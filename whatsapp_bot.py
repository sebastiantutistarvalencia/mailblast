from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
import time, urllib.parse, os, random

SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wa_session')


class WhatsAppBot:
    def __init__(self):
        self.driver = None
        self.status  = 'disconnected'  # disconnected|loading|waiting_qr|connected|error
        self.error   = None

    def connect(self):
        try:
            self.status = 'loading'
            self.error  = None
            os.makedirs(SESSION_DIR, exist_ok=True)

            opts = webdriver.ChromeOptions()
            opts.add_argument(f'--user-data-dir={SESSION_DIR}')
            opts.add_argument('--profile-directory=WA_Profile')
            opts.add_argument('--no-sandbox')
            opts.add_argument('--disable-dev-shm-usage')
            opts.add_experimental_option('excludeSwitches', ['enable-logging'])
            opts.add_experimental_option('useAutomationExtension', False)

            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=opts)
            self.driver.maximize_window()
            self.driver.get('https://web.whatsapp.com')
            self.status = 'waiting_qr'

            # Detect connected: search input appears
            WebDriverWait(self.driver, 90).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')
                )
            )
            self.status = 'connected'

        except TimeoutException:
            self.status = 'error'
            self.error  = 'Tiempo agotado. Escanea el QR antes de 90 segundos.'
        except WebDriverException as e:
            self.status = 'error'
            self.error  = f'Chrome error: {e.msg}'
        except Exception as e:
            self.status = 'error'
            self.error  = str(e)

    def send_message(self, phone, message):
        if self.status != 'connected' or not self.driver:
            raise Exception('WhatsApp no está conectado')

        # Normalize phone: only digits
        phone_clean = ''.join(c for c in phone if c.isdigit())

        url = (f'https://web.whatsapp.com/send'
               f'?phone={phone_clean}&text={urllib.parse.quote(message)}')
        self.driver.get(url)

        wait = WebDriverWait(self.driver, 20)
        try:
            # Send button (language-agnostic selector)
            send_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//span[@data-icon="send"]'))
            )
            send_btn.click()
            # Random delay: 3–6 s to reduce ban risk
            time.sleep(random.uniform(3.0, 6.0))
        except TimeoutException:
            raise Exception(f'Número {phone} sin WhatsApp o inválido')

    def disconnect(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self.status = 'disconnected'
        self.error  = None


wa_bot = WhatsAppBot()
