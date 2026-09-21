import os
import sqlite3
import threading
import time
import hmac
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import requests
from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash


DATA_DIR = os.getenv("DATA_DIR", "/data")
DATABASE = os.path.join(DATA_DIR, "parcelbeacon.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
POLL_INTERVAL_MINUTES = max(15, int(os.getenv("POLL_INTERVAL_MINUTES", "60")))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=8 * 1024 * 1024)

STATUS_LABELS = {"pending": "ממתין", "notfound": "לא נמצא", "info_received": "פרטי המשלוח התקבלו", "transit": "בדרך", "in_transit": "בדרך", "pickup": "ממתין לאיסוף", "available_for_pickup": "ממתין לאיסוף", "out_for_delivery": "יצא למסירה", "delivered": "נמסר", "exception": "חריגה", "failed_attempt": "ניסיון מסירה נכשל", "expired": "פג תוקף", "unknown": "לא ידוע"}
COMMON_SOURCES = ["AliExpress", "Amazon", "eBay", "Temu", "SHEIN", "iHerb", "Banggood", "Geekbuying", "דואר ישראל", "חנות מקומית"]
EVENT_TRANSLATIONS = {
    "departed from facility": "יצא ממתקן המיון",
    "arrived at facility": "הגיע למתקן המיון",
    "in transit": "המשלוח בדרך",
    "out for delivery": "יצא למסירה",
    "delivered": "המשלוח נמסר",
    "available for pickup": "המשלוח ממתין לאיסוף",
    "ready for pickup": "המשלוח מוכן לאיסוף",
    "shipment received": "המשלוח התקבל",
    "information received": "פרטי המשלוח התקבלו",
    "customs clearance": "המשלוח בטיפול המכס",
}
LOCATION_TRANSLATIONS = {"lod": "לוד", "israel": "ישראל"}
COURIER_NAMES = {
    "ups": "UPS", "usps": "USPS", "dhl": "DHL", "fedex": "FedEx",
    "israel-post": "דואר ישראל", "israelpost": "דואר ישראל",
    "cainiao": "Cainiao", "amazon": "Amazon Logistics", "aramex": "Aramex",
    "gls": "GLS", "dpd": "DPD", "yanwen": "Yanwen", "4px": "4PX",
}


@app.template_filter("status_he")
def status_he(value):
    normalized = (value or "unknown").lower()
    return STATUS_LABELS.get(normalized, normalized.replace("_", " "))


@app.template_filter("event_he")
def event_he(value):
    if not value:
        return ""
    return EVENT_TRANSLATIONS.get(value.strip().lower(), value)


@app.template_filter("location_he")
def location_he(value):
    if not value:
        return ""
    return ", ".join(LOCATION_TRANSLATIONS.get(part.strip().lower(), part.strip()) for part in value.split(","))


def parse_provider_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


@app.template_filter("datetime_he")
def datetime_he(value):
    parsed = parse_provider_datetime(value)
    if not parsed:
        return value or "טרם נבדק"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%d/%m/%Y %H:%M")


@app.template_filter("date_he")
def date_he(value):
    parsed = parse_provider_datetime(value)
    return parsed.strftime("%d/%m/%Y") if parsed else (value or "")


@app.template_filter("courier_name")
def courier_name(value):
    if not value:
        return "טרם זוהתה"
    return COURIER_NAMES.get(value.strip().lower(), value)


def save_product_image(upload, shipment_id):
    if not upload or not upload.filename:
        return None
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"shipment-{shipment_id}.webp"
    destination = os.path.join(UPLOAD_DIR, filename)
    try:
        with Image.open(upload.stream) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            image.save(destination, "WEBP", quality=85, method=6)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("יש לבחור קובץ תמונה תקין מסוג JPG, PNG או WebP.") from exc
    return filename


