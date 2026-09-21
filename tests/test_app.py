import importlib
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
        assert b'value="Old Name"' in client.get("/shipments/1/edit").data
        response = client.post(
            "/shipments/1/edit",
            data={"name": "New Name", "tracking_number": "NEW456", "carrier_code": "israel-post", "source": "New Store"},
            follow_redirects=True,
        )
        assert "עודכנו בהצלחה".encode() in response.data
        assert b"New Name" in response.data
        assert b"NEW456" in response.data
        assert b"OLD123" not in response.data


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


def test_ship24_tracking_response_is_normalized(tmp_path, monkeypatch):
    load_app(tmp_path, monkeypatch)
    import app as app_module

    result = app_module.normalize_tracking(
        {
            "shipment": {
                "statusMilestone": "available_for_pickup",
                "statusCode": "delivery_available_for_pickup",
                "delivery": {"estimatedDeliveryDate": "2026-09-22"},
            },
            "events": [
                {
                    "eventId": "event-1",
                    "order": 1,
                    "occurrenceDatetime": "2026-09-20T10:00:00+03:00",
                    "status": "Shipment received",
                    "location": "Tel Aviv",
                    "courierCode": "israel-post",
                },
                {
                    "eventId": "event-2",
                    "order": 2,
                    "occurrenceDatetime": "2026-09-21T10:00:00+03:00",
                    "status": "Ready for pickup",
                    "location": "Haifa",
                    "courierCode": "israel-post",
                },
            ],
        }
    )

    assert result["status"] == "available_for_pickup"
    assert result["latest_event"] == "Ready for pickup"
    assert result["latest_location"] == "Haifa"
    assert result["carrier_code"] == "israel-post"
    assert result["estimated_delivery"] == "2026-09-22"
