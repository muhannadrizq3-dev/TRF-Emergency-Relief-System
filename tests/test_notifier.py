import unittest
from unittest import mock

import notifier
from notifier import Notifier, build_message
from tests.helpers import NOW, FakeSender, make_store

SHELTER = {"name": "Shelter B", "area": "Al Nahda, Sharjah", "latitude": 25.3, "longitude": 55.372}
SUPPLY = {"name": "food", "unit": "meal packs"}
SENDER = {"display_name": "Toka Ahmed", "username": "toka"}
REQUEST = {"quantity": 60, "is_sos": 1, "note": "power cut"}
ALL_CHANNELS = {"telegram": {"token": "t", "chat_id": "c"}, "whatsapp": {"phone": "+971", "apikey": "k"},
                "email": {"host": "h", "port": 587, "user": "u", "password": "p", "to": "x@y.ae"}}


class MessageTests(unittest.TestCase):
    def test_message_contains_location_sender_and_time(self):
        text = build_message(REQUEST, SHELTER, SUPPLY, SENDER, NOW)
        for part in ("SOS", "Shelter B", "25.30000, 55.37200", "60 meal packs of food",
                     "Toka Ahmed (@toka)", "2026-11-01 12:00 UTC", "power cut", "999", "Demo alert"):
            self.assertIn(part, text)

    def test_non_sos_label(self):
        text = build_message({**REQUEST, "is_sos": 0, "note": ""}, SHELTER, SUPPLY, SENDER, NOW)
        self.assertIn("CRITICAL REQUEST", text)
        self.assertNotIn("Note:", text)


class NotifierTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def test_sends_on_every_channel(self):
        fakes = {name: FakeSender() for name in ALL_CHANNELS}
        n = Notifier(self.store, channels=ALL_CHANNELS, senders=fakes)
        self.assertEqual(n.send("hello"), ["telegram", "whatsapp", "email"])
        self.assertEqual(n.recent()[0]["channel"], "telegram,whatsapp,email")
        self.assertEqual(fakes["whatsapp"].calls[0], (ALL_CHANNELS["whatsapp"], "hello"))

    def test_one_failing_channel_does_not_stop_others(self):
        fakes = {"telegram": FakeSender(error=OSError("offline")), "whatsapp": FakeSender(), "email": FakeSender(ok=False)}
        n = Notifier(self.store, channels=ALL_CHANNELS, senders=fakes)
        with self.assertLogs("trf.notifier", level="WARNING"):
            self.assertEqual(n.send("hello"), ["whatsapp"])

    def test_falls_back_to_log_without_channels(self):
        n = Notifier(self.store, channels={})
        with self.assertLogs("trf.notifier", level="WARNING") as logs:
            self.assertEqual(n.send("hello"), [])
        self.assertIn("fallback log", "\n".join(logs.output))
        row = n.recent()[0]
        self.assertEqual((row["channel"], row["delivered"]), ("log", 0))

    def test_falls_back_when_all_channels_fail(self):
        n = Notifier(self.store, channels={"telegram": ALL_CHANNELS["telegram"]},
                     senders={"telegram": FakeSender(error=TimeoutError())})
        with self.assertLogs("trf.notifier", level="WARNING"):
            self.assertEqual(n.send("hello"), [])
        self.assertEqual(n.recent()[0]["delivered"], 0)

    def test_alert_for_request_stores_alert(self):
        n = Notifier(self.store, channels={"telegram": ALL_CHANNELS["telegram"]}, senders={"telegram": FakeSender()})
        n.alert_for_request(REQUEST, SHELTER, SUPPLY, SENDER)
        self.assertIn("Shelter B", n.recent()[0]["message"])

    def test_channels_come_from_settings(self):
        with mock.patch.multiple(notifier.settings, TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="c",
                                 WHATSAPP_PHONE="", WHATSAPP_APIKEY="", SMTP_HOST="smtp.gmail.com",
                                 SMTP_USER="u", SMTP_PASSWORD="p", ALERT_EMAIL_TO="team@example.com"):
            self.assertEqual(list(notifier.channels_from_settings()), ["telegram", "email"])


if __name__ == "__main__":
    unittest.main()
