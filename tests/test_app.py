import importlib
import sqlite3
from io import BytesIO

from PIL import Image


def load_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("DISABLE_POLLER", "1")
    import app as app_module
    return importlib.reload(app_module).app


def login(client):
    return client.post(
        "/login",
        data={"username": "admin", "password": "test-password"},
        follow_redirects=True,
    )


def test_health_and_authentication(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json == {"provider_configured": False, "status": "ok"}
        assert client.get("/").status_code == 302
        assert login(client).status_code == 200


def test_shipment_lifecycle(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        response = client.post(
            "/shipments",
            data={"name": "Test Parcel", "tracking_number": "TEST123", "source": "Test Store"},
            follow_redirects=True,
        )
        assert b"Test Parcel" in response.data
        assert b"TEST123" in client.get("/shipments/1").data
        client.post("/shipments/1/archive", data={"archived": "1"})
        assert b"Test Parcel" in client.get("/?archived=1").data
        client.post("/shipments/1/delete")
        assert b"Test Parcel" not in client.get("/?archived=1").data


def test_product_url_create_edit_remove_and_validation(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        client.post("/shipments", data={"tracking_number": "URL123", "product_url": "https://shop.example/item?id=1"})
        assert b'https://shop.example/item?id=1' in client.get("/").data
        assert b'https://shop.example/item?id=1' in client.get("/shipments/1").data
        client.post("/shipments/1/edit", data={"tracking_number": "URL123", "product_url": "javascript:alert(1)"})
        assert b'https://shop.example/item?id=1' in client.get("/shipments/1").data
        client.post("/shipments/1/edit", data={"tracking_number": "URL123", "product_url": "https://new.example/product"})
        assert b'https://new.example/product' in client.get("/shipments/1").data
        client.post("/shipments/1/edit", data={"tracking_number": "URL123", "product_url": ""})
        assert b'https://new.example/product' not in client.get("/shipments/1").data


def test_product_url_migration_keeps_existing_shipments(tmp_path, monkeypatch):
    db_path = tmp_path / "parcelbeacon.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE shipments (id INTEGER PRIMARY KEY, name TEXT, tracking_number TEXT, source TEXT, carrier_code TEXT, status TEXT, substatus TEXT, latest_event TEXT, latest_location TEXT, estimated_delivery TEXT, archived INTEGER, provider_registered INTEGER, last_checked TEXT, created_at TEXT, updated_at TEXT)")
        db.execute("INSERT INTO shipments (id, name, tracking_number, status, archived, created_at, updated_at) VALUES (1, 'Existing', 'OLD1', 'pending', 0, '2026-01-01', '2026-01-01')")
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        assert b"Existing" in client.get("/").data
        client.post("/shipments/1/edit", data={"tracking_number": "OLD1", "name": "Existing", "product_url": "https://shop.example/old"})
        assert b'https://shop.example/old' in client.get("/shipments/1").data


def test_source_field_has_common_and_saved_autocomplete_options(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        client.post(
            "/shipments",
            data={"name": "Custom Store Parcel", "tracking_number": "CUSTOM12345", "source": "My Store"},
        )
        response = client.get("/")
        assert b'datalist id="source-options"' in response.data
        assert b'value="AliExpress"' in response.data
        assert b'value="My Store"' in response.data


def test_existing_shipment_can_be_edited(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        client.post(
            "/shipments",
            data={"name": "Old Name", "tracking_number": "OLD123", "source": "Old Store"},
        )
        edit_page = client.get("/shipments/1/edit").data
        assert b'value="Old Name"' in edit_page
        assert b'class="source-picker"' in edit_page
        assert b'value="Old Store" selected' in edit_page
        response = client.post(
            "/shipments/1/edit",
            data={"name": "New Name", "tracking_number": "NEW456", "carrier_code": "israel-post", "source": "New Store"},
            follow_redirects=True,
        )
        assert "עודכנו בהצלחה".encode() in response.data
        assert b"New Name" in response.data
        assert b"NEW456" in response.data
        assert b"OLD123" not in response.data


def test_track123_link_is_available_without_ship24(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        response = client.get("/")
        assert b"https://www.track123.com/tracking" in response.data
        assert b"dashboard.ship24.com" not in response.data


def test_name_is_generated_when_left_empty(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        response = client.post(
            "/shipments",
            data={"name": "", "tracking_number": "AUTO123456", "source": "Amazon"},
            follow_redirects=True,
        )
        assert "משלוח מ־Amazon".encode() in response.data


def test_tracking_text_and_dates_are_localised(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_request_context():
        assert app.jinja_env.filters["event_he"]("Departed from Facility") == "יצא ממתקן המיון"
        assert app.jinja_env.filters["event_he"]("On the way, A trusted third-party vendor is on the way with your package · BEN GURION AIRPORT") == "החבילה בדרך עם חברת שילוח חיצונית"
        assert app.jinja_env.filters["event_he"]("Notification has been received regarding a parcel being shipped") == "התקבלה הודעה על משלוח החבילה"
        assert app.jinja_env.filters["event_he"]("Arrived at customs,Arrived at customs") == "המשלוח הגיע למכס"
        assert app.jinja_env.filters["event_he"]("Arrived at linehaul office,Arrived at linehaul office") == "הגיע למרכז ההעברה הבין־לאומי"
        assert app.jinja_env.filters["event_he"]("Departed from departure country/region,Left from departure country/region") == "יצא ממדינת המוצא"
        assert app.jinja_env.filters["event_he"]("Xiaoshan District,Departed from sorting center,Outbound in sorting center") == "יצא ממרכז המיון"
        assert app.jinja_env.filters["event_he"]("At local FedEx facility") == "במתקן המקומי של FedEx"
        assert app.jinja_env.filters["event_he"]("International shipment release - Import") == "המשלוח הבין־לאומי שוחרר ביבוא"
        assert app.jinja_env.filters["event_he"]("On the way, Package available for clearance") == "החבילה זמינה לשחרור מהמכס"
        assert app.jinja_env.filters["location_he"]("Lod, Israel") == "לוד, ישראל"
        assert app.jinja_env.filters["datetime_he"]("2026-09-21T07:12:41+00:00") == "21/09/2026 10:12"
        assert app.jinja_env.filters["date_he"]("2026-09-22T00:00:00.000Z") == "22/09/2026"


def test_courier_name_is_displayed(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        client.post(
            "/shipments",
            data={"name": "UPS Parcel", "tracking_number": "UPS123", "carrier_code": "ups"},
        )
        response = client.get("/")
        assert "חברת שילוח:".encode() in response.data
        assert b"UPS" in response.data


def test_product_image_can_be_added_and_removed(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    image_data = BytesIO()
    Image.new("RGB", (40, 30), "blue").save(image_data, "PNG")
    image_data.seek(0)
    with app.test_client() as client:
        login(client)
        response = client.post(
            "/shipments",
            data={
                "name": "Photo Parcel",
                "tracking_number": "PHOTO123",
                "product_image": (image_data, "product.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert b"shipment-1.webp" in response.data
        image_response = client.get("/shipment-images/shipment-1.webp")
        assert image_response.status_code == 200
        assert image_response.mimetype == "image/webp"
        client.post(
            "/shipments/1/edit",
            data={"name": "Photo Parcel", "tracking_number": "PHOTO123", "remove_image": "1"},
            follow_redirects=True,
        )
        assert client.get("/shipment-images/shipment-1.webp").status_code == 404


def test_duplicate_tracking_number(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        payload = {"name": "First", "tracking_number": "SAME123"}
        client.post("/shipments", data=payload)
        response = client.post("/shipments", data=payload, follow_redirects=True)
        assert "כבר קיים במערכת".encode() in response.data


def test_account_credentials_can_be_changed_in_web_ui(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        response = client.post(
            "/settings/account",
            data={
                "username": "new-user",
                "current_password": "test-password",
                "new_password": "new-test-password",
                "confirm_password": "new-test-password",
            },
            follow_redirects=True,
        )
        assert "עודכנו בהצלחה".encode() in response.data
        client.post("/logout")
        assert client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
        ).status_code == 200
        response = client.post(
            "/login",
            data={"username": "new-user", "password": "new-test-password"},
            follow_redirects=True,
        )
        assert "המשלוחים שלי".encode() in response.data


def test_account_change_requires_current_password(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        response = client.post(
            "/settings/account",
            data={
                "username": "new-user",
                "current_password": "wrong-password",
                "new_password": "new-test-password",
                "confirm_password": "new-test-password",
            },
            follow_redirects=True,
        )
        assert "הסיסמה הנוכחית שגויה".encode() in response.data


def test_shipments_can_be_sorted_by_nearest_delivery(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    import app as app_module

    with app.test_client() as client:
        login(client)
        client.post("/shipments", data={"name": "Later", "tracking_number": "LATER123"})
        client.post("/shipments", data={"name": "Sooner", "tracking_number": "SOONER123"})
        client.post("/shipments", data={"name": "Unknown", "tracking_number": "UNKNOWN123"})
        with app.app_context():
            db = app_module.get_db()
            db.execute("UPDATE shipments SET estimated_delivery='2026-09-25' WHERE tracking_number='LATER123'")
            db.execute("UPDATE shipments SET estimated_delivery='2026-09-22' WHERE tracking_number='SOONER123'")
            db.commit()
        response = client.get("/?sort=eta_asc")
        page = response.data.decode()
        assert page.index("Sooner") < page.index("Later") < page.index("Unknown")
        assert 'class="shipment shipment-compact"' in page


def test_nearest_delivery_is_the_default_sort_order(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    import app as app_module

    with app.test_client() as client:
        login(client)
        client.post("/shipments", data={"name": "Later", "tracking_number": "LATER123"})
        client.post("/shipments", data={"name": "Sooner", "tracking_number": "SOONER123"})
        with app.app_context():
            db = app_module.get_db()
            db.execute("UPDATE shipments SET estimated_delivery='2026-09-25' WHERE tracking_number='LATER123'")
            db.execute("UPDATE shipments SET estimated_delivery='2026-09-22' WHERE tracking_number='SOONER123'")
            db.commit()
        page = client.get("/").data.decode()
        assert page.index("Sooner") < page.index("Later")
        assert '<option value="eta_asc" selected>' in page


def test_shipments_can_be_searched_and_actions_include_delete(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        client.post(
            "/shipments",
            data={"name": "Network Cable", "tracking_number": "CABLE123", "source": "Amazon"},
        )
        client.post(
            "/shipments",
            data={"name": "Planter", "tracking_number": "PLANTER456", "source": "AliExpress"},
        )
        response = client.get("/?q=CABLE")
        assert b"Network Cable" in response.data
        assert b"Planter" not in response.data
        assert b'name="q" value="CABLE"' in response.data
        assert b'data-confirm=' in response.data
        assert b">\xd7\x9e\xd7\x97\xd7\x99\xd7\xa7\xd7\x94</button>" in response.data


def test_track123_query_uses_v21_api(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import app as app_module

    client = app_module.Track123Client()
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs["json"]))
        return {"accepted": {"content": [{"trackNo": "DSVPH005472484"}]}}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.get_tracking("DSVPH005472484")
    assert calls == [
        (
            "POST",
            "/tk/v2.1/track/query",
            {"trackNoInfos": [{"trackNo": "DSVPH005472484"}], "queryPageSize": 1},
        )
    ]
    assert result["trackNo"] == "DSVPH005472484"


def test_track123_tracking_response_is_normalized(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import app as app_module

    result = app_module.normalize_track123_tracking(
        {
            "trackNo": "DSVPH005472484",
            "transitStatus": "IN_TRANSIT",
            "transitSubStatus": "IN_TRANSIT_01",
            "expectedDelivery": "2026-09-25",
            "localLogisticsInfo": {
                "courierCode": "cainiao",
                "trackingDetails": [
                    {
                        "address": "Customs",
                        "eventTimeZeroUTC": "2026-09-17T08:08:28Z",
                        "eventDetail": "Arrived at customs",
                        "transitSubStatus": "IN_TRANSIT_01",
                    }
                ],
            },
        }
    )

    assert result["provider_name"] == "track123"
    assert result["status"] == "in_transit"
    assert result["latest_event"] == "Arrived at customs"
    assert result["carrier_code"] == "cainiao"
    assert result["estimated_delivery"] == "2026-09-25"


def test_track123_is_used_when_tracking_is_available(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACK123_API_KEY", "track123-test-key")
    flask_app = load_app(tmp_path, monkeypatch)
    import app as app_module

    track123_calls = []

    monkeypatch.setattr(
        app_module.track123_provider,
        "register",
        lambda tracking_number, carrier_code="": track123_calls.append(("register", tracking_number, carrier_code)) or {},
    )
    monkeypatch.setattr(
        app_module.track123_provider,
        "get_tracking",
        lambda tracking_number, carrier_code="": track123_calls.append(("query", tracking_number, carrier_code)) or {
            "transitStatus": "IN_TRANSIT",
            "localLogisticsInfo": {
                "courierCode": "cainiao",
                "trackingDetails": [
                    {
                        "eventTimeZeroUTC": "2026-09-17T08:08:28Z",
                        "eventDetail": "Arrived at customs",
                        "address": "Customs",
                    }
                ],
            },
        },
    )
    with flask_app.app_context():
        db = app_module.get_db()
        now = app_module.utc_now()
        cursor = db.execute(
            "INSERT INTO shipments (name,tracking_number,created_at,updated_at) VALUES (?,?,?,?)",
            ("AliExpress parcel", "DSVPH005472484", now, now),
        )
        db.commit()
        app_module.refresh_shipment(cursor.lastrowid, notify=False)
        shipment = db.execute("SELECT * FROM shipments WHERE id=?", (cursor.lastrowid,)).fetchone()

    assert track123_calls == [("register", "DSVPH005472484", ""), ("query", "DSVPH005472484", "")]
    assert shipment["provider_name"] == "track123"
    assert shipment["carrier_code"] == "cainiao"


def test_ship24_key_is_ignored_and_existing_history_survives(tmp_path, monkeypatch):
    monkeypatch.delenv("TRACK123_API_KEY", raising=False)
    monkeypatch.setenv("SHIP24_API_KEY", "legacy-key")
    flask_app = load_app(tmp_path, monkeypatch)
    import app as app_module

    with flask_app.app_context():
        db = app_module.get_db()
        now = app_module.utc_now()
        cursor = db.execute(
            "INSERT INTO shipments (name,tracking_number,provider_name,created_at,updated_at) VALUES (?,?,?,?,?)",
            ("Legacy parcel", "OLD123", "ship24", now, now),
        )
        db.execute(
            "INSERT INTO events (shipment_id,event_key,event_time,description,location,created_at) VALUES (?,?,?,?,?,?)",
            (cursor.lastrowid, "legacy-event", now, "Old scan", "Tel Aviv", now),
        )
        db.commit()
        assert app_module.any_provider_enabled() is False
        assert db.execute("SELECT description FROM events WHERE shipment_id=?", (cursor.lastrowid,)).fetchone()[0] == "Old scan"


def test_manual_carrier_is_used_for_track123_and_preserved_on_empty_response(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACK123_API_KEY", "test-key")
    flask_app = load_app(tmp_path, monkeypatch)
    import app as app_module

    calls = []
    monkeypatch.setattr(app_module.track123_provider, "register", lambda number, carrier="": calls.append(("register", carrier)))
    monkeypatch.setattr(app_module.track123_provider, "get_tracking", lambda number, carrier="": calls.append(("query", carrier)) or {"transitStatus": "NO_RECORD", "localLogisticsInfo": {"courierCode": "il-post"}})
    with flask_app.test_client() as client:
        login(client)
        client.post("/shipments", data={"tracking_number": "LO436083025GB", "carrier_code": "royal-mail"})
        assert calls == [("register", "royal-mail"), ("query", "royal-mail")]
        with flask_app.app_context():
            row = app_module.get_db().execute("SELECT carrier_code,carrier_override,provider_name FROM shipments WHERE tracking_number='LO436083025GB'").fetchone()
            assert (row["carrier_code"], row["carrier_override"], row["provider_name"]) == ("royal-mail", "royal-mail", "track123")


def test_edit_changes_registered_track123_carrier(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACK123_API_KEY", "test-key")
    flask_app = load_app(tmp_path, monkeypatch)
    import app as app_module

    calls = []
    monkeypatch.setattr(app_module.track123_provider, "register", lambda number, carrier="": calls.append(("register", carrier)))
    monkeypatch.setattr(app_module.track123_provider, "change_courier", lambda number, old, new: calls.append(("change", old, new)))
    monkeypatch.setattr(app_module.track123_provider, "get_tracking", lambda number, carrier="": calls.append(("query", carrier)) or None)
    with flask_app.test_client() as client:
        login(client)
        client.post("/shipments", data={"tracking_number": "LO436083025GB", "carrier_code": "israel-post"})
        client.post("/shipments/1/edit", data={"tracking_number": "LO436083025GB", "carrier_code": "royal-mail"})
        assert ("change", "israel-post", "royal-mail") in calls
        assert calls[-1] == ("query", "royal-mail")


def test_automatic_carrier_detection_replaces_stale_provider_without_erasing_history(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACK123_API_KEY", "test-key")
    flask_app = load_app(tmp_path, monkeypatch)
    import app as app_module

    monkeypatch.setattr(app_module.track123_provider, "register", lambda number, carrier="": None)
    monkeypatch.setattr(app_module.track123_provider, "get_tracking", lambda number, carrier="": {
        "transitStatus": "INIT", "localLogisticsInfo": {"courierCode": "royal-mail", "trackingDetails": []},
    })
    with flask_app.app_context():
        db = app_module.get_db()
        now = app_module.utc_now()
        cursor = db.execute(
            """INSERT INTO shipments (name,tracking_number,carrier_code,provider_name,status,latest_event,
               created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
            ("Old parcel", "LO436083025GB", "il-post", "ship24", "info_received", "Old scan", now, now),
        )
        db.execute(
            "INSERT INTO events (shipment_id,event_key,description,created_at) VALUES (?,?,?,?)",
            (cursor.lastrowid, "old", "Old scan", now),
        )
        db.commit()
        app_module.refresh_shipment(cursor.lastrowid, notify=False)
        row = db.execute("SELECT * FROM shipments WHERE id=?", (cursor.lastrowid,)).fetchone()
        assert (row["carrier_code"], row["provider_name"], row["status"], row["latest_event"]) == (
            "royal-mail", "track123", "pending", None,
        )
        assert db.execute("SELECT COUNT(*) FROM events WHERE shipment_id=?", (cursor.lastrowid,)).fetchone()[0] == 1