def delete_product_image(filename):
    if not filename:
        return
    path = Path(UPLOAD_DIR, filename)
    if path.parent == Path(UPLOAD_DIR) and path.is_file():
        path.unlink()


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db():
    if "db" not in g:
        os.makedirs(DATA_DIR, exist_ok=True)
        g.db = sqlite3.connect(DATABASE, timeout=30)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DATABASE) as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                tracking_number TEXT NOT NULL UNIQUE,
                carrier_code TEXT,
                source TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                substatus TEXT,
                latest_event TEXT,
                latest_location TEXT,
                estimated_delivery TEXT,
                archived INTEGER NOT NULL DEFAULT 0,
                provider_registered INTEGER NOT NULL DEFAULT 0,
                last_checked TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER NOT NULL,
                event_key TEXT NOT NULL,
                event_time TEXT,
                description TEXT,
                location TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(shipment_id, event_key),
                FOREIGN KEY(shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS auth_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(shipments)")}
        if "provider_name" not in columns:
            db.execute("ALTER TABLE shipments ADD COLUMN provider_name TEXT")
        if "provider_tracker_id" not in columns:
            db.execute("ALTER TABLE shipments ADD COLUMN provider_tracker_id TEXT")
        if "image_filename" not in columns:
            db.execute("ALTER TABLE shipments ADD COLUMN image_filename TEXT")


def get_auth_settings():
    row = get_db().execute(
        "SELECT username, password_hash FROM auth_settings WHERE id = 1"
    ).fetchone()
    if row:
        return {
            "username": row["username"],
            "password_hash": row["password_hash"],
            "password": None,
        }
    return {
        "username": os.getenv("APP_USERNAME", "admin"),
        "password_hash": None,
        "password": os.getenv("APP_PASSWORD", ""),
    }


def verify_credentials(username, password):
    credentials = get_auth_settings()
    username_matches = hmac.compare_digest(username, credentials["username"])
    if credentials["password_hash"]:
        password_matches = check_password_hash(credentials["password_hash"], password)
    else:
        password_matches = hmac.compare_digest(password, credentials["password"])
    return username_matches and password_matches


def authentication_enabled():
    credentials = get_auth_settings()
    return bool(credentials["password_hash"] or credentials["password"])


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if authentication_enabled() and not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


class Ship24Client:
    base_url = "https://api.ship24.com/public/v1"

    def __init__(self):
        self.api_key = os.getenv("SHIP24_API_KEY", "").strip()

    @property
    def enabled(self):
        return bool(self.api_key)

    def _request(self, method, path, **kwargs):
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=30,
            **kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", {})

    def register(self, tracking_number, carrier_code=""):
        body = {"trackingNumber": tracking_number}
        if carrier_code:
            body["courierCode"] = [carrier_code]
        destination_country = os.getenv("DESTINATION_COUNTRY_CODE", "IL").strip().upper()
        if destination_country:
            body["destinationCountryCode"] = destination_country
        data = self._request("POST", "/trackers", json=body)
        return data.get("tracker", {})

    def get_tracking(self, tracking_number, tracker_id=""):
        paths = [f"/trackers/{tracker_id}/results"] if tracker_id else []
        paths.append(f"/trackers/search/{tracking_number}/results")
        for path in paths:
            try:
                data = self._request("GET", path)
            except requests.HTTPError:
                if path == paths[-1]:
                    raise
                continue
            trackings = data.get("trackings", [])
            if trackings:
                return trackings[0]
        return None

    def update_courier(self, tracker_id, carrier_code):
        return self._request(
            "PATCH",
            f"/trackers/{tracker_id}",
            json={"courierCode": [carrier_code]},
        )


provider = Ship24Client()


def send_gotify(title, message, priority=5):
    base_url = os.getenv("GOTIFY_URL", "").rstrip("/")
    token = os.getenv("GOTIFY_TOKEN", "")
    if not base_url or not token:
        return
    requests.post(
        f"{base_url}/message",
        params={"token": token},
        json={"title": title, "message": message, "priority": priority},
        timeout=15,
    ).raise_for_status()


def normalize_tracking(data):
    shipment = data.get("shipment", {})
    checkpoints = data.get("events") or []
    checkpoints = sorted(
        checkpoints,
        key=lambda event: (event.get("order", -1), event.get("occurrenceDatetime", "")),
        reverse=True,
    )
    latest = checkpoints[0] if checkpoints else {}
    delivery = shipment.get("delivery") or {}
    courier_codes = [event.get("courierCode") for event in checkpoints if event.get("courierCode")]
    return {
        "status": shipment.get("statusMilestone") or latest.get("statusMilestone") or "pending",
        "substatus": shipment.get("statusCode") or latest.get("statusCode") or "",
        "latest_event": latest.get("status") or "",
        "latest_location": latest.get("location") or "",
        "estimated_delivery": delivery.get("estimatedDeliveryDate") or "",
        "carrier_code": courier_codes[0] if courier_codes else "",
        "events": checkpoints,
    }


def refresh_shipment(shipment_id, notify=True):
    if not provider.enabled:
        raise RuntimeError("SHIP24_API_KEY is not configured")
    with app.app_context():
        db = get_db()
        shipment = db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        if not shipment:
            return
        carrier = shipment["carrier_code"] or ""
        tracker_id = shipment["provider_tracker_id"] or ""
        if shipment["provider_name"] != "ship24" or not tracker_id:
            tracker = provider.register(shipment["tracking_number"], carrier)
            tracker_id = tracker.get("trackerId", "")
            db.execute(
                """UPDATE shipments SET provider_name='ship24', provider_tracker_id=?,
                   provider_registered=1, updated_at=? WHERE id=?""",
                (tracker_id, utc_now(), shipment_id),
            )
            db.commit()
        raw = provider.get_tracking(shipment["tracking_number"], tracker_id)
        if not raw:
            db.execute(
                "UPDATE shipments SET provider_name='ship24', provider_registered=1, last_checked=?, updated_at=? WHERE id=?",
                (utc_now(), utc_now(), shipment_id),
            )
            db.commit()
            return
        result = normalize_tracking(raw)
        carrier = result["carrier_code"] or carrier
        old_status = shipment["status"]
        old_event = shipment["latest_event"] or ""
        now = utc_now()
        db.execute(
            """UPDATE shipments SET carrier_code=?, status=?, substatus=?, latest_event=?,
               latest_location=?, estimated_delivery=?, provider_registered=1,
               last_checked=?, updated_at=? WHERE id=?""",
            (carrier, result["status"], result["substatus"], result["latest_event"],
             result["latest_location"], result["estimated_delivery"], now, now, shipment_id),
        )
        for event in result["events"]:
            event_time = event.get("occurrenceDatetime") or ""
            description = event.get("status") or ""
            location = event.get("location") or ""
            key = f"{event_time}|{description}|{location}"
            db.execute(
                "INSERT OR IGNORE INTO events (shipment_id,event_key,event_time,description,location,created_at) VALUES (?,?,?,?,?,?)",
                (shipment_id, key, event_time, description, location, now),
            )
        db.commit()
        changed = old_status != result["status"] or (result["latest_event"] and old_event != result["latest_event"])
        if notify and changed:
            send_gotify(
                f"ParcelBeacon: {shipment['name']}",
                f"מצב: {STATUS_LABELS.get(result['status'], result['status'])}\n{result['latest_event']}\n{result['latest_location']}".strip(),
                7 if result["status"] in ("exception", "failed_attempt") else 5,
            )


def refresh_all(notify=True):
    with app.app_context():
        ids = [row["id"] for row in get_db().execute("SELECT id FROM shipments WHERE archived = 0").fetchall()]
    for shipment_id in ids:
        try:
            refresh_shipment(shipment_id, notify=notify)
        except Exception as exc:
            app.logger.warning("Unable to refresh shipment %s: %s", shipment_id, exc)


def polling_worker():
    time.sleep(30)
    while True:
        if provider.enabled:
            refresh_all(notify=True)
        time.sleep(POLL_INTERVAL_MINUTES * 60)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        supplied_user = request.form.get("username", "")
        supplied_password = request.form.get("password", "")
        if verify_credentials(supplied_user, supplied_password):
            session["authenticated"] = True
            session["username"] = supplied_user
            return redirect(url_for("index"))
        flash("שם המשתמש או הסיסמה שגויים.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/settings/account", methods=["GET", "POST"])
@login_required
def account_settings():
    credentials = get_auth_settings()
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_username = request.form.get("username", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not verify_credentials(credentials["username"], current_password):
            flash("הסיסמה הנוכחית שגויה.", "error")
        elif not new_username or len(new_username) > 64:
            flash("שם המשתמש חייב להכיל בין תו אחד ל־64 תווים.", "error")
        elif new_password and len(new_password) < 10:
            flash("הסיסמה החדשה חייבת להכיל לפחות 10 תווים.", "error")
        elif new_password != confirm_password:
            flash("אימות הסיסמה החדשה אינו תואם.", "error")
        else:
            if new_password:
                password_hash = generate_password_hash(new_password)
            elif credentials["password_hash"]:
                password_hash = credentials["password_hash"]
            else:
                password_hash = generate_password_hash(current_password)
            get_db().execute(
                """INSERT INTO auth_settings (id, username, password_hash, updated_at)
                   VALUES (1, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     username=excluded.username,
                     password_hash=excluded.password_hash,
                     updated_at=excluded.updated_at""",
                (new_username, password_hash, utc_now()),
            )
            get_db().commit()
            session["authenticated"] = True
            session["username"] = new_username
            flash("פרטי הכניסה עודכנו בהצלחה.", "success")
            return redirect(url_for("account_settings"))

    return render_template("account_settings.html", username=credentials["username"])


@app.get("/")
@login_required
def index():
    archived = request.args.get("archived", "0") == "1"
    sort = request.args.get("sort", "updated")
    order_by = {
        "updated": "updated_at DESC",
        "eta_asc": "CASE WHEN estimated_delivery IS NULL OR estimated_delivery = '' THEN 1 ELSE 0 END, estimated_delivery ASC, updated_at DESC",
        "eta_desc": "CASE WHEN estimated_delivery IS NULL OR estimated_delivery = '' THEN 1 ELSE 0 END, estimated_delivery DESC, updated_at DESC",
    }.get(sort, "updated_at DESC")
    if sort not in {"updated", "eta_asc", "eta_desc"}:
        sort = "updated"
    shipments = get_db().execute(
        f"SELECT * FROM shipments WHERE archived = ? ORDER BY {order_by}", (int(archived),)
    ).fetchall()
    saved_sources = [
        row["source"]
        for row in get_db().execute(
            "SELECT DISTINCT source FROM shipments WHERE source IS NOT NULL AND TRIM(source) <> '' ORDER BY source"
        ).fetchall()
    ]
    sources = list(dict.fromkeys(COMMON_SOURCES + saved_sources))
    return render_template(
        "index.html",
        shipments=shipments,
        archived=archived,
        provider_enabled=provider.enabled,
        sources=sources,
        sort=sort,
    )


@app.post("/shipments")
@login_required
def add_shipment():
    name = request.form.get("name", "").strip()
    tracking_number = request.form.get("tracking_number", "").strip()
    source = request.form.get("source", "").strip()
    if not tracking_number:
        flash("יש להזין מספר מעקב.", "error")
        return redirect(url_for("index"))
    if not name:
        name = f"משלוח מ־{source}" if source else f"משלוח {tracking_number[-6:]}"
    now = utc_now()
    try:
        cursor = get_db().execute(
            "INSERT INTO shipments (name,tracking_number,carrier_code,source,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (name, tracking_number, request.form.get("carrier_code", "").strip(), source, now, now),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        flash("מספר המעקב כבר קיים במערכת.", "error")
        return redirect(url_for("index"))
    try:
        image_filename = save_product_image(request.files.get("product_image"), cursor.lastrowid)
        if image_filename:
            get_db().execute(
                "UPDATE shipments SET image_filename=? WHERE id=?",
                (image_filename, cursor.lastrowid),
            )
            get_db().commit()
    except ValueError as exc:
        flash(f"המשלוח נשמר ללא תמונה: {exc}", "error")
    flash("המשלוח נוסף בהצלחה.", "success")
    if provider.enabled:
        try:
            refresh_shipment(cursor.lastrowid, notify=False)
        except Exception as exc:
            flash(f"המשלוח נשמר, אך העדכון הראשוני נכשל: {exc}", "error")
    return redirect(url_for("index"))


@app.get("/shipments/<int:shipment_id>")
@login_required
def shipment_detail(shipment_id):
    shipment = get_db().execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if not shipment:
        return ("Not found", 404)
    events = get_db().execute(
        "SELECT * FROM events WHERE shipment_id = ? ORDER BY event_time DESC, id DESC", (shipment_id,)
    ).fetchall()
    return render_template("detail.html", shipment=shipment, events=events)


@app.route("/shipments/<int:shipment_id>/edit", methods=["GET", "POST"])
@login_required
def edit_shipment(shipment_id):
    db = get_db()
    shipment = db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if not shipment:
        return ("Not found", 404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        tracking_number = request.form.get("tracking_number", "").strip()
        carrier_code = request.form.get("carrier_code", "").strip()
        source = request.form.get("source", "").strip()
        if not tracking_number:
            flash("יש להזין מספר מעקב.", "error")
        else:
            if not name:
                name = f"משלוח מ־{source}" if source else f"משלוח {tracking_number[-6:]}"
            tracking_changed = tracking_number != shipment["tracking_number"]
            duplicate = db.execute(
                "SELECT id FROM shipments WHERE tracking_number=? AND id<>?",
                (tracking_number, shipment_id),
            ).fetchone()
            if duplicate:
                flash("מספר המעקב כבר קיים במערכת.", "error")
            else:
                carrier_changed = bool(carrier_code and carrier_code != (shipment["carrier_code"] or ""))
                image_filename = shipment["image_filename"]
                try:
                    uploaded_filename = save_product_image(request.files.get("product_image"), shipment_id)
                except ValueError as exc:
                    flash(str(exc), "error")
                else:
                    if uploaded_filename:
                        image_filename = uploaded_filename
                    elif request.form.get("remove_image") == "1":
                        delete_product_image(image_filename)
                        image_filename = None
                    if tracking_changed:
                        db.execute("DELETE FROM events WHERE shipment_id = ?", (shipment_id,))
                        db.execute(
                            """UPDATE shipments SET name=?, tracking_number=?, carrier_code=?, source=?,
                               status='pending', substatus=NULL, latest_event=NULL, latest_location=NULL,
                               estimated_delivery=NULL, provider_registered=0, provider_name=NULL,
                               provider_tracker_id=NULL, last_checked=NULL, image_filename=?, updated_at=? WHERE id=?""",
                            (name, tracking_number, carrier_code, source, image_filename, utc_now(), shipment_id),
                        )
                    else:
                        db.execute(
                            "UPDATE shipments SET name=?, carrier_code=?, source=?, image_filename=?, updated_at=? WHERE id=?",
                            (name, carrier_code, source, image_filename, utc_now(), shipment_id),
                        )
                    db.commit()
                    flash("פרטי המשלוח עודכנו בהצלחה.", "success")
                    if carrier_changed and shipment["provider_tracker_id"] and provider.enabled:
                        try:
                            provider.update_courier(shipment["provider_tracker_id"], carrier_code)
                        except Exception as exc:
                            flash(f"הפרטים נשמרו, אך עדכון חברת השילוח ב־Ship24 נכשל: {exc}", "error")
                    if tracking_changed and provider.enabled:
                        try:
                            refresh_shipment(shipment_id, notify=False)
                        except Exception as exc:
                            flash(f"הפרטים נשמרו, אך העדכון הראשוני נכשל: {exc}", "error")
                    return redirect(url_for("shipment_detail", shipment_id=shipment_id))

    saved_sources = [
        row["source"]
        for row in db.execute(
            "SELECT DISTINCT source FROM shipments WHERE source IS NOT NULL AND TRIM(source) <> '' ORDER BY source"
        ).fetchall()
    ]
    return render_template(
        "edit_shipment.html",
        shipment=shipment,
        sources=list(dict.fromkeys(COMMON_SOURCES + saved_sources)),
    )


@app.get("/shipment-images/<path:filename>")
@login_required
def shipment_image(filename):
    return send_from_directory(UPLOAD_DIR, filename, max_age=3600)


@app.post("/shipments/<int:shipment_id>/refresh")
@login_required
def refresh_one(shipment_id):
    try:
        refresh_shipment(shipment_id)
        flash("המשלוח עודכן.", "success")
    except Exception as exc:
        flash(f"העדכון נכשל: {exc}", "error")
    return redirect(request.referrer or url_for("index"))


@app.post("/refresh-all")
@login_required
def refresh_all_route():
    refresh_all(notify=True)
    flash("עדכון כל המשלוחים הסתיים.", "success")
    return redirect(url_for("index"))


@app.post("/shipments/<int:shipment_id>/archive")
@login_required
def archive_shipment(shipment_id):
    value = 1 if request.form.get("archived", "1") == "1" else 0
    get_db().execute("UPDATE shipments SET archived=?, updated_at=? WHERE id=?", (value, utc_now(), shipment_id))
    get_db().commit()
    return redirect(request.referrer or url_for("index"))


@app.post("/shipments/<int:shipment_id>/delete")
@login_required
def delete_shipment(shipment_id):
    shipment = get_db().execute("SELECT image_filename FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if shipment:
        delete_product_image(shipment["image_filename"])
    get_db().execute("DELETE FROM events WHERE shipment_id = ?", (shipment_id,))
    get_db().execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))
    get_db().commit()
    flash("המשלוח נמחק.", "success")
    return redirect(url_for("index"))


@app.get("/health")
def health():
    return jsonify(status="ok", provider_configured=provider.enabled)


init_db()
if os.getenv("DISABLE_POLLER", "0") != "1":
    threading.Thread(target=polling_worker, daemon=True, name="shipment-poller").start()
