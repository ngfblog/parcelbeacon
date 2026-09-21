import importlib


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


def test_duplicate_tracking_number(tmp_path, monkeypatch):
    app = load_app(tmp_path, monkeypatch)
    with app.test_client() as client:
        login(client)
        payload = {"name": "First", "tracking_number": "SAME123"}
        client.post("/shipments", data=payload)
        response = client.post("/shipments", data=payload, follow_redirects=True)
        assert "כבר קיים במערכת".encode() in response.data
