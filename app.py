from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, send_from_directory
import smtplib, ssl, os, uuid, threading, time, urllib.parse, mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime
try:
    from whatsapp_bot import wa_bot
    WA_AVAILABLE = True
except Exception as _wa_err:
    print(f"WhatsApp no disponible en este entorno: {_wa_err}")
    WA_AVAILABLE = False
    wa_bot = None

app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

campaigns    = {}
send_progress = {}
wa_sessions  = {}

TRACKING_PIXEL = bytes([
    0x47,0x49,0x46,0x38,0x39,0x61,0x01,0x00,0x01,0x00,
    0x80,0x00,0x00,0xff,0xff,0xff,0x00,0x00,0x00,0x21,
    0xf9,0x04,0x01,0x00,0x00,0x00,0x00,0x2c,0x00,0x00,
    0x00,0x00,0x01,0x00,0x01,0x00,0x00,0x02,0x02,0x44,
    0x01,0x00,0x3b
])

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

SOCIAL_COLORS = {
    'instagram': '#E1306C',
    'facebook':  '#1877F2',
    'tiktok':    '#000000',
    'youtube':   '#FF0000',
    'twitter':   '#1DA1F2',
    'whatsapp':  '#25D366',
    'linkedin':  '#0A66C2',
}
SOCIAL_LABELS = {
    'instagram': 'IG', 'facebook': 'FB', 'tiktok': 'TT',
    'youtube': 'YT', 'twitter': 'X', 'whatsapp': 'WA', 'linkedin': 'IN',
}
SOCIAL_EMOJI = {
    'instagram': '📸', 'facebook': '👤', 'tiktok': '🎵',
    'youtube': '▶', 'twitter': '𝕏', 'whatsapp': '💬', 'linkedin': '💼',
}


def build_social_html(social):
    """Generate email-safe table HTML for social media icons."""
    if not social or not any(social.values()):
        return ''
    icons = ''
    for platform, url in social.items():
        if not url:
            continue
        color = SOCIAL_COLORS.get(platform, '#888888')
        label = SOCIAL_LABELS.get(platform, platform[:2].upper())
        icons += (
            f'<a href="{url}" style="display:inline-block;margin:0 4px;width:40px;height:40px;'
            f'border-radius:50%;background-color:{color};text-align:center;line-height:40px;'
            f'color:#ffffff;font-size:13px;font-weight:700;text-decoration:none;'
            f'font-family:Arial,Helvetica,sans-serif">{label}</a>'
        )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation">'
        '<tr><td align="center" style="padding:24px 20px;background-color:#f8f8fc;border-top:1px solid #eeeeee">'
        '<p style="margin:0 0 14px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;'
        'font-weight:600;color:#aaaaaa;text-transform:uppercase;letter-spacing:1px">'
        'S&#237;guenos en redes sociales</p>'
        + icons +
        '</td></tr></table>'
    )


def build_mime(subject, from_str, to_email, html, image_path=None):
    """Build MIME message. Uses CID inline embed if image_path is given."""
    if image_path and os.path.isfile(image_path):
        # related → alternative + inline image
        msg = MIMEMultipart('related')
        alt = MIMEMultipart('alternative')
        msg.attach(alt)
        alt.attach(MIMEText(html.replace('{{cid_image}}', 'cid:mainimage'), 'html', 'utf-8'))

        mime_type, _ = mimetypes.guess_type(image_path)
        subtype = (mime_type or 'image/jpeg').split('/')[-1]
        with open(image_path, 'rb') as f:
            img = MIMEImage(f.read(), _subtype=subtype)
        img.add_header('Content-ID', '<mainimage>')
        img.add_header('Content-Disposition', 'inline', filename=os.path.basename(image_path))
        msg.attach(img)
    else:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(html, 'html', 'utf-8'))

    msg['Subject'] = subject
    msg['From']    = from_str
    msg['To']      = to_email
    msg['Message-ID'] = f"<{uuid.uuid4()}@mailer>"
    return msg


