import sys
import types
import importlib
import pytest
from flask import Flask


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Create a fake config module with a DB_PATH pointing to a temp SQLite file
    db_path = tmp_path / "test.sqlite"
    config_module = types.ModuleType("config")
    config_module.DB_PATH = str(db_path)
    sys.modules["config"] = config_module

    # Ensure a fresh import of the routes module for each test, binding to this DB_PATH
    if "scrum_121_routes" in sys.modules:
        del sys.modules["scrum_121_routes"]

    # Import logic module (same directory) and routes module
    importlib.import_module("scrum_121")
    routes = importlib.import_module("scrum_121_routes")

    # Build a minimal Flask app and register only this blueprint
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_post_create_success_schema_smoke_and_list_filter(client):
    # Successful create with mixed-case status to test normalization
    payload = {
        "company": "  ACME Corp  ",
        "role": "Engineer",
        "status": "Applied",
        "applied_date": "2024-01-02",
        "notes": "first note",
    }
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert set(data.keys()) == expected_keys
    assert isinstance(data["id"], int)
    assert data["company"] == "ACME Corp"  # trimmed
    assert data["role"] == "Engineer"
    assert data["status"] == "applied"  # normalized to lowercase
    assert data["applied_date"] == "2024-01-02"
    assert data["notes"] == "first note"

    app_id = data["id"]

    # Schema smoke test via GET single
    resp_get = client.get(f"/applications/{app_id}")
    assert resp_get.status_code == 200
    data_get = resp_get.get_json()
    assert set(data_get.keys()) == expected_keys

    # List with mixed-case status filter should be accepted and return our record
    resp_list = client.get("/applications", query_string={"status": "APPLIED"})
    assert resp_list.status_code == 200
    list_data = resp_list.get_json()
    assert isinstance(list_data, list)
    assert any(item["id"] == app_id for item in list_data)
    for item in list_data:
        assert "id" in item and "company" in item and "role" in item and "status" in item and "applied_date" in item and "notes" in item
        assert item["status"] == "applied"


@pytest.mark.parametrize(
    "payload,missing_field_substr",
    [
        ({"role": "Engineer"}, "company"),
        ({"company": "ACME"}, "role"),
    ],
)
def test_post_validation_missing_required_fields(client, payload, missing_field_substr):
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
    assert missing_field_substr in data["error"]


def test_post_validation_non_json_body(client):
    resp = client.post("/applications", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Request body must be JSON"


def test_get_single_not_found(client):
    resp = client.get("/applications/999999")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data
    assert "not found" in data["error"].lower()


def test_put_update_success_and_status_case(client):
    # Create initial record
    create_resp = client.post(
        "/applications",
        json={"company": "Beta", "role": "Developer"},
    )
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # Update with mixed-case status and other fields
    update_payload = {
        "company": "Beta Corp",
        "role": "Senior Developer",
        "status": "OFFER",
        "applied_date": "2024-05-01",
        "notes": "  updated notes  ",
    }
    resp = client.put(f"/applications/{app_id}", json=update_payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == app_id
    assert data["company"] == "Beta Corp"
    assert data["role"] == "Senior Developer"
    assert data["status"] == "offer"  # normalized to lowercase
    assert data["applied_date"] == "2024-05-01"
    assert data["notes"] == "updated notes"  # trimmed


def test_put_validation_empty_json_no_fields(client):
    # Create initial record
    create_resp = client.post(
        "/applications",
        json={"company": "Gamma", "role": "QA"},
    )
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # Empty JSON should trigger "No updatable fields provided"
    resp = client.put(f"/applications/{app_id}", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
    assert "No updatable fields provided" in data["error"]


def test_put_validation_non_json_body(client):
    # Create initial record
    create_resp = client.post(
        "/applications",
        json={"company": "Delta", "role": "Analyst"},
    )
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    resp = client.put(f"/applications/{app_id}", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Request body must be JSON"


def test_delete_success_and_not_found(client):
    # Create then delete
    create_resp = client.post(
        "/applications",
        json={"company": "Epsilon", "role": "Ops"},
    )
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    del_resp = client.delete(f"/applications/{app_id}")
    assert del_resp.status_code == 204
    assert del_resp.data == b""

    # Ensure it's gone
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 404

    # Deleting again should 404
    del_resp2 = client.delete(f"/applications/{app_id}")
    assert del_resp2.status_code == 404


def test_list_route_without_filter_and_invalid_filter(client):
    # Create two records with different statuses
    r1 = client.post("/applications", json={"company": "A", "role": "R1", "status": "Applied"})
    assert r1.status_code == 201
    r2 = client.post("/applications", json={"company": "B", "role": "R2", "status": "Rejected"})
    assert r2.status_code == 201

    # List without filter should return both
    resp_all = client.get("/applications")
    assert resp_all.status_code == 200
    data_all = resp_all.get_json()
    assert isinstance(data_all, list)
    ids = {item["id"] for item in data_all}
    assert r1.get_json()["id"] in ids and r2.get_json()["id"] in ids

    # Invalid filter should 400
    resp_bad = client.get("/applications", query_string={"status": "unknown"})
    assert resp_bad.status_code == 400
    err = resp_bad.get_json()
    assert "error" in err
    assert "Invalid status" in err["error"] or "status filter cannot be empty" in err["error"]