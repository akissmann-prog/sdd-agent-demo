import json
import re
import sys
import types
import importlib

import pytest
from flask import Flask


@pytest.fixture
def app(monkeypatch, tmp_path):
    # Create a dynamic config module with a tmp sqlite db path
    db_path = tmp_path / "test.db"
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = str(db_path)
    monkeypatch.setitem(sys.modules, "config", config_mod)

    # Ensure fresh import of routes after injecting config
    if "scrum_136_routes" in sys.modules:
        del sys.modules["scrum_136_routes"]

    routes = importlib.import_module("scrum_136_routes")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(routes.bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def assert_has_application_keys(obj):
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert set(obj.keys()) == expected_keys


def test_create_application_success_and_schema_smoke(client):
    payload = {"company": "Acme Corp", "role": "SWE"}
    r = client.post("/applications", json=payload)
    assert r.status_code == 201
    body = r.get_json()
    assert "data" in body
    created = body["data"]
    assert_has_application_keys(created)
    assert created["company"] == "Acme Corp"
    assert created["role"] == "SWE"
    assert created["status"] == "applied"  # default
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", created["applied_date"])

    # Schema smoke test via GET list
    r2 = client.get("/applications")
    assert r2.status_code == 200
    list_body = r2.get_json()
    assert "data" in list_body
    items = list_body["data"]
    assert len(items) == 1
    assert_has_application_keys(items[0])


@pytest.mark.parametrize(
    "missing_field,base_payload",
    [
        ("company", {"role": "Engineer"}),
        ("role", {"company": "Initech"}),
    ],
)
def test_create_validation_missing_required_fields(client, missing_field, base_payload):
    r = client.post("/applications", json=base_payload)
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "Bad Request"
    assert "details" in body
    assert missing_field in body["details"]


def test_create_with_invalid_json_body(client):
    # Send invalid JSON
    r = client.post("/applications", data="not json", content_type="application/json")
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "Bad Request"
    assert body["details"].get("json") is not None


@pytest.mark.parametrize("status_value", ["Applied", "APPLIED"])
def test_status_field_mixed_case_on_post(client, status_value):
    payload = {"company": "Globex", "role": "Dev", "status": status_value}
    r = client.post("/applications", json=payload)
    assert r.status_code == 201
    body = r.get_json()
    created = body["data"]
    assert created["status"] == "applied"


def test_get_single_and_404(client):
    # Create one
    r = client.post("/applications", json={"company": "Umbrella", "role": "QA"})
    assert r.status_code == 201
    app_id = r.get_json()["data"]["id"]

    # Get existing
    r2 = client.get(f"/applications/{app_id}")
    assert r2.status_code == 200
    got = r2.get_json()["data"]
    assert_has_application_keys(got)
    assert got["id"] == app_id

    # Get missing
    r3 = client.get("/applications/999999")
    assert r3.status_code == 404
    err = r3.get_json()
    assert err["error"] == "Not Found"


def test_update_application_success_and_validation(client):
    # Create
    r = client.post("/applications", json={"company": "Soylent", "role": "SWE"})
    assert r.status_code == 201
    app_id = r.get_json()["data"]["id"]

    # Update with multiple fields including mixed-case status
    upd = {"notes": "Updated notes", "role": "SWE II", "status": "OFFer"}
    r2 = client.put(f"/applications/{app_id}", json=upd)
    assert r2.status_code == 200
    updated = r2.get_json()["data"]
    assert updated["notes"] == "Updated notes"
    assert updated["role"] == "SWE II"
    assert updated["status"] == "offer"

    # Update with invalid status
    r3 = client.put(f"/applications/{app_id}", json={"status": "hired"})
    assert r3.status_code == 400
    body3 = r3.get_json()
    assert "status" in body3["details"]

    # Update with no updatable fields -> validation error
    r4 = client.put(f"/applications/{app_id}", json={})
    assert r4.status_code == 400
    body4 = r4.get_json()
    assert "non_field" in body4["details"]


def test_delete_application_flow(client):
    # Create
    r = client.post("/applications", json={"company": "Initech", "role": "TPS Manager"})
    assert r.status_code == 201
    app_id = r.get_json()["data"]["id"]

    # Delete existing
    r2 = client.delete(f"/applications/{app_id}")
    assert r2.status_code == 204
    assert r2.data == b""

    # After delete, GET should 404
    r3 = client.get(f"/applications/{app_id}")
    assert r3.status_code == 404

    # Deleting again should 404
    r4 = client.delete(f"/applications/{app_id}")
    assert r4.status_code == 404


def test_list_filter_status_and_invalid_filter(client):
    # Seed multiple
    r1 = client.post("/applications", json={"company": "A", "role": "R1"})  # default 'applied'
    assert r1.status_code == 201

    r2 = client.post(
        "/applications",
        json={"company": "B", "role": "R2", "status": "IntervieWing"},
    )
    assert r2.status_code == 201

    # Filter interviewing
    r = client.get("/applications?status=IntervieWing")
    assert r.status_code == 200
    items = r.get_json()["data"]
    assert all(item["status"] == "interviewing" for item in items)
    assert len(items) == 1
    assert items[0]["company"] == "B"

    # Invalid filter
    r_bad = client.get("/applications?status=unknown")
    assert r_bad.status_code == 400
    assert r_bad.get_json()["error"] == "Bad Request"