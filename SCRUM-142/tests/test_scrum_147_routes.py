import json
import uuid
import sys
import types
import importlib
import pytest
from flask import Flask


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    # Prepare config module with DB_PATH for this test
    db_path = str(tmp_path / "test.db")
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = db_path
    sys.modules["config"] = config_mod

    # Ensure fresh imports for per-test DB_PATH
    for name in ["scrum_147_routes", "scrum_147"]:
        if name in sys.modules:
            sys.modules.pop(name)

    logic = importlib.import_module("scrum_147")
    routes = importlib.import_module("scrum_147_routes")

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()
    return client, routes, logic


def test_post_create_and_schema_smoke(app_client):
    client, _, _ = app_client

    # Create an application (no status/applied_date to use defaults)
    payload = {"company": "Acme Corp", "role": "Backend Engineer"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    created = resp.get_json()
    assert created["company"] == "Acme Corp"
    assert created["role"] == "Backend Engineer"
    assert created["status"] == "applied"
    assert "applied_date" in created
    app_id = created["id"]

    # Schema smoke test via list endpoint
    resp_list = client.get("/applications")
    assert resp_list.status_code == 200
    body = resp_list.get_json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 1
    item = body["items"][0]
    for key in ["id", "company", "role", "status", "applied_date"]:
        assert key in item

    # GET single
    resp_single = client.get(f"/applications/{app_id}")
    assert resp_single.status_code == 200
    single = resp_single.get_json()
    for key in ["id", "company", "role", "status", "applied_date"]:
        assert key in single
    assert single["id"] == app_id


def test_post_validation_missing_company(app_client):
    client, _, _ = app_client

    payload = {"role": "Developer"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert "message" in body


def test_post_validation_missing_role(app_client):
    client, _, _ = app_client

    payload = {"company": "Acme"}
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert "message" in body


def test_status_normalization_on_create(app_client):
    client, _, _ = app_client

    # Mixed case status values should be accepted and normalized to lowercase
    payload1 = {"company": "Acme", "role": "Dev", "status": "Applied"}
    resp1 = client.post("/applications", json=payload1)
    assert resp1.status_code == 201
    body1 = resp1.get_json()
    assert body1["status"] == "applied"

    payload2 = {"company": "Beta", "role": "QA", "status": "APPLIED"}
    resp2 = client.post("/applications", json=payload2)
    assert resp2.status_code == 201
    body2 = resp2.get_json()
    assert body2["status"] == "applied"

    # Ensure both are retrievable
    resp_list = client.get("/applications")
    assert resp_list.status_code == 200
    items = resp_list.get_json()["items"]
    assert len(items) == 2
    assert all(i["status"] == "applied" for i in items)


def test_get_list_with_status_filter(app_client):
    client, _, _ = app_client

    # Seed various statuses
    client.post("/applications", json={"company": "Acme", "role": "Dev", "status": "Applied"})
    client.post("/applications", json={"company": "Beta", "role": "QA", "status": "Interviewing"})
    client.post("/applications", json={"company": "Gamma", "role": "PM", "status": "Offer"})
    client.post("/applications", json={"company": "Delta", "role": "Ops", "status": "Rejected"})

    # Filter with mixed case query param
    resp = client.get("/applications?status=InTeRviEwing")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["company"] == "Beta"
    assert items[0]["status"] == "interviewing"


def test_put_update_success_and_status_normalization(app_client):
    client, _, _ = app_client

    # Create initial
    create_resp = client.post("/applications", json={"company": "Acme", "role": "Dev"})
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # Update with all fields, status mixed case
    update_payload = {
        "company": "Acme Updated",
        "role": "Senior Dev",
        "status": "INTERVIEWING",
        "applied_date": "2023-01-15",
    }
    put_resp = client.put(f"/applications/{app_id}", json=update_payload)
    assert put_resp.status_code == 200
    updated = put_resp.get_json()
    assert updated["company"] == "Acme Updated"
    assert updated["role"] == "Senior Dev"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2023-01-15"

    # Confirm persisted
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 200
    got = get_resp.get_json()
    assert got == updated


def test_put_validation_errors(app_client):
    client, _, _ = app_client

    # Invalid UUID format
    resp_invalid_id = client.put("/applications/not-a-uuid", json={"company": "New", "role": "New"})
    assert resp_invalid_id.status_code == 400

    # Valid UUID but not found
    some_uuid = str(uuid.uuid4())
    resp_not_found = client.put(f"/applications/{some_uuid}", json={"company": "New", "role": "New"})
    assert resp_not_found.status_code == 404

    # Create one to test field validations
    create_resp = client.post("/applications", json={"company": "Acme", "role": "Dev"})
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # Invalid status
    resp_bad_status = client.put(f"/applications/{app_id}", json={"status": "unknown"})
    assert resp_bad_status.status_code == 400

    # Invalid applied_date
    resp_bad_date = client.put(f"/applications/{app_id}", json={"applied_date": "2024/01/01"})
    assert resp_bad_date.status_code == 400

    # Empty/whitespace role
    resp_empty_role = client.put(f"/applications/{app_id}", json={"role": "   "})
    assert resp_empty_role.status_code == 400

    # Empty/whitespace company
    resp_empty_company = client.put(f"/applications/{app_id}", json={"company": "   "})
    assert resp_empty_company.status_code == 400


def test_delete_success_and_not_found(app_client):
    client, _, _ = app_client

    # Create
    create_resp = client.post("/applications", json={"company": "Acme", "role": "Dev"})
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # Delete success
    del_resp = client.delete(f"/applications/{app_id}")
    assert del_resp.status_code == 204
    assert del_resp.data == b""

    # Get after delete -> 404
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 404

    # Delete again -> 404
    del_resp2 = client.delete(f"/applications/{app_id}")
    assert del_resp2.status_code == 404

    # Invalid id -> 400
    del_bad = client.delete("/applications/not-a-uuid")
    assert del_bad.status_code == 400


def test_get_single_invalid_id_and_not_found(app_client):
    client, _, _ = app_client

    # Invalid UUID
    resp_bad = client.get("/applications/12345")
    assert resp_bad.status_code == 400

    # Valid UUID but not found
    resp_nf = client.get(f"/applications/{uuid.uuid4()}")
    assert resp_nf.status_code == 404


def test_invalid_json_returns_400(app_client):
    client, _, _ = app_client

    # Non-empty invalid JSON body
    resp = client.post("/applications", data="not json", content_type="application/json")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "message" in body and body["message"] == "invalid JSON"