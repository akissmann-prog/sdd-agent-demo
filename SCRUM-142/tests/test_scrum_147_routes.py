import sys
import types
import importlib
import uuid

import pytest
from flask import Flask

import scrum_147  # ensure logic module is importable from same directory


def build_app(tmp_path):
    # Provide a config module with DB_PATH pointing to a real sqlite file in tmp_path
    db_path = tmp_path / "test.db"
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = str(db_path)
    sys.modules["config"] = config_mod

    # Ensure fresh import of routes so it picks up this DB_PATH
    if "scrum_147_routes" in sys.modules:
        del sys.modules["scrum_147_routes"]
    routes = importlib.import_module("scrum_147_routes")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(routes.bp)
    return app


@pytest.fixture
def app(tmp_path):
    return build_app(tmp_path)


def test_post_create_success_and_schema_smoke_and_status_normalization(app):
    client = app.test_client()

    # Initial list should be empty
    resp = client.get("/applications")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 0

    # Create minimal valid application (defaults applied)
    payload = {"company": "Acme Corp", "role": "Software Engineer"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    created1 = resp.get_json()
    # Schema smoke test keys
    for key in ("id", "company", "role", "status", "applied_date"):
        assert key in created1
    assert created1["company"] == "Acme Corp"
    assert created1["role"] == "Software Engineer"
    # Default status should be 'applied'
    assert created1["status"] == "applied"

    # After first POST, list and assert presence of expected keys
    resp = client.get("/applications")
    assert resp.status_code == 200
    listed = resp.get_json()
    assert "items" in listed
    assert len(listed["items"]) >= 1
    for item in listed["items"]:
        for key in ("id", "company", "role", "status", "applied_date"):
            assert key in item

    # Create with mixed-case status "Applied" -> normalized to lowercase
    payload2 = {"company": "Beta LLC", "role": "QA Engineer", "status": "Applied"}
    resp = client.post("/applications", json=payload2)
    assert resp.status_code == 201
    created2 = resp.get_json()
    assert created2["status"] == "applied"

    # Create with uppercase status "APPLIED" -> normalized to lowercase
    payload3 = {"company": "Gamma Inc", "role": "DevOps", "status": "APPLIED"}
    resp = client.post("/applications", json=payload3)
    assert resp.status_code == 201
    created3 = resp.get_json()
    assert created3["status"] == "applied"


def test_get_single_found_and_missing_and_invalid_id(app):
    client = app.test_client()

    # Create a record
    resp = client.post(
        "/applications",
        json={"company": "Acme", "role": "SWE", "status": "applied"},
    )
    assert resp.status_code == 201
    created = resp.get_json()
    app_id = created["id"]

    # Get by id (found)
    resp = client.get(f"/applications/{app_id}")
    assert resp.status_code == 200
    got = resp.get_json()
    assert got["id"] == app_id
    assert got["company"] == "Acme"
    assert got["role"] == "SWE"
    assert got["status"] == "applied"

    # Get by id (missing)
    missing_id = str(uuid.uuid4())
    resp = client.get(f"/applications/{missing_id}")
    assert resp.status_code == 404
    err = resp.get_json()
    assert "message" in err

    # Get by id (invalid UUID)
    resp = client.get("/applications/not-a-uuid")
    assert resp.status_code == 400
    err = resp.get_json()
    assert "message" in err


def test_post_validation_missing_required_fields(app):
    client = app.test_client()

    # Missing company
    resp = client.post("/applications", json={"role": "SWE"})
    assert resp.status_code == 400
    err = resp.get_json()
    assert "message" in err

    # Missing role
    resp = client.post("/applications", json={"company": "Acme"})
    assert resp.status_code == 400
    err = resp.get_json()
    assert "message" in err

    # Empty body (treated as {}), triggers required company error
    resp = client.post("/applications", data="")
    assert resp.status_code == 400
    err = resp.get_json()
    assert "message" in err


def test_put_update_success_and_status_normalization(app):
    client = app.test_client()

    # Create
    resp = client.post(
        "/applications",
        json={"company": "StartCo", "role": "Engineer", "status": "applied"},
    )
    assert resp.status_code == 201
    created = resp.get_json()
    app_id = created["id"]

    # Update with all fields, mixed-case status, valid date
    update_payload = {
        "company": "StartCo International",
        "role": "Senior Engineer",
        "status": "InTeRvIeWiNg",
        "applied_date": "2024-01-02",
    }
    resp = client.put(f"/applications/{app_id}", json=update_payload)
    assert resp.status_code == 200
    updated = resp.get_json()
    assert updated["id"] == app_id
    assert updated["company"] == "StartCo International"
    assert updated["role"] == "Senior Engineer"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2024-01-02"

    # Confirm via GET
    resp = client.get(f"/applications/{app_id}")
    assert resp.status_code == 200
    got = resp.get_json()
    assert got["status"] == "interviewing"
    assert got["company"] == "StartCo International"


def test_put_invalid_status_returns_400(app):
    client = app.test_client()

    # Create
    resp = client.post(
        "/applications",
        json={"company": "BadStatusCo", "role": "Eng", "status": "applied"},
    )
    assert resp.status_code == 201
    created = resp.get_json()
    app_id = created["id"]

    # Update with invalid status
    resp = client.put(
        f"/applications/{app_id}",
        json={"company": "BadStatusCo", "role": "Eng", "status": "UNKNOWN"},
    )
    assert resp.status_code == 400
    err = resp.get_json()
    assert "message" in err


def test_delete_success_then_missing_and_invalid_id(app):
    client = app.test_client()

    # Create
    resp = client.post(
        "/applications",
        json={"company": "DeleteCo", "role": "Ops", "status": "applied"},
    )
    assert resp.status_code == 201
    created = resp.get_json()
    app_id = created["id"]

    # Delete success
    resp = client.delete(f"/applications/{app_id}")
    assert resp.status_code == 204
    assert resp.data == b""

    # Subsequent get should be 404
    resp = client.get(f"/applications/{app_id}")
    assert resp.status_code == 404

    # Delete again should be 404
    resp = client.delete(f"/applications/{app_id}")
    assert resp.status_code == 404

    # Delete with invalid id should be 400
    resp = client.delete("/applications/not-a-uuid")
    assert resp.status_code == 400
    err = resp.get_json()
    assert "message" in err


def test_list_filter_by_status_mixed_case(app):
    client = app.test_client()

    # Create multiple records with different statuses
    resp = client.post(
        "/applications",
        json={"company": "OfferCo", "role": "Dev", "status": "Offer"},
    )
    assert resp.status_code == 201
    offer = resp.get_json()

    resp = client.post(
        "/applications",
        json={"company": "RejectCo", "role": "Dev", "status": "rejected"},
    )
    assert resp.status_code == 201
    rejected = resp.get_json()

    # Filter by status with mixed case
    resp = client.get("/applications?status=OFFER")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert all(item["status"] == "offer" for item in data["items"])
    ids = {item["id"] for item in data["items"]}
    assert offer["id"] in ids
    assert rejected["id"] not in ids

    resp = client.get("/applications?status=rejected")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert all(item["status"] == "rejected" for item in data["items"])
    ids = {item["id"] for item in data["items"]}
    assert rejected["id"] in ids
    assert offer["id"] not in ids