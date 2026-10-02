import json
import types
import uuid
import importlib
import sys

import pytest
from flask import Flask

import scrum_125 as logic


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def app(monkeypatch, db_path):
    # Ensure config module exists with desired DB_PATH before importing routes
    config_stub = types.SimpleNamespace(DB_PATH=db_path)
    monkeypatch.setitem(sys.modules, "config", config_stub)

    # Reload routes to pick up the config.DB_PATH value for this test
    if "scrum_125_routes" in sys.modules:
        del sys.modules["scrum_125_routes"]
    routes = importlib.import_module("scrum_125_routes")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def create_application(client, company="Acme", role="Engineer", status="applied", applied_date="2023-01-02", notes="note"):
    payload = {
        "company": company,
        "role": role,
        "status": status,
        "applied_date": applied_date,
        "notes": notes,
    }
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert isinstance(data, dict)
    return data


def test_dashboard_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("Content-Type", "")
    assert b"Job Applications Dashboard" in resp.data


def test_statuses_endpoint(client):
    resp = client.get("/applications/statuses")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "statuses" in data
    assert data["statuses"] == list(logic.get_statuses())


def test_grouped_initial_empty(client):
    resp = client.get("/applications/grouped")
    assert resp.status_code == 200
    data = resp.get_json()
    statuses = logic.get_statuses()
    assert isinstance(data, dict)
    # All expected statuses present and empty lists
    for s in statuses:
        assert s in data
        assert data[s] == []


def test_create_application_success_and_schema_smoke(client):
    created = create_application(client, company="FooCorp", role="Backend", status="applied", applied_date="2023-04-05", notes="first")
    # Verify schema keys on single object
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert expected_keys.issubset(set(created.keys()))

    # Schema smoke test on list endpoint
    resp = client.get("/applications")
    assert resp.status_code == 200
    apps = resp.get_json()
    assert isinstance(apps, list)
    assert len(apps) >= 1
    for app_obj in apps:
        assert expected_keys.issubset(set(app_obj.keys()))


def test_create_status_mixed_case_normalization(client):
    c1 = create_application(client, company="BarInc", role="Dev", status="Applied", applied_date="2023-04-06", notes="")
    assert c1["status"] == "applied"

    c2 = create_application(client, company="BazLLC", role="DevOps", status="APPLIED", applied_date="2023-04-07", notes="")
    assert c2["status"] == "applied"


def test_create_missing_required_fields(client):
    base = {"role": "Engineer", "status": "applied", "applied_date": "2023-01-02", "notes": ""}
    # Missing company
    resp = client.post("/applications", json={k: v for k, v in base.items() if k != "company"})
    assert resp.status_code == 422
    # Missing role
    base2 = {"company": "Acme", "status": "applied", "applied_date": "2023-01-02", "notes": ""}
    resp2 = client.post("/applications", json={k: v for k, v in base2.items() if k != "role"})
    assert resp2.status_code == 422