def send_emails_thread(campaign_id, smtp_cfg, recipients, subject, template,
                       host_url, redirect_url='', image_path='', image_url='', social=None):
    # Decide image source: local file (CID) takes priority over URL
    use_cid = bool(image_path and os.path.isfile(image_path))
    fallback_img = image_url or 'https://picsum.photos/600/300?random=42'

    social_html = build_social_html(social or {})

    try:
        ctx = ssl.create_default_context()
        port = int(smtp_cfg['port'])
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_cfg['host'], port, context=ctx)
        else:
            server = smtplib.SMTP(smtp_cfg['host'], port)
            server.ehlo()
            server.starttls(context=ctx)
        server.login(smtp_cfg['user'], smtp_cfg['password'])

        for recipient in recipients:
            try:
                rid = str(uuid.uuid4())[:8]
                base_track = f"{host_url}track/{campaign_id}/{rid}"
                click_link = (base_track + '?url=' + urllib.parse.quote(redirect_url, safe='')
                              if redirect_url else base_track)

                html = template
                html = html.replace('{{name}}',      recipient.get('name') or 'Amigo/a')
                html = html.replace('{{email}}',     recipient['email'])
                html = html.replace('{{click_link}}', click_link)
                html = html.replace('{{unsub_link}}', f"{host_url}unsub/{campaign_id}/{rid}")
                html = html.replace('{{social_links}}', social_html)

                # Image: CID or URL
                if use_cid:
                    # {{image_url}} → {{cid_image}} placeholder; build_mime swaps it for cid:mainimage
                    html = html.replace('{{image_url}}', '{{cid_image}}')
                else:
                    html = html.replace('{{image_url}}', fallback_img)
                    html = html.replace('{{cid_image}}', fallback_img)

                # Tracking pixel
                pixel = (f'<img src="{host_url}open/{campaign_id}/{rid}" '
                         f'width="1" height="1" alt="" style="opacity:0">')
                html = html.replace('</body>', f'{pixel}</body>')

                from_str = f"{smtp_cfg.get('from_name', 'Newsletter')} <{smtp_cfg['user']}>"
                msg = build_mime(subject, from_str, recipient['email'], html,
                                 image_path if use_cid else None)

                server.sendmail(smtp_cfg['user'], [recipient['email']], msg.as_string())
                send_progress[campaign_id]['sent'] += 1
                campaigns[campaign_id]['sent'] += 1
                time.sleep(0.15)
            except Exception as e:
                send_progress[campaign_id]['failed'] += 1
                campaigns[campaign_id]['failed'] += 1
                print(f"Error → {recipient['email']}: {e}")

        server.quit()
    except Exception as e:
        send_progress[campaign_id]['error'] = str(e)
        campaigns[campaign_id]['error'] = str(e)
        print(f"Error SMTP: {e}")
    finally:
        send_progress[campaign_id]['done'] = True


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No se recibió archivo'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Nombre de archivo vacío'}), 400
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_EXT:
        return jsonify({'error': f'Tipo .{ext} no permitido. Usa PNG, JPG, GIF o WEBP'}), 400
    fname = str(uuid.uuid4())[:12] + '.' + ext
    fpath = os.path.join(UPLOAD_FOLDER, fname)
    f.save(fpath)
    return jsonify({'path': fpath, 'preview_url': f'/static/uploads/{fname}'})


@app.route('/static/uploads/<path:fname>')
def serve_upload(fname):
    return send_from_directory(UPLOAD_FOLDER, fname)


@app.route('/api/send', methods=['POST'])
def start_campaign():
    data = request.json
    cid = str(uuid.uuid4())[:8].upper()
    n = len(data['recipients'])
    campaigns[cid] = {
        'id': cid, 'subject': data['subject'],
        'total': n, 'sent': 0, 'failed': 0, 'opens': 0, 'clicks': 0,
        'created_at': datetime.now().strftime('%H:%M:%S')
    }
    # Inicializar ANTES de arrancar el hilo para evitar race condition en polls
    send_progress[cid] = {'total': n, 'sent': 0, 'failed': 0, 'done': False, 'error': None}
    t = threading.Thread(
        target=send_emails_thread,
        args=(cid, data['smtp'], data['recipients'], data['subject'], data['template'],
              request.host_url, data.get('redirect_url', ''),
              data.get('image_path', ''), data.get('image_url', ''),
              data.get('social', {})),
        daemon=True
    )
    t.start()
    return jsonify({'campaign_id': cid})


@app.route('/api/progress/<cid>')
def get_progress(cid):
    return jsonify(send_progress.get(cid, {'error': 'No encontrada'}))


@app.route('/api/campaigns')
def list_campaigns():
    return jsonify(list(reversed(list(campaigns.values()))))


@app.route('/track/<cid>/<rid>')
def track_click(cid, rid):
    if cid in campaigns:
        campaigns[cid]['clicks'] = campaigns[cid].get('clicks', 0) + 1
    dest = request.args.get('url')
    return redirect(dest if dest else url_for('landing', cid=cid, rid=rid))


@app.route('/open/<cid>/<rid>')
def track_open(cid, rid):
    if cid in campaigns:
        campaigns[cid]['opens'] = campaigns[cid].get('opens', 0) + 1
    return Response(TRACKING_PIXEL, mimetype='image/gif')


