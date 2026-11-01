import hashlib
import hmac
import logging
import os
import re
import secrets
from collections import Counter, OrderedDict
from datetime import timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

import activity
import data_io
import dispatch
import emergency_requests as er
import inventory
import settings
import storage
from notifier import Notifier, send_mail_to, smtp_settings
from translations import translate

logging.basicConfig(level=logging.INFO)


class AuthError(ValueError):
    pass


def validate_password(password):
    if len(password or "") < settings.MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {settings.MIN_PASSWORD_LENGTH} characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("Password must contain at least one letter and one number.")
    if len(password) > 128:
        raise AuthError("Password is too long.")


def clean_email(email):
    email = (email or "").strip().lower()
    if not email:
        return None
    if not re.fullmatch(settings.EMAIL_PATTERN, email):
        raise AuthError("Enter a valid email address.")
    return email


def register_user(store, username, display_name, password, requested_role, shelter_id=None, email=None):
    username = (username or "").strip()
    if not re.fullmatch(settings.USERNAME_PATTERN, username):
        raise AuthError("Username must be 3-30 letters, numbers, '.', '_' or '-'.")
    display_name = " ".join((display_name or "").split())[: settings.MAX_NAME_LENGTH] or username
    email = clean_email(email)
    validate_password(password)
    if store.query_one("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,)):
        raise AuthError("That username is taken.")
    if email and store.query_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise AuthError("An account with that email already exists.")

    if store.count("users") == 0:
        role = settings.COORDINATOR
    elif requested_role in settings.SELF_SIGNUP_ROLES:
        role = requested_role
    else:
        role = settings.VOLUNTEER

    shelter = None
    if role == settings.SHELTER_STAFF and shelter_id not in (None, ""):
        try:
            shelter = int(shelter_id)
        except (TypeError, ValueError):
            raise AuthError("Unknown shelter.") from None
        if not er.get_shelter(store, shelter):
            raise AuthError("Unknown shelter.")

    return store.insert(
        """INSERT INTO users (username, email, display_name, password_hash, role, shelter_id,
                              failed_attempts, locked_until, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)""",
        (username, email, display_name, generate_password_hash(password), role, shelter,
         storage.to_iso(storage.utcnow())),
    )


def find_user(store, login_name):
    login_name = (login_name or "").strip()
    if "@" in login_name:
        return store.query_one("SELECT * FROM users WHERE email = ?", (login_name.lower(),))
    return store.query_one("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (login_name,))


def authenticate(store, login_name, password, now=None):
    now = now or storage.utcnow()
    user = find_user(store, login_name)
    if user is None:
        check_password_hash(generate_password_hash("dummy-password-1"), password or "")
        raise AuthError("Wrong username, email or password.")

    locked_until = storage.from_iso(user["locked_until"])
    if locked_until and locked_until > now:
        minutes = int((locked_until - now).total_seconds() // 60) + 1
        raise AuthError(f"Account locked. Try again in {minutes} minute(s).")

    if not check_password_hash(user["password_hash"], password or ""):
        failed = int(user["failed_attempts"] or 0) + 1
        if failed >= settings.MAX_FAILED_LOGINS:
            until = storage.to_iso(now + timedelta(minutes=settings.LOCKOUT_MINUTES))
            store.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?", (until, user["id"]))
            raise AuthError(f"Too many attempts. Account locked for {settings.LOCKOUT_MINUTES} minutes.")
        store.execute("UPDATE users SET failed_attempts = ?, locked_until = NULL WHERE id = ?", (failed, user["id"]))
        raise AuthError("Wrong username, email or password.")

    store.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user["id"],))
    return user


def set_role(store, acting_user, target_id, new_role):
    if new_role not in settings.ROLES:
        raise AuthError("Unknown role.")
    target = store.query_one("SELECT * FROM users WHERE id = ?", (target_id,))
    if target is None:
        raise AuthError("Unknown user.")
    if int(target["id"]) == int(acting_user["id"]) and new_role != settings.COORDINATOR:
        raise AuthError("You cannot remove your own coordinator role.")
    store.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, target_id))
    return target


