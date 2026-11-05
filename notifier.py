import json
import logging
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

import settings
from storage import to_iso, utcnow

log = logging.getLogger("trf.notifier")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
CALLMEBOT_API = "https://api.callmebot.com/whatsapp.php"


def build_message(request, shelter, supply, sender, when=None):
    when = when or utcnow()
    kind = "SOS" if request.get("is_sos") else "CRITICAL REQUEST"
    lines = [
        f"🚨 {kind} — {settings.APP_NAME}",
        f"Shelter: {shelter['name']} ({shelter.get('area') or 'no area'})",
        f"Location: {shelter['latitude']:.5f}, {shelter['longitude']:.5f}",
        f"Map: https://www.openstreetmap.org/?mlat={shelter['latitude']}&mlon={shelter['longitude']}#map=16/{shelter['latitude']}/{shelter['longitude']}",
        f"Needs: {request['quantity']} {supply['unit']} of {supply['name']}",
        f"Sent by: {sender['display_name']} (@{sender['username']})",
        f"Time: {when.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if request.get("note"):
        lines.append(f"Note: {request['note']}")
    lines.append("Real emergency? Call 999 Police · 998 Ambulance · 997 Civil Defence")
    return "\n".join(lines)


def send_telegram(cfg, text, timeout=5):
    data = urllib.parse.urlencode({"chat_id": cfg["chat_id"], "text": text}).encode()
    req = urllib.request.Request(TELEGRAM_API.format(token=cfg["token"]), data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return bool(json.loads(resp.read().decode() or "{}").get("ok"))


def send_whatsapp(cfg, text, timeout=8):
    query = urllib.parse.urlencode({"phone": cfg["phone"], "text": text, "apikey": cfg["apikey"]})
    with urllib.request.urlopen(f"{CALLMEBOT_API}?{query}", timeout=timeout) as resp:
        return 200 <= resp.status < 300


def send_email(cfg, text, timeout=8):
    msg = EmailMessage()
    msg["Subject"] = text.splitlines()[0]
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    msg.set_content(text)
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=timeout) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)
    return True


def channels_from_settings():
    channels = {}
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        channels["telegram"] = {"token": settings.TELEGRAM_BOT_TOKEN, "chat_id": settings.TELEGRAM_CHAT_ID}
    if settings.WHATSAPP_PHONE and settings.WHATSAPP_APIKEY:
        channels["whatsapp"] = {"phone": settings.WHATSAPP_PHONE, "apikey": settings.WHATSAPP_APIKEY}
    if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD and settings.ALERT_EMAIL_TO:
        channels["email"] = {"host": settings.SMTP_HOST, "port": settings.SMTP_PORT, "user": settings.SMTP_USER,
                             "password": settings.SMTP_PASSWORD, "to": settings.ALERT_EMAIL_TO}
    return channels


DEFAULT_SENDERS = {"telegram": send_telegram, "whatsapp": send_whatsapp, "email": send_email}


class Notifier:
    def __init__(self, store, channels=None, senders=None):
        self.store = store
        self.channels = channels_from_settings() if channels is None else channels
        self.senders = dict(DEFAULT_SENDERS, **(senders or {}))

    @property
    def enabled_channels(self):
        return list(self.channels)

    def send(self, text):
        delivered = []
        for name, cfg in self.channels.items():
            try:
                if self.senders[name](cfg, text):
                    delivered.append(name)
                else:
                    log.warning("%s alert was not accepted", name)
            except Exception as exc:
                log.warning("%s alert failed: %s", name, exc)
        if not delivered:
            log.warning("ALERT (fallback log):\n%s", text)
        self.store.insert(
            "INSERT INTO alerts (message, channel, delivered, created_at) VALUES (?, ?, ?, ?)",
            (text, ",".join(delivered) if delivered else "log", 1 if delivered else 0, to_iso(utcnow())),
        )
        return delivered

    def alert_for_request(self, request, shelter, supply, sender):
        return self.send(build_message(request, shelter, supply, sender))

    def recent(self, limit=20):
        return self.store.query("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (int(limit),))