@app.route('/unsub/<cid>/<rid>')
def unsubscribe(cid, rid):
    return ('<html><body style="font-family:sans-serif;text-align:center;padding:80px;'
            'background:#0a0a0f;color:#e0e0e0">'
            '<h2 style="color:#7c3aed">✓ Removido exitosamente</h2>'
            '<p>No recibirás más correos de esta campaña.</p></body></html>')


@app.route('/landing/<cid>/<rid>')
def landing(cid, rid):
    return render_template('landing.html', campaign=campaigns.get(cid, {}))


# ── WHATSAPP ──────────────────────────────────────────────────────────────────

@app.route('/api/wa/connect', methods=['POST'])
def wa_connect():
    if not WA_AVAILABLE:
        return jsonify({'error': 'WhatsApp no disponible en este servidor. Usa la version local.'}), 503
    if wa_bot.status == 'connected':
        return jsonify({'status': 'connected'})
    if wa_bot.status in ('loading', 'waiting_qr'):
        return jsonify({'status': wa_bot.status})
    threading.Thread(target=wa_bot.connect, daemon=True).start()
    return jsonify({'status': 'loading'})


@app.route('/api/wa/status')
def wa_status():
    return jsonify({'status': wa_bot.status, 'error': wa_bot.error})


@app.route('/api/wa/disconnect', methods=['POST'])
def wa_disconnect():
    threading.Thread(target=wa_bot.disconnect, daemon=True).start()
    return jsonify({'status': 'disconnected'})


def _wa_send_thread(sid, contacts, template):
    wa_sessions[sid] = {'total': len(contacts), 'sent': 0, 'failed': 0,
                        'done': False, 'errors': []}
    for c in contacts:
        try:
            msg = (template
                   .replace('{{name}}',  c.get('name')  or 'Amigo/a')
                   .replace('{{phone}}', c.get('phone', '')))
            wa_bot.send_message(c['phone'], msg)
            wa_sessions[sid]['sent'] += 1
        except Exception as e:
            wa_sessions[sid]['failed'] += 1
            wa_sessions[sid]['errors'].append(str(e))
    wa_sessions[sid]['done'] = True


@app.route('/api/wa/send', methods=['POST'])
def wa_send():
    data = request.json
    sid  = str(uuid.uuid4())[:8].upper()
    threading.Thread(
        target=_wa_send_thread,
        args=(sid, data['contacts'], data['message']),
        daemon=True
    ).start()
    return jsonify({'session_id': sid})


@app.route('/api/wa/progress/<sid>')
def wa_progress(sid):
    return jsonify(wa_sessions.get(sid, {'error': 'No encontrado'}))


# ── CSV PARSE (server-side fallback) ──────────────────────────────────────────

@app.route('/api/csv', methods=['POST'])
def parse_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'Sin archivo'}), 400
    text = request.files['file'].read().decode('utf-8-sig', errors='replace')
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return jsonify({'contacts': []})

    sep = ';' if lines[0].count(';') > lines[0].count(',') else ','
    headers = [h.strip().strip('"\'').lower() for h in lines[0].split(sep)]

    name_idx  = next((i for i, h in enumerate(headers) if h in ('nombre','name','nombres')), -1)
    email_idx = next((i for i, h in enumerate(headers) if h in ('email','correo','mail','e-mail')), -1)
    phone_idx = next((i for i, h in enumerate(headers)
                      if h in ('telefono','teléfono','phone','celular','movil','móvil','whatsapp','tel')), -1)

    contacts = []
    for line in lines[1:]:
        cols = [c.strip().strip('"\'') for c in line.split(sep)]
        entry = {
            'name':  cols[name_idx]  if name_idx  >= 0 and name_idx  < len(cols) else '',
            'email': cols[email_idx] if email_idx >= 0 and email_idx < len(cols) else '',
            'phone': cols[phone_idx] if phone_idx >= 0 and phone_idx < len(cols) else '',
        }
        # Auto-detect if no header match
        if not entry['email'] and not entry['phone']:
            for col in cols:
                if '@' in col and not entry['email']:
                    entry['email'] = col
                if col.replace('+','').replace(' ','').replace('-','').isdigit() and len(col) >= 7 and not entry['phone']:
                    entry['phone'] = col
        if entry['email'] or entry['phone']:
            contacts.append(entry)

    return jsonify({'contacts': contacts, 'total': len(contacts)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7000))
    print(f"\n  MailBlast en http://localhost:{port}\n")
    app.run(debug=False, port=port, host='0.0.0.0')