RESET_LINK_MINUTES = 30


def make_reset_token(secret, user):
    signer = URLSafeTimedSerializer(secret, salt="trf-password-reset")
    return signer.dumps({"u": user["id"], "h": user["password_hash"][-16:]})


def read_reset_token(store, secret, token):
    signer = URLSafeTimedSerializer(secret, salt="trf-password-reset")
    try:
        data = signer.loads(token, max_age=RESET_LINK_MINUTES * 60)
    except BadSignature:
        return None
    user = store.query_one("SELECT * FROM users WHERE id = ?", (data.get("u"),))
    if user is None or user["password_hash"][-16:] != data.get("h"):
        return None
    return user


def set_password(store, user_id, password):
    validate_password(password)
    store.execute(
        "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (generate_password_hash(password), user_id),
    )


def reset_password(store, target_id):
    target = store.query_one("SELECT * FROM users WHERE id = ?", (target_id,))
    if target is None:
        raise AuthError("Unknown user.")
    temp = secrets.token_urlsafe(6) + str(secrets.randbelow(10))
    store.execute(
        "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (generate_password_hash(temp), target_id),
    )
    return target, temp


def build_overview(store, user=None):
    supplies = inventory.list_supplies(store)
    all_requests = er.list_requests(store)
    open_requests = [r for r in all_requests if r["status"] in settings.OPEN_STATUSES]
    live = [r for r in all_requests if r["status"] != settings.CANCELLED]

    demand = Counter()
    for r in open_requests:
        demand[r["supply_type_id"]] += r["remaining"]
    stock_vs_demand = [
        {"label": s["label"], "stock": int(s["quantity"]), "demand": demand.get(s["id"], 0)} for s in supplies
    ]
    chart_max = max([1] + [max(x["stock"], x["demand"]) for x in stock_vs_demand])
    for x in stock_vs_demand:
        x["stock_pct"] = round(100 * x["stock"] / chart_max)
        x["demand_pct"] = round(100 * x["demand"] / chart_max)
    shortages = [x for x in stock_vs_demand if x["demand"] > x["stock"]]

    by_priority = OrderedDict((name, 0) for name in ("critical", "high", "medium", "low"))
    by_shelter = Counter()
    for r in open_requests:
        by_priority[r["priority_label"]] += 1
        by_shelter[r["shelter_name"]] += 1
    fulfilled = sum(1 for r in live if r["status"] == settings.FULFILLED)

    shelters = er.list_shelters(store)
    waiting_by_shelter = Counter(r["shelter_id"] for r in open_requests)
    for s in shelters:
        s["waiting"] = waiting_by_shelter.get(s["id"], 0)

    return {
        "supplies": supplies,
        "requests": all_requests,
        "open_requests": open_requests,
        "shelters": shelters,
        "stock_total": sum(int(s["quantity"]) for s in supplies),
        "low_supplies": [s for s in supplies if s["level"] != "good"],
        "request_total": len(all_requests),
        "waiting": len(open_requests),
        "units_delivered": sum(int(r["delivered"]) for r in all_requests),
        "sos_waiting": sum(1 for r in open_requests if r["is_sos"]),
        "stock_vs_demand": stock_vs_demand,
        "shortages": shortages,
        "by_priority": by_priority,
        "by_priority_max": max([1] + list(by_priority.values())),
        "by_shelter": by_shelter.most_common(),
        "by_shelter_max": max([1] + list(by_shelter.values())),
        "fulfilled": fulfilled,
        "live_total": len(live),
        "fulfilment_pct": round(100 * fulfilled / len(live)) if live else 0,
    }


def stable_fallback_secret():
    seeds = [os.environ.get(name, "") for name in
             ("TELEGRAM_BOT_TOKEN", "VERCEL_PROJECT_ID", "VERCEL_GIT_REPO_ID", "VERCEL_PROJECT_PRODUCTION_URL")]
    seeds.extend(password_hash for _, _, _, password_hash in settings.TEAM_ACCOUNTS)
    return hashlib.sha256(("trf-session|" + "|".join(seeds)).encode()).hexdigest()