def test_create_non_json_body_returns_400(client):
    resp = client.post("/applications", data="not json", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Request body must be JSON"


def test_get_single_found_and_not_found(client):
    created = create_application(client, company="GetMe", role="QA", applied_date="2023-02-02", notes="x")
    app_id = created["id"]
    # Found
    resp = client.get(f"/applications/{app_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == app_id
    # Not found
    resp2 = client.get(f"/applications/{uuid.uuid4()}")
    assert resp2.status_code == 404


def test_put_update_success_and_persistence(client):
    created = create_application(client, company="OldCo", role="OldRole", applied_date="2023-03-03", notes="old")
    app_id = created["id"]
    patch = {
        "company": "NewCo",
        "role": "NewRole",
        "applied_date": "2023-03-04",
        "notes": "updated notes",
    }
    resp = client.put(f"/applications/{app_id}", json=patch)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["company"] == "NewCo"
    assert data["role"] == "NewRole"
    assert data["applied_date"] == "2023-03-04"
    assert data["notes"] == "updated notes"

    # Persisted
    resp2 = client.get(f"/applications/{app_id}")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["company"] == "NewCo"
    assert data2["role"] == "NewRole"
    assert data2["applied_date"] == "2023-03-04"
    assert data2["notes"] == "updated notes"


def test_put_update_status_mixed_case_normalization(client):
    created = create_application(client, company="StatCo", role="Tester", status="applied", applied_date="2023-05-01", notes="")
    app_id = created["id"]
    resp = client.put(f"/applications/{app_id}", json={"status": "InTeRvIeWiNg"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "interviewing"


def test_put_update_unknown_field_and_no_fields(client):
    created = create_application(client, company="X", role="Y", applied_date="2023-06-01", notes="")
    app_id = created["id"]

    # Unknown field
    resp = client.put(f"/applications/{app_id}", json={"foo": "bar"})
    assert resp.status_code == 422

    # No fields
    resp2 = client.put(f"/applications/{app_id}", json={})
    assert resp2.status_code == 422


def test_put_update_non_json_body_returns_400(client):
    created = create_application(client, company="A", role="B", applied_date="2023-07-01", notes="")
    app_id = created["id"]
    resp = client.put(f"/applications/{app_id}", data="not json", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "Request body must be JSON"


def test_put_update_not_found(client):
    # Attempt to update non-existent application
    resp = client.put(f"/applications/{uuid.uuid4()}", json={"company": "Z"})
    assert resp.status_code == 404


def test_change_status_endpoint(client):
    created = create_application(client, company="C", role="D", status="applied", applied_date="2023-08-01", notes="")
    app_id = created["id"]

    # Valid change with mixed case
    resp = client.put(f"/applications/{app_id}/status", json={"status": "Offer"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "offer"

    # Invalid type
    resp2 = client.put(f"/applications/{app_id}/status", json={"status": 123})
    assert resp2.status_code == 422

    # Invalid value
    resp3 = client.put(f"/applications/{app_id}/status", json={"status": "unknown"})
    assert resp3.status_code == 422


def test_delete_application_and_not_found(client):
    created = create_application(client, company="DelCo", role="DelRole", applied_date="2023-09-01", notes="")
    app_id = created["id"]

    resp = client.delete(f"/applications/{app_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"deleted": True}

    # Subsequent fetch should be 404
    resp2 = client.get(f"/applications/{app_id}")
    assert resp2.status_code == 404

    # Deleting non-existent should be 404
    resp3 = client.delete(f"/applications/{uuid.uuid4()}")
    assert resp3.status_code == 404


def test_list_flat_returns_all_and_grouped_counts(client):
    # Create several with different statuses and cases
    a1 = create_application(client, company="AC1", role="R1", status="Applied", applied_date="2023-10-01", notes="")
    a2 = create_application(client, company="AC2", role="R2", status="INTERVIEWING", applied_date="2023-10-02", notes="")
    a3 = create_application(client, company="AC3", role="R3", status="offer", applied_date="2023-10-03", notes="")
    a4 = create_application(client, company="AC4", role="R4", status="rejected", applied_date="2023-10-04", notes="")

    # Flat list includes all
    resp_list = client.get("/applications")
    assert resp_list.status_code == 200
    apps = resp_list.get_json()
    ids = {a["id"] for a in apps}
    assert {a1["id"], a2["id"], a3["id"], a4["id"]}.issubset(ids)

    # Grouped counts
    resp_grouped = client.get("/applications/grouped")
    assert resp_grouped.status_code == 200
    grouped = resp_grouped.get_json()
    assert grouped["applied"]  # a1
    assert grouped["interviewing"]  # a2
    assert grouped["offer"]  # a3
    assert grouped["rejected"]  # a4

    # Ensure normalization worked
    assert any(app["id"] == a1["id"] for app in grouped["applied"])
    assert any(app["id"] == a2["id"] for app in grouped["interviewing"])
    assert any(app["id"] == a3["id"] for app in grouped["offer"])
    assert any(app["id"] == a4["id"] for app in grouped["rejected"])