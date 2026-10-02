import json
import sys
import types
import importlib
from datetime import date
import pytest
from flask import Flask


@pytest.fixture
def app(tmp_path):
    # Prepare a fresh 'config' module with a DB_PATH pointing to a temp SQLite file
    db_file = tmp_path / "test.db"
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = str(db_file)
    sys.modules["config"] = config_mod

    # Ensure we import a fresh routes module each time so it picks up the DB_PATH value
    if "scrum_132_routes" in sys.modules:
        del sys.modules["scrum_132_routes"]
    routes = importlib.import_module("scrum_132_routes")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_list_initially_empty(client):
    resp = client.get("/applications")
    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == []


def test_create_application_success_201_and_location_and_schema_keys(client):
    payload = {
        "company": "Acme Corp",
        "role": "Software Engineer",
        "status": "applied",
        "notes": "First application"
    }
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    assert resp.is_json
    created = resp.get_json()
    assert isinstance(created.get("id"), int)
    assert resp.headers.get("Location") == f"/applications/{created['id']}"

    # Schema smoke: ensure all expected keys exist
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert expected_keys.issubset(created.keys())

    # After POST, list should contain the record and include all keys
    list_resp = client.get("/applications")
    assert list_resp.status_code == 200
    assert list_resp.is_json
    apps = list_resp.get_json()
    assert isinstance(apps, list)
    assert len(apps) >= 1
    found = next((a for a in apps if a["id"] == created["id"]), None)
    assert found is not None
    assert expected_keys.issubset(found.keys())


def test_get_single_and_404_behavior(client):
    # Create a record
    payload = {"company": "Beta LLC", "role": "QA"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    app_id = resp.get_json()["id"]

    # Fetch it
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 200
    assert get_resp.is_json
    data = get_resp.get_json()
    assert data["id"] == app_id
    assert data["company"] == "Beta LLC"
    assert data["role"] == "QA"
    assert set(["id", "company", "role", "status", "applied_date", "notes"]).issubset(data.keys())

    # Missing id -> 404
    missing_resp = client.get("/applications/999999")
    assert missing_resp.status_code == 404
    assert missing_resp.is_json


def test_update_application_success_and_validations(client):
    # Create initial record
    payload = {"company": "Gamma Inc", "role": "DevOps", "status": "applied"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    app_id = resp.get_json()["id"]

    # Valid update: change multiple fields
    update_payload = {
        "company": "Gamma Incorporated",
        "role": "Senior DevOps",
        "status": "interviewing",
        "applied_date": "2024-01-02",
        "notes": "Phone screen scheduled"
    }
    up_resp = client.put(f"/applications/{app_id}", json=update_payload)
    assert up_resp.status_code == 200
    updated = up_resp.get_json()
    assert updated["company"] == "Gamma Incorporated"
    assert updated["role"] == "Senior DevOps"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2024-01-02"
    assert updated["notes"] == "Phone screen scheduled"

    # Validate invalid updates
    # 1) Empty body
    up_empty = client.put(f"/applications/{app_id}", json={})
    assert up_empty.status_code == 400

    # 2) Unknown field
    up_unknown = client.put(f"/applications/{app_id}", json={"foo": "bar"})
    assert up_unknown.status_code == 400

    # 3) Invalid status
    up_bad_status = client.put(f"/applications/{app_id}", json={"status": "hired"})
    assert up_bad_status.status_code == 400

    # 4) Invalid date format
    up_bad_date = client.put(f"/applications/{app_id}", json={"applied_date": "20240102"})
    assert up_bad_date.status_code == 400

    # 5) Update missing id -> 404
    up_missing = client.put("/applications/999999", json={"company": "Zed"})
    assert up_missing.status_code == 404


def test_delete_application_and_404(client):
    # Create record
    payload = {"company": "Delta Co", "role": "Analyst"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    app_id = resp.get_json()["id"]

    # Delete it
    del_resp = client.delete(f"/applications/{app_id}")
    assert del_resp.status_code == 204
    assert del_resp.data == b""

    # Now should be 404 on get
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 404

    # Delete non-existent -> 404
    del_missing = client.delete("/applications/999999")
    assert del_missing.status_code == 404


@pytest.mark.parametrize("missing_field,payload", [
    ("company", {"role": "Engineer"}),
    ("role", {"company": "Acme"}),
])
def test_post_validation_missing_required_fields(client, missing_field, payload):
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 400
    assert resp.is_json
    err = resp.get_json()
    assert "error" in err


def test_post_validation_missing_json_body(client):
    resp = client.post("/applications")
    assert resp.status_code == 400
    assert resp.is_json
    assert "error" in resp.get_json()


def test_list_filtering_and_invalid_status_param(client):
    # Create various statuses
    apps_to_create = [
        {"company": "A", "role": "R1", "status": "applied"},
        {"company": "B", "role": "R2", "status": "interviewing"},
        {"company": "C", "role": "R3", "status": "offer"},
        {"company": "D", "role": "R4", "status": "rejected"},
    ]
    ids = []
    for p in apps_to_create:
        r = client.post("/applications", json=p)
        assert r.status_code == 201
        ids.append(r.get_json()["id"])

    # Filter per status
    for status in ["applied", "interviewing", "offer", "rejected"]:
        r = client.get(f"/applications?status={status}")
        assert r.status_code == 200
        data = r.get_json()
        assert all(item["status"] == status for item in data)

    # Empty status treated as no filter
    r_empty = client.get("/applications?status=")
    assert r_empty.status_code == 200
    all_data = r_empty.get_json()
    assert len(all_data) >= len(apps_to_create)

    # Invalid filter -> 400
    r_invalid = client.get("/applications?status=unknown")
    assert r_invalid.status_code == 400

    # Mixed-case filter (should be invalid per current validation)
    r_mixed = client.get("/applications?status=Applied")
    assert r_mixed.status_code == 400


@pytest.mark.parametrize("mixed_status", ["Applied", "APPLIED", "InterViewing"])
def test_status_field_mixed_case_rejected_on_post_and_put(client, mixed_status):
    # POST with mixed-case status should fail validation
    resp = client.post("/applications", json={"company": "X", "role": "Y", "status": mixed_status})
    assert resp.status_code == 400

    # Create a valid record
    ok = client.post("/applications", json={"company": "X", "role": "Y", "status": "applied"})
    assert ok.status_code == 201
    app_id = ok.get_json()["id"]

    # PUT with mixed-case status should fail validation
    up = client.put(f"/applications/{app_id}", json={"status": mixed_status})
    assert up.status_code == 400


def test_dashboard_route_serves_html(client):
    resp = client.get("/applications/dashboard")
    assert resp.status_code == 200
    # Content-Type should be text/html
    assert "text/html" in resp.headers.get("Content-Type", "").lower()
    body = resp.data.decode("utf-8", errors="ignore")
    assert "<!doctype html>" in body.lower()
    assert "Job Applications" in body