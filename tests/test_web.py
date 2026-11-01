import io
import unittest
from datetime import timedelta

import emergency_requests as er
import inventory
import storage
from notifier import Notifier
from tests.helpers import FakeSender, csrf, make_store
from web_app import (AuthError, authenticate, create_app, make_reset_token, read_reset_token, register_user,
                     reset_password)

PASSWORD = "Passw0rd1"


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.sender = FakeSender()
        self.app = create_app(self.store, testing=True,
                              notifier=Notifier(self.store, channels={"telegram": {"token": "t", "chat_id": "c"}},
                                                senders={"telegram": self.sender}))
        self.client = self.app.test_client()

    def signup(self, username, role="shelter_staff", email=None):
        token = csrf(self.client, "/signup")
        return self.client.post("/signup", data={
            "csrf_token": token, "username": username, "display_name": username.title() + " Test",
            "email": email or f"{username}@example.com",
            "password": PASSWORD, "confirm": PASSWORD, "role": role, "agree": "1",
        })

    def login(self, login, password=PASSWORD, remember=False):
        token = csrf(self.client, "/login")
        data = {"csrf_token": token, "login": login, "password": password}
        if remember:
            data["remember"] = "1"
        return self.client.post("/login", data=data)

    def logout(self):
        self.client.post("/logout", data={"csrf_token": csrf(self.client, "/dashboard")})

    def post(self, path, data, **kw):
        data = dict(data, csrf_token=csrf(self.client, "/dashboard"))
        return self.client.post(path, data=data, **kw)

    def user(self, username):
        return self.store.query_one("SELECT * FROM users WHERE username = ?", (username,))


class AuthTests(WebTestCase):
    def test_first_account_becomes_coordinator(self):
        self.signup("muhannad", role="volunteer")
        self.assertEqual(self.user("muhannad")["role"], "coordinator")

    def test_later_accounts_cannot_claim_coordinator(self):
        self.signup("muhannad")
        self.logout()
        self.signup("intruder", role="coordinator")
        self.assertEqual(self.user("intruder")["role"], "volunteer")

    def test_passwords_are_hashed(self):
        self.signup("muhannad")
        stored = self.user("muhannad")["password_hash"]
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))

    def test_weak_password_rejected(self):
        with self.assertRaises(AuthError):
            register_user(self.store, "toka", "Toka", "password", "volunteer")

    def test_bad_username_and_email_rejected(self):
        with self.assertRaises(AuthError):
            register_user(self.store, "<b>x</b>", "x", PASSWORD, "volunteer")
        with self.assertRaises(AuthError):
            register_user(self.store, "toka", "Toka", PASSWORD, "volunteer", email="not-an-email")

    def test_duplicate_email_rejected(self):
        register_user(self.store, "toka", "Toka", PASSWORD, "volunteer", email="t@example.com")
        with self.assertRaises(AuthError):
            register_user(self.store, "toka2", "Toka", PASSWORD, "volunteer", email="T@Example.com")

    def test_login_with_username_or_email(self):
        register_user(self.store, "reima", "Reima", PASSWORD, "volunteer", email="reima@example.com")
        self.assertEqual(authenticate(self.store, "REIMA", PASSWORD)["username"], "reima")
        self.assertEqual(authenticate(self.store, "Reima@Example.com", PASSWORD)["username"], "reima")

    def test_login_and_logout(self):
        register_user(self.store, "toka", "Toka", PASSWORD, "volunteer")
        self.assertEqual(self.login("toka").status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.logout()
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_remember_me_sets_lasting_cookie(self):
        register_user(self.store, "toka", "Toka", PASSWORD, "volunteer")
        resp = self.login("toka", remember=True)
        self.assertIn("Expires=", resp.headers["Set-Cookie"])
        self.logout()
        resp = self.login("toka")
        self.assertNotIn("Expires=", resp.headers["Set-Cookie"])

    def test_lockout_after_five_failures(self):
        register_user(self.store, "reima", "Reima", PASSWORD, "volunteer")
        for _ in range(5):
            with self.assertRaises(AuthError):
                authenticate(self.store, "reima", "wrong")
        with self.assertRaises(AuthError) as ctx:
            authenticate(self.store, "reima", PASSWORD)
        self.assertIn("locked", str(ctx.exception).lower())

    def test_lock_expires_after_15_minutes(self):
        register_user(self.store, "reima", "Reima", PASSWORD, "volunteer")
        for _ in range(5):
            with self.assertRaises(AuthError):
                authenticate(self.store, "reima", "wrong")
        later = storage.utcnow() + timedelta(minutes=16)
        self.assertEqual(authenticate(self.store, "reima", PASSWORD, now=later)["username"], "reima")

    def test_coordinator_password_reset(self):
        uid = register_user(self.store, "fatyma", "Fatyma", PASSWORD, "volunteer")
        _, temp = reset_password(self.store, uid)
        self.assertEqual(authenticate(self.store, "fatyma", temp)["id"], uid)
        with self.assertRaises(AuthError):
            authenticate(self.store, "fatyma", PASSWORD)

    def test_open_redirect_blocked(self):
        register_user(self.store, "toka", "Toka", PASSWORD, "volunteer")
        token = csrf(self.client, "/login")
        resp = self.client.post("/login?next=//evil.example", data={
            "csrf_token": token, "login": "toka", "password": PASSWORD})
        self.assertTrue(resp.headers["Location"].endswith("/dashboard"))


class ResetLinkTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.app.mailer = lambda to, subject, body: self.sent.append((to, subject, body))
        register_user(self.store, "muhannad", "Muhannad Rizq", PASSWORD, "volunteer", email="m@example.com")

    def request_link(self, email):
        token = csrf(self.client, "/forgot-password")
        return self.client.post("/forgot-password", data={"csrf_token": token, "email": email})

    def test_reset_link_changes_password_once(self):
        self.request_link("M@Example.com")
        self.assertEqual(self.sent[0][0], "m@example.com")
        link = [w for w in self.sent[0][2].split() if "/reset-password/" in w][0]
        path = link[link.index("/reset-password/"):]
        token = csrf(self.client, path)
        self.client.post(path, data={"csrf_token": token, "password": "NewPass123", "confirm": "NewPass123"})
        self.assertEqual(authenticate(self.store, "muhannad", "NewPass123")["username"], "muhannad")
        self.assertEqual(self.client.get(path).status_code, 302)

    def test_unknown_email_gives_same_answer_and_sends_nothing(self):
        resp = self.request_link("nobody@example.com")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sent, [])

    def test_tampered_token_rejected(self):
        user = self.user("muhannad")
        token = make_reset_token(self.app.config["SECRET_KEY"], user)
        self.assertIsNotNone(read_reset_token(self.store, self.app.config["SECRET_KEY"], token))
        self.assertIsNone(read_reset_token(self.store, self.app.config["SECRET_KEY"], token + "x"))
        self.assertIsNone(read_reset_token(self.store, "other-secret", token))

    def test_without_email_settings_page_explains_coordinator_reset(self):
        self.app.mailer = None
        html = self.client.get("/forgot-password").get_data(as_text=True)
        self.assertIn("Reset password", html)
        self.assertNotIn('name="email"', html)


class SignupFormTests(WebTestCase):
    def test_form_keeps_values_after_error(self):
        self.signup("muhannad")
        self.logout()
        token = csrf(self.client, "/signup")
        html = self.client.post("/signup", data={
            "csrf_token": token, "username": "toka", "display_name": "Toka Ahmed", "email": "toka@example.com",
            "password": PASSWORD, "confirm": "different1", "role": "shelter_staff", "agree": "1"}).get_data(as_text=True)
        self.assertIn('value="Toka Ahmed"', html)
        self.assertIn('value="toka@example.com"', html)
        self.assertIn('value="shelter_staff" selected', html)

    def test_signup_page_matches_design(self):
        self.signup("muhannad")
        self.logout()
        html = self.client.get("/signup").get_data(as_text=True)
        for text in ("Join the TRF relief team in under a minute.", "Coordinators are chosen by an existing coordinator.",
                     "Used to reset your password if you forget it.", 'data-reveal="confirm"', "Cookie Policy"):
            self.assertIn(text, html)


class SecurityTests(WebTestCase):
    def test_post_without_csrf_rejected(self):
        resp = self.client.post("/login", data={"login": "x", "password": "y"})
        self.assertEqual(resp.status_code, 400)

    def test_security_headers_present(self):
        resp = self.client.get("/login")
        for header in ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
            self.assertIn(header, resp.headers)
        self.assertNotIn("unsafe-inline", resp.headers["Content-Security-Policy"])

    def test_pages_require_login(self):
        for path in ("/dashboard", "/api/map-data", "/export/requests.csv", "/requests/1/edit"):
            self.assertEqual(self.client.get(path).status_code, 302, path)

    def test_staff_cannot_use_coordinator_actions(self):
        self.signup("muhannad")
        self.logout()
        self.signup("staff")
        for path, data in [("/stock/add", {"supply_type_id": 1, "quantity": 5}),
                           ("/shelters", {"name": "X", "latitude": 25, "longitude": 55}),
                           ("/reset-demo", {}), ("/start-empty", {}), ("/dispatch/auto", {}),
                           ("/users/1/role", {"role": "volunteer"})]:
            self.assertEqual(self.post(path, data).status_code, 403, path)

    def test_volunteer_cannot_create_requests(self):
        self.signup("muhannad")
        self.logout()
        self.signup("vol", role="volunteer")
        resp = self.post("/requests/new", {"shelter_id": 1, "supply_type_id": 1, "quantity": 5, "priority": "low"})
        self.assertEqual(resp.status_code, 403)

    def test_staff_cannot_edit_someone_elses_request(self):
        self.signup("muhannad")
        self.post("/requests/new", {"shelter_id": 1, "supply_type_id": 1, "quantity": 5, "priority": "low"})
        self.logout()
        self.signup("staff")
        self.assertEqual(self.client.get("/requests/1/edit").status_code, 403)
        self.assertEqual(self.post("/requests/1/cancel", {}).status_code, 403)

    def test_note_is_html_escaped(self):
        self.signup("muhannad")
        self.post("/requests/new", {"shelter_id": 1, "supply_type_id": 1, "quantity": 5,
                                    "priority": "low", "note": "<script>alert(1)</script>"})
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


class FeatureTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.signup("muhannad")

    def test_dashboard_has_every_section(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        for section in ("overview", "inventory", "new-request", "requests", "shelters", "reports", "data", "activity", "team"):
            self.assertIn(f'id="{section}"', html)
        self.assertIn("Welcome back, Muhannad", html)

    def test_create_request_and_see_it(self):
        resp = self.post("/requests/new", {"shelter_id": 2, "supply_type_id": 2, "quantity": 60, "priority": "high"})
        self.assertEqual(resp.status_code, 302)
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("0 / 60", html)
        self.assertEqual(self.sender.calls, [])

    def test_critical_request_alerts(self):
        self.post("/requests/new", {"shelter_id": 1, "supply_type_id": 3, "quantity": 5, "priority": "critical"})
        self.assertEqual(len(self.sender.calls), 1)

    def test_sos_sends_alert(self):
        token = csrf(self.client, "/sos")
        self.client.post("/sos", data={"csrf_token": token, "shelter_id": 1, "supply_type_id": 3, "quantity": 5, "note": "injuries"})
        self.assertEqual(len(self.sender.calls), 1)
        self.assertIn("SOS", self.sender.calls[0][1])

    def test_public_sos_page_shows_numbers(self):
        self.logout()
        html = self.client.get("/sos").get_data(as_text=True)
        for number in ("999", "998", "997"):
            self.assertIn(f'tel:{number}', html)
        self.assertEqual(self.client.post("/sos", data={"csrf_token": csrf(self.client, "/login")}).status_code, 403)

    def test_auto_dispatch_route(self):
        self.post("/requests/new", {"shelter_id": 1, "supply_type_id": 1, "quantity": 10, "priority": "low"})
        self.post("/dispatch/auto", {})
        self.assertEqual(er.list_requests(self.store)[0]["status"], "fulfilled")

    def test_add_stock_and_new_supply_type(self):
        self.post("/stock/add", {"supply_type_id": 1, "quantity": "5"})
        self.assertEqual(inventory.get_supply(self.store, 1)["quantity"], 105)
        self.post("/supply-types", {"name": "Tents", "quantity": "12"})
        self.assertEqual(inventory.get_supply_by_name(self.store, "tents")["quantity"], 12)

    def test_add_and_remove_shelter(self):
        self.post("/shelters", {"name": "Shelter D", "area": "Al Khan", "latitude": "25.32", "longitude": "55.36"})
        sid = self.store.query_one("SELECT id FROM shelters WHERE name = 'Shelter D'")["id"]
        self.post(f"/shelters/{sid}/delete", {})
        self.assertEqual(self.store.count("shelters"), 3)

    def test_csv_import_route(self):
        resp = self.post("/import", {"kind": "shelters", "file": (io.BytesIO(b"name,area,lat,lng\nShelter D,Al Khan,25.32,55.36\n"), "s.csv")},
                         content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.store.count("shelters"), 4)

    def test_csv_import_rejects_non_csv(self):
        self.post("/import", {"kind": "supplies", "file": (io.BytesIO(b"item,quantity\nwater,5\n"), "s.txt")},
                  content_type="multipart/form-data")
        self.assertEqual(inventory.get_supply(self.store, 1)["quantity"], 100)

    def test_exports(self):
        for kind in ("supplies", "requests", "shelters", "activity"):
            resp = self.client.get(f"/export/{kind}.csv")
            self.assertEqual((resp.status_code, resp.mimetype), (200, "text/csv"), kind)
        self.assertEqual(self.client.get("/export/users.csv").status_code, 404)

    def test_map_data_json(self):
        data = self.client.get("/api/map-data").get_json()
        self.assertEqual(len(data["shelters"]), 3)
        self.assertEqual(data["shelters"][0]["waiting"], 0)

    def test_change_role_and_activity_log(self):
        self.logout()
        self.signup("toka")
        self.logout()
        self.login("muhannad")
        uid = self.user("toka")["id"]
        self.post(f"/users/{uid}/role", {"role": "volunteer"})
        self.assertEqual(self.user("toka")["role"], "volunteer")
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("changed Toka Test&#39;s role to Volunteer", html)

    def test_cannot_demote_self(self):
        self.post(f"/users/{self.user('muhannad')['id']}/role", {"role": "volunteer"})
        self.assertEqual(self.user("muhannad")["role"], "coordinator")

    def test_start_empty_and_reset_demo(self):
        self.post("/start-empty", {})
        self.assertEqual((self.store.count("supply_types"), self.store.count("shelters")), (0, 0))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.post("/reset-demo", {})
        self.assertEqual((self.store.count("supply_types"), self.store.count("shelters")), (3, 3))
        self.assertEqual(self.store.count("users"), 1)

    def test_arabic_interface(self):
        self.client.get("/lang/ar")
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn('dir="rtl"', html)
        self.assertIn("نظرة عامة", html)

    def test_public_pages(self):
        self.assertEqual(self.client.get("/healthz").get_json()["status"], "ok")
        for path in ("/terms", "/cookies", "/forgot-password", "/signup"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/does-not-exist").status_code, 404)


if __name__ == "__main__":
    unittest.main()


class TeamAccountTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.app = create_app(self.store, testing=True, team_accounts=True,
                              notifier=Notifier(self.store, channels={}))

    def test_four_team_coordinators_exist(self):
        rows = self.store.query("SELECT username, display_name, role FROM users ORDER BY id")
        self.assertEqual([(r["username"], r["display_name"], r["role"]) for r in rows], [
            ("muhannad", "Muhannad Rizq", "coordinator"), ("toka", "Toka Ahmed", "coordinator"),
            ("reima", "Reima Aboamir", "coordinator"), ("fatyma", "Fatyma Iskhakova", "coordinator")])

    def test_passwords_are_not_stored_in_plain_text(self):
        import settings
        for _, _, _, password_hash in settings.TEAM_ACCOUNTS:
            self.assertTrue(password_hash.startswith("scrypt:"))

    def test_accounts_come_back_after_a_restart_without_duplicates(self):
        create_app(self.store, testing=True, team_accounts=True, notifier=Notifier(self.store, channels={}))
        self.assertEqual(self.store.count("users"), 4)

    def test_new_signups_are_never_coordinators(self):
        client = self.app.test_client()
        token = csrf(client, "/signup")
        client.post("/signup", data={"csrf_token": token, "username": "guest", "display_name": "Guest",
                                     "password": PASSWORD, "confirm": PASSWORD, "role": "coordinator", "agree": "1"})
        self.assertEqual(self.store.query_one("SELECT role FROM users WHERE username = 'guest'")["role"], "volunteer")

    def test_team_members_can_log_in_with_their_email(self):
        rows = {r["username"]: r["email"] for r in self.store.query("SELECT username, email FROM users")}
        self.assertEqual(rows, {"muhannad": "muhannadrizq3@gmail.com", "toka": "toka82439@gmail.com",
                                "reima": "abomir.reima@gmail.com", "fatyma": "fatyma.isk@gmail.com"})
        user = self.store.query_one("SELECT username FROM users WHERE email = ?", ("abomir.reima@gmail.com",))
        self.assertEqual(user["username"], "reima")


class TestAlertTests(unittest.TestCase):
    def make(self, channels, sender):
        store = make_store()
        app = create_app(store, testing=True, notifier=Notifier(store, channels=channels, senders={"telegram": sender}))
        client = app.test_client()
        token = csrf(client, "/signup")
        client.post("/signup", data={"csrf_token": token, "username": "muhannad", "display_name": "Muhannad",
                                     "password": PASSWORD, "confirm": PASSWORD, "agree": "1"})
        return client

    def press(self, client):
        token = csrf(client, "/dashboard")
        client.post("/alerts/test", data={"csrf_token": token})
        return client.get("/dashboard").get_data(as_text=True)

    def test_says_what_is_missing_when_not_set_up(self):
        html = self.press(self.make({}, FakeSender()))
        self.assertIn("TELEGRAM_BOT_TOKEN", html)

    def test_success(self):
        sender = FakeSender()
        html = self.press(self.make({"telegram": {"token": "t", "chat_id": "c"}}, sender))
        self.assertIn("Test alert sent", html)
        self.assertIn("Demo alert", sender.calls[0][1])

    def test_shows_telegram_error(self):
        from notifier import ChannelError, telegram_hint
        sender = FakeSender(error=ChannelError(telegram_hint(400, "Bad Request: chat not found")))
        html = self.press(self.make({"telegram": {"token": "t", "chat_id": "c"}}, sender))
        self.assertIn("chat not found", html)
        self.assertIn("pressed Start", html)
