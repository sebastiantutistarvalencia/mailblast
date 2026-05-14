@echo off
echo.
echo  Instalando dependencias...
pip install flask -q
echo.
echo  Abriendo MailBlast en http://localhost:7000
echo  (Presiona Ctrl+C para detener)
echo.
start "" http://localhost:7000
python app.py
pause