def create_app(store=None, testing=False, notifier=None, mailer=None, team_accounts=None, app=None):
    app = app or Flask(__name__)
    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret and testing:
        secret = "test-secret"
    elif not secret:
        secret = stable_fallback_secret()
    app.config.update(
        SECRET_KEY=secret,
        TESTING=testing,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.ON_VERCEL,
        PERMANENT_SESSION_LIFETIME=timedelta(days=settings.REMEMBER_ME_DAYS),
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    )
    if not os.environ.get("SECRET_KEY") and not testing:
        app.logger.warning("SECRET_KEY not set. Set it in production.")

    store = store or storage.Storage()
    storage.seed_demo_data(store)
    if team_accounts if team_accounts is not None else not testing:
        storage.seed_team_accounts(store)
    app.store = store
    app.notifier = notifier or Notifier(store)
    app.mailer = mailer
    if app.mailer is None and smtp_settings():
        app.mailer = lambda to, subject, body: send_mail_to(smtp_settings(), to, subject, body)

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("user_id")
        if uid is not None:
            g.user = store.query_one("SELECT * FROM users WHERE id = ?", (uid,))
            if g.user is None:
                session.clear()
        g.lang = session.get("lang", "en")
        if request.method == "POST":
            sent = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(sent, expected):
                session["csrf_token"] = secrets.token_urlsafe(32)
                flash(translate("Your session expired. Please try again.", g.lang), "info")
                back_to = request.path if request.path in ("/login", "/signup", "/forgot-password") else None
                if g.user and not back_to:
                    back_to = url_for("dashboard")
                return redirect(back_to or url_for("login"))

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com; "
            "style-src 'self' https://unpkg.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://server.arcgisonline.com https://unpkg.com; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if settings.ON_VERCEL:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if g.get("user"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.context_processor
    def inject():
        lang = g.get("lang", "en")
        user = g.get("user")
        return {
            "current_user": user,
            "user_initials": activity.initials(user["display_name"]) if user else "",
            "first_name": (user["display_name"].split() or [""])[0] if user else "",
            "csrf_token": csrf_token,
            "_": lambda text: translate(text, lang),
            "lang": lang,
            "text_dir": "rtl" if lang == "ar" else "ltr",
            "can": lambda action: bool(user) and settings.can(user["role"], action),
            "can_modify": lambda req: er.can_modify(user, req),
            "settings": settings,
            "fmt_time": er.format_time,
            "uae_time": activity.uae_time,
            "initials": activity.initials,
        }

    def t(text):
        return translate(text, g.get("lang", "en"))

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash(t("Please log in first."), "info")
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def permission_required(action):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if not settings.can(g.user["role"], action):
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def safe_next(target, default="dashboard"):
        if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
            return target
        return url_for(default)

    def back(section):
        return redirect(url_for("dashboard") + "#" + section)

    def log(action):
        activity.log(store, g.user, action)

    def start_session(user, remember):
        lang = session.get("lang", "en")
        session.clear()
        session["user_id"] = user["id"]
        session["lang"] = lang
        session.permanent = bool(remember)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    def http_error(err):
        return render_template("error.html", code=err.code, message=err.description), err.code

    @app.errorhandler(500)
    def server_error(err):
        return render_template("error.html", code=500, message="Something went wrong on our side."), 500

    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if g.user else "login"))

    @app.route("/healthz")
    def healthz():
        return jsonify(status="ok", database=store.backend_name)

    @app.route("/lang/<code>")
    def set_language(code):
        session["lang"] = "ar" if code == "ar" else "en"
        return redirect(safe_next(request.args.get("next"), "index"))

    @app.route("/terms")
    def terms():
        return render_template("terms.html")

    @app.route("/cookies")
    def cookies():
        return render_template("cookies.html")

    @app.route("/privacy")
    def privacy():
        return redirect(url_for("cookies"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user and request.method == "GET":
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            try:
                user = authenticate(store, request.form.get("login"), request.form.get("password"))
            except AuthError as exc:
                flash(str(exc), "error")
            else:
                start_session(user, request.form.get("remember"))
                return redirect(safe_next(request.args.get("next")))
        return render_template("auth.html", tab="login", first_user=store.count("users") == 0, form={})

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            form = request.form
            if form.get("password") != form.get("confirm"):
                flash(t("Passwords do not match."), "error")
            elif not form.get("agree"):
                flash(t("You must accept the Terms & Conditions."), "error")
            else:
                try:
                    uid = register_user(store, form.get("username"), form.get("display_name"),
                                        form.get("password"), form.get("role"), form.get("shelter_id"),
                                        form.get("email"))
                except AuthError as exc:
                    flash(str(exc), "error")
                else:
                    user = store.query_one("SELECT * FROM users WHERE id = ?", (uid,))
                    start_session(user, False)
                    g.user = user
                    log(f"created an account ({translate(user['role'], 'en')})")
                    flash(t("Welcome! Your account is ready."), "success")
                    return redirect(url_for("dashboard"))
        return render_template("auth.html", tab="signup", first_user=store.count("users") == 0,
                               form=request.form if request.method == "POST" else {})

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST" and app.mailer:
            email = (request.form.get("email") or "").strip().lower()
            user = store.query_one("SELECT * FROM users WHERE email = ?", (email,)) if email else None
            if user:
                link = url_for("reset_with_link", token=make_reset_token(app.config["SECRET_KEY"], user), _external=True)
                body = (f"Hello {user['display_name']},\n\n"
                        f"Use this link to choose a new password for {settings.APP_NAME}. "
                        f"It works once and expires in {RESET_LINK_MINUTES} minutes:\n\n{link}\n\n"
                        "If you did not ask for this, you can ignore this email.")
                try:
                    app.mailer(email, f"{settings.APP_NAME}: reset your password", body)
                except Exception as exc:
                    app.logger.warning("Password reset email failed: %s", exc)
            flash(t("If an account uses that email, a reset link is on its way. Check your inbox."), "success")
            return redirect(url_for("forgot_password"))
        return render_template("forgot.html", email_enabled=bool(app.mailer))

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_with_link(token):
        user = read_reset_token(store, app.config["SECRET_KEY"], token)
        if user is None:
            flash(t("That reset link is invalid or has expired. Ask for a new one."), "error")
            return redirect(url_for("forgot_password"))
        if request.method == "POST":
            if request.form.get("password") != request.form.get("confirm"):
                flash(t("Passwords do not match."), "error")
            else:
                try:
                    set_password(store, user["id"], request.form.get("password"))
                except AuthError as exc:
                    flash(str(exc), "error")
                else:
                    activity.log(store, user, "reset their password with an email link")
                    flash(t("Your password has been changed. You can log in now."), "success")
                    return redirect(url_for("login"))
        return render_template("reset.html", token=token)

    @app.route("/logout", methods=["POST"])
    def logout():
        lang = session.get("lang", "en")
        session.clear()
        session["lang"] = lang
        flash(t("You have been logged out."), "success")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @permission_required("view_dashboard")
    def dashboard():
        users = []
        if settings.can(g.user["role"], "manage_users"):
            users = store.query("""SELECT u.id, u.username, u.email, u.display_name, u.role, s.name AS shelter_name
                                   FROM users u LEFT JOIN shelters s ON s.id = u.shelter_id ORDER BY u.id""")
            for u in users:
                u["initials"] = activity.initials(u["display_name"])
        return render_template(
            "dashboard.html",
            o=build_overview(store, g.user),
            history=dispatch.dispatch_history(store, 8),
            activity_rows=activity.recent(store, 25),
            users=users,
            alerts=app.notifier.recent(5),
            channels=app.notifier.enabled_channels,
            priorities=settings.PRIORITY_NAMES,
            temp_password=session.pop("temp_password", None),
        )

    def send_alert(req):
        shelter = er.get_shelter(store, req["shelter_id"])
        supply = inventory.get_supply(store, req["supply_type_id"])
        return app.notifier.alert_for_request(req, shelter, supply, g.user)

    def describe(req):
        shelter = er.get_shelter(store, req["shelter_id"])
        supply = inventory.get_supply(store, req["supply_type_id"])
        return f"{req['quantity']} {supply['name']} for {shelter['name']}"

    @app.route("/requests/new", methods=["GET", "POST"])
    @permission_required("create_request")
    def new_request():
        if request.method == "GET":
            return redirect(url_for("dashboard") + "#new-request")
        try:
            rid = er.create_request(
                store, g.user["id"], request.form.get("shelter_id"), request.form.get("supply_type_id"),
                request.form.get("quantity"), request.form.get("priority"), request.form.get("note"),
            )
        except er.RequestError as exc:
            flash(str(exc), "error")
            return back("new-request")
        req = er.get_request(store, rid)
        log(f"requested {describe(req)} ({er.priority_name(req['priority'])})")
        if int(req["priority"]) == settings.CRITICAL:
            send_alert(req)
            flash(t("Critical request created. The response team has been alerted."), "success")
        else:
            flash(t("Request created."), "success")
        return back("requests")

    @app.route("/sos", methods=["GET", "POST"])
    def sos():
        if g.user is None:
            if request.method == "POST":
                abort(403)
            return render_template("sos.html", shelters=[], supplies=[])
        if not settings.can(g.user["role"], "send_sos"):
            return render_template("sos.html", shelters=[], supplies=[], view_only=True)
        if request.method == "POST":
            try:
                rid = er.create_request(
                    store, g.user["id"], request.form.get("shelter_id"), request.form.get("supply_type_id"),
                    request.form.get("quantity"), settings.CRITICAL, request.form.get("note"), is_sos=True,
                )
            except er.RequestError as exc:
                flash(str(exc), "error")
            else:
                req = er.get_request(store, rid)
                log(f"sent an SOS: {describe(req)}")
                sent = send_alert(req)
                flash(t("SOS sent. The response team has been alerted.") if sent
                      else t("SOS saved. The alert was recorded in the fallback log."), "success")
                return back("requests")
        return render_template("sos.html", shelters=er.list_shelters(store), supplies=inventory.list_supplies(store))

    @app.route("/requests/<int:request_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_request(request_id):
        req = er.get_request(store, request_id)
        if req is None:
            abort(404)
        if not er.can_modify(g.user, req):
            abort(403)
        if request.method == "POST":
            try:
                er.edit_request(store, g.user, request_id, request.form.get("quantity"),
                                request.form.get("priority"), request.form.get("note"))
            except er.RequestError as exc:
                flash(str(exc), "error")
            else:
                log(f"edited request #{request_id}")
                flash(t("Request updated."), "success")
                return back("requests")
        return render_template("request_form.html", existing=req, shelter=er.get_shelter(store, req["shelter_id"]),
                               supply=inventory.get_supply(store, req["supply_type_id"]),
                               priorities=settings.PRIORITY_NAMES)

    @app.route("/requests/<int:request_id>/cancel", methods=["POST"])
    @login_required
    def cancel_request(request_id):
        req = er.get_request(store, request_id)
        if req is None:
            abort(404)
        try:
            er.cancel_request(store, g.user, request_id)
        except er.RequestError:
            abort(403)
        log(f"cancelled request #{request_id} ({describe(req)})")
        flash(t("Request cancelled."), "info")
        return back("requests")

    @app.route("/dispatch/auto", methods=["POST"])
    @permission_required("dispatch")
    def auto_dispatch():
        plan = dispatch.run_auto_dispatch(store, g.user["id"])
        if plan:
            log(f"auto-dispatched {sum(plan.values())} units to {len(plan)} requests")
            flash(t("Dispatched {units} units to {count} requests.").format(units=sum(plan.values()), count=len(plan)),
                  "success")
        else:
            flash(t("Nothing to dispatch: no waiting requests or no stock."), "info")
        return back("requests")

    @app.route("/dispatch/<int:request_id>", methods=["POST"])
    @permission_required("dispatch")
    def dispatch_one(request_id):
        try:
            sent = dispatch.dispatch_request(store, g.user["id"], request_id, request.form.get("amount"))
        except er.RequestError as exc:
            flash(str(exc), "error")
        else:
            req = er.get_request(store, request_id)
            supply = inventory.get_supply(store, req["supply_type_id"])
            shelter = er.get_shelter(store, req["shelter_id"])
            log(f"dispatched {sent} {supply['name']} to {shelter['name']}")
            flash(t("Dispatched {units} units.").format(units=sent), "success")
        return back("requests")

    @app.route("/stock/add", methods=["POST"])
    @permission_required("manage_stock")
    def add_stock():
        try:
            sid = int(request.form.get("supply_type_id", "0"))
            total = inventory.add_stock(store, sid, request.form.get("quantity"))
        except (inventory.InventoryError, ValueError) as exc:
            flash(str(exc) if isinstance(exc, inventory.InventoryError) else t("Choose a supply."), "error")
        else:
            supply = inventory.get_supply(store, sid)
            log(f"added {request.form.get('quantity')} {supply['name']} to stock (now {total})")
            flash(t("Stock updated."), "success")
        return back("inventory")

    @app.route("/stock/<int:supply_id>/level", methods=["POST"])
    @permission_required("manage_stock")
    def set_level(supply_id):
        try:
            supply = inventory.get_supply(store, supply_id)
            if not supply:
                abort(404)
            inventory.set_stock(store, supply_id, request.form.get("quantity"), request.form.get("threshold"))
        except inventory.InventoryError as exc:
            flash(str(exc), "error")
        else:
            log(f"set {supply['name']} to {request.form.get('quantity')} (low-stock level {request.form.get('threshold')})")
            flash(t("Stock updated."), "success")
        return back("inventory")

    @app.route("/supply-types", methods=["POST"])
    @permission_required("manage_supply_types")
    def supply_types():
        try:
            inventory.add_supply_type(store, request.form.get("name"), request.form.get("unit") or "units",
                                      request.form.get("quantity") or 0)
        except inventory.InventoryError as exc:
            flash(str(exc), "error")
        else:
            log(f"added a new supply type: {request.form.get('name', '').strip()}")
            flash(t("Supply type added."), "success")
        return back("inventory")

    @app.route("/supply-types/<int:supply_id>/delete", methods=["POST"])
    @permission_required("manage_supply_types")
    def delete_supply(supply_id):
        supply = inventory.get_supply(store, supply_id)
        if not supply:
            abort(404)
        try:
            inventory.delete_supply_type(store, supply_id)
        except inventory.InventoryError as exc:
            flash(str(exc), "error")
        else:
            log(f"removed the supply type {supply['name']}")
            flash(t("Supply type removed."), "info")
        return back("inventory")

    @app.route("/shelters", methods=["POST"])
    @permission_required("manage_shelters")
    def add_shelter():
        try:
            er.add_shelter(store, request.form.get("name"), request.form.get("area"),
                           request.form.get("latitude"), request.form.get("longitude"), 0)
        except er.RequestError as exc:
            flash(str(exc), "error")
        else:
            log(f"added the shelter {request.form.get('name', '').strip()}")
            flash(t("Shelter added."), "success")
        return back("shelters")

    @app.route("/shelters/<int:shelter_id>/delete", methods=["POST"])
    @permission_required("manage_shelters")
    def delete_shelter(shelter_id):
        shelter = er.get_shelter(store, shelter_id)
        if not shelter:
            abort(404)
        try:
            er.delete_shelter(store, shelter_id)
        except er.RequestError as exc:
            flash(str(exc), "error")
        else:
            log(f"removed the shelter {shelter['name']}")
            flash(t("Shelter removed."), "info")
        return back("shelters")

    @app.route("/api/map-data")
    @permission_required("view_map")
    def map_data():
        o = build_overview(store)
        data = []
        for s in o["shelters"]:
            mine = [r for r in o["open_requests"] if r["shelter_id"] == s["id"]]
            data.append({
                "id": s["id"], "name": s["name"], "area": s["area"],
                "lat": s["latitude"], "lng": s["longitude"],
                "waiting": len(mine), "sos": any(r["is_sos"] for r in mine),
                "needs": [f'{r["remaining"]} {r["supply_name"]} ({r["priority_label"]})' for r in mine],
            })
        return jsonify(shelters=data)

    @app.route("/export/<kind>.csv")
    @permission_required("view_reports")
    def export(kind):
        if kind not in data_io.EXPORT_KINDS:
            abort(404)
        if kind == "activity" and not settings.can(g.user["role"], "view_activity"):
            abort(403)
        return Response(data_io.export_csv(store, kind), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={data_io.export_filename(kind)}"})

    @app.route("/import", methods=["POST"])
    @permission_required("import_csv")
    def import_csv():
        kind = request.form.get("kind")
        upload = request.files.get("file")
        if kind not in data_io.IMPORT_KINDS:
            flash(t("Choose what to import."), "error")
            return back("data")
        if not upload or not upload.filename:
            flash(t("Choose a CSV file to import."), "error")
            return back("data")
        if not upload.filename.lower().endswith(".csv"):
            flash(t("The file must be a .csv file."), "error")
            return back("data")
        try:
            text = upload.read().decode("utf-8-sig")
            summary = data_io.import_csv(store, g.user, kind, text)
        except UnicodeDecodeError:
            flash(t("The file must be UTF-8 text."), "error")
        except inventory.InventoryError as exc:
            flash(t("Nothing was imported.") + " " + str(exc), "error")
        else:
            log(f"imported {summary} from a CSV file")
            flash(t("Imported") + f" {summary}.", "success")
        return back("data")

    @app.route("/alerts/test", methods=["POST"])
    @permission_required("manage_users")
    def test_alert():
        notifier = app.notifier
        if "telegram" not in notifier.channels:
            missing = [name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not getattr(settings, name)]
            flash(t("Telegram is not switched on.") + " " + t("Missing in Vercel:") + " " + ", ".join(missing or ["?"])
                  + ". " + t("Add them in Settings → Environment Variables, then Redeploy."), "error")
            return back("new-request")
        text = (f"✅ Test alert from {settings.APP_NAME}\nSent by {g.user['display_name']}.\n"
                "Demo alert from a school competition project. A real system would use official emergency channels.")
        delivered = notifier.send(text)
        if "telegram" in delivered:
            log("sent a test Telegram alert")
            flash(t("Test alert sent. Check the Telegram chat."), "success")
        else:
            flash(t("Telegram did not send the message:") + " " + notifier.last_errors.get("telegram", "unknown error"), "error")
        return back("new-request")

    @app.route("/reset-demo", methods=["POST"])
    @permission_required("reset_demo")
    def reset_demo():
        storage.reset_demo(store)
        log("reset everything to the demo data")
        flash(t("Demo data restored."), "info")
        return redirect(url_for("dashboard"))

    @app.route("/start-empty", methods=["POST"])
    @permission_required("reset_demo")
    def start_empty():
        storage.start_empty(store)
        log("cleared all the data")
        flash(t("All data cleared. Accounts were kept."), "info")
        return redirect(url_for("dashboard"))

    @app.route("/users/<int:user_id>/role", methods=["POST"])
    @permission_required("manage_users")
    def change_role(user_id):
        try:
            target = set_role(store, g.user, user_id, request.form.get("role"))
        except AuthError as exc:
            flash(str(exc), "error")
        else:
            log(f"changed {target['display_name']}'s role to {translate(request.form.get('role'), 'en')}")
            flash(t("Role updated."), "success")
        return back("team")

    @app.route("/users/<int:user_id>/reset-password", methods=["POST"])
    @permission_required("manage_users")
    def admin_reset_password(user_id):
        try:
            target, temp = reset_password(store, user_id)
        except AuthError as exc:
            flash(str(exc), "error")
        else:
            log(f"reset the password for {target['display_name']}")
            session["temp_password"] = {"name": target["display_name"], "password": temp}
        return back("team")

    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
