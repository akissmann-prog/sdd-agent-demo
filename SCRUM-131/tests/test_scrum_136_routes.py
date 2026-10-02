import sys
import types
import importlib
from flask import Flask
import pytest

import scrum_136  # ensure logic module is importable alongside routes


@pytest.fixture
def client(tmp_path):
    # Provide a config module with DB_PATH for the routes module
    db_path = str(tmp_path / "test.db")
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = db_path
    sys.modules["config"] = config_mod

    # Import or reload the routes module so it reads the new DB_PATH
    if "scrum_136_routes" in sys.modules:
        importlib.reload(sys.modules["scrum_136_routes"])
        routes = sys.modules["scrum_136_routes"]
    else:
        routes = importlib.import_module("scrum_136_routes")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(routes.bp)

    with app.test_client() as c:
        yield c


def test_post_create_success_and_schema_smoke(client):
    payload = {
        "company": "Acme Corp",
        "role": "Backend Engineer",
        "status": "Applied",  # mixed case to test normalization
        "applied_date": "2023-07-01",
        "notes": "Remote-first company",
    }
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    body = resp.get_json()
    assert isinstance(body, dict)
    assert "data" in body
    created = body["data"]
    assert created["status"] == "applied"  # normalized
    new_id = created["id"]

    # Schema smoke test: GET single and assert all expected keys are present
    resp2 = client.get(f"/applications/{new_id}")
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert "data" in body2
    fetched = body2["data"]
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert set(fetched.keys()) == expected_keys

    # GET list should include the created item
    resp3 = client.get("/applications")
    assert resp3.status_code == 200
    body3 = resp3.get_json()
    assert "data" in body3
    items = body3["data"]
    assert any(item["id"] == new_id for item in items)


def test_post_validation_missing_required_fields_and_unknown_and_invalid_json(client):
    # Missing company
    resp = client.post("/applications", json={"role": "Engineer"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Bad Request"
    assert "company" in body["details"]

    # Missing role
    resp = client.post("/applications", json={"company": "Acme"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "role" in body["details"]

    # Unknown field present
    resp = client.post("/applications", json={"company": "Acme", "role": "Dev", "foo": "bar"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "unknown" in body["details"]
    assert "foo" in body["details"]["unknown"]

    # Invalid or missing JSON body
    resp = client.post("/applications", data="not json", content_type="application/json")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Bad Request"
    assert "json" in body["details"]


def test_get_list_and_filter_status_and_invalid_filter(client):
    # Create multiple applications with varying statuses (with mixed case)
    r1 = client.post("/applications", json={"company": "A", "role": "R1", "status": "Applied"})
    assert r1.status_code == 201
    id1 = r1.get_json()["data"]["id"]

    r2 = client.post("/applications", json={"company": "B", "role": "R2", "status": "INTERVIEWING"})
    assert r2.status_code == 201
    id2 = r2.get_json()["data"]["id"]

    r3 = client.post("/applications", json={"company": "C", "role": "R3", "status": "rejected"})
    assert r3.status_code == 201
    id3 = r3.get_json()["data"]["id"]

    # GET all
    resp_all = client.get("/applications")
    assert resp_all.status_code == 200
    items = resp_all.get_json()["data"]
    ids = [it["id"] for it in items]
    assert set(ids) == {id1, id2, id3}

    # GET filter by status lowercase
    resp_applied = client.get("/applications?status=applied")
    assert resp_applied.status_code == 200
    items_applied = resp_applied.get_json()["data"]
    assert len(items_applied) == 1
    assert items_applied[0]["status"] == "applied"

    # GET filter by status mixed case should also work
    resp_applied2 = client.get("/applications?status=Applied")
    assert resp_applied2.status_code == 200
    items_applied2 = resp_applied2.get_json()["data"]
    assert len(items_applied2) == 1
    assert items_applied2[0]["status"] == "applied"

    # Invalid filter value
    resp_bad = client.get("/applications?status=invalid_status")
    assert resp_bad.status_code == 400
    body_bad = resp_bad.get_json()
    assert body_bad["error"] == "Bad Request"
    assert "status" in body_bad["details"]


def test_get_single_404_not_found(client):
    resp = client.get("/applications/999999")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"


def test_put_update_success_and_validation(client):
    # Create an application to update
    create_resp = client.post("/applications", json={"company": "InitCo", "role": "Initial"})
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["data"]["id"]

    # Successful update with mixed-case status and notes None
    update_payload = {"status": "OFFER", "notes": None}
    upd_resp = client.put(f"/applications/{app_id}", json=update_payload)
    assert upd_resp.status_code == 200
    updated = upd_resp.get_json()["data"]
    assert updated["status"] == "offer"
    assert updated["notes"] is None

    # Verify persisted via GET
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 200
    got = get_resp.get_json()["data"]
    assert got["status"] == "offer"
    assert got["notes"] is None

    # Validation: empty update payload
    resp_empty = client.put(f"/applications/{app_id}", json={})
    assert resp_empty.status_code == 400
    body_empty = resp_empty.get_json()
    assert body_empty["error"] == "Bad Request"
    assert "non_field" in body_empty["details"]

    # Validation: unknown field in update
    resp_unknown = client.put(f"/applications/{app_id}", json={"foo": "bar"})
    assert resp_unknown.status_code == 400
    body_unknown = resp_unknown.get_json()
    assert "unknown" in body_unknown["details"]
    assert "foo" in body_unknown["details"]["unknown"]

    # Validation: invalid company (empty after trim)
    resp_bad_company = client.put(f"/applications/{app_id}", json={"company": "   "})
    assert resp_bad_company.status_code == 400
    body_bad_company = resp_bad_company.get_json()
    assert "company" in body_bad_company["details"]

    # Update non-existent id
    resp_not_found = client.put("/applications/999999", json={"status": "rejected"})
    assert resp_not_found.status_code == 404
    body_not_found = resp_not_found.get_json()
    assert body_not_found["error"] == "Not Found"


def test_delete_success_and_404(client):
    # Create
    create_resp = client.post("/applications", json={"company": "DeleteCo", "role": "ToDelete"})
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["data"]["id"]

    # Delete success
    del_resp = client.delete(f"/applications/{app_id}")
    assert del_resp.status_code == 204
    assert del_resp.data == b""

    # Confirm gone
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 404

    # Delete again -> 404
    del_resp2 = client.delete(f"/applications/{app_id}")
    assert del_resp2.status_code == 404
    body = del_resp2.get_json()
    assert body["error"] == "Not Found"