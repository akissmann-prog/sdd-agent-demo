import sys
import types
import importlib
import re

import pytest
from flask import Flask


@pytest.fixture
def app(tmp_path):
    # Prepare a dynamic config module with DB_PATH pointing to a temp sqlite file
    db_path = tmp_path / "test.db"
    config_module = types.ModuleType("config")
    config_module.DB_PATH = str(db_path)
    sys.modules["config"] = config_module

    # Ensure routes import uses our config
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


def create_application(client, payload):
    return client.post("/applications", json=payload)


def test_get_list_empty(client):
    resp = client.get("/applications")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "data" in data
    assert isinstance(data["data"], list)
    assert data["data"] == []


def test_post_create_success_and_schema_smoke(client):
    payload = {"company": "Acme Corp", "role": "Engineer", "status": "Applied", "notes": "First app"}
    resp = create_application(client, payload)
    assert resp.status_code == 201
    body = resp.get_json()
    assert "data" in body
    entity = body["data"]
    # Schema smoke: all keys present
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert set(entity.keys()) == expected_keys
    assert entity["company"] == "Acme Corp"
    assert entity["role"] == "Engineer"
    assert entity["status"] == "applied"
    assert entity["notes"] == "First app"
    assert isinstance(entity["id"], int)
    assert isinstance(entity["applied_date"], str)
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", entity["applied_date"])

    # GET list should include the created entity, with all keys
    resp2 = client.get("/applications")
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert "data" in body2
    items = body2["data"]
    assert len(items) >= 1
    found = next((i for i in items if i["id"] == entity["id"]), None)
    assert found is not None
    assert set(found.keys()) == expected_keys


def test_post_validation_missing_company(client):
    payload = {"role": "Engineer"}
    resp = create_application(client, payload)
    assert resp.status_code == 400
    err = resp.get_json()
    assert err["error"] == "Bad Request"
    assert "details" in err
    assert "company" in err["details"]
    assert err["details"]["company"] in ("is required", "must be a non-empty string")


def test_post_validation_missing_role(client):
    payload = {"company": "Acme"}
    resp = create_application(client, payload)
    assert resp.status_code == 400
    err = resp.get_json()
    assert err["error"] == "Bad Request"
    assert "details" in err
    assert "role" in err["details"]
    assert err["details"]["role"] in ("is required", "must be a non-empty string")


def test_post_status_mixed_case_values(client):
    # Mixed case "APPLIED" should be normalized
    payload = {"company": "Beta", "role": "Dev", "status": "APPLIED"}
    resp = create_application(client, payload)
    assert resp.status_code == 201
    entity = resp.get_json()["data"]
    assert entity["status"] == "applied"

    # Another mixed case status
    payload2 = {"company": "Gamma", "role": "QA", "status": "InTeRvIeWiNg"}
    resp2 = create_application(client, payload2)
    assert resp2.status_code == 201
    entity2 = resp2.get_json()["data"]
    assert entity2["status"] == "interviewing"


def test_list_filter_status_case_insensitive_and_invalid(client):
    # Create some records
    r1 = create_application(client, {"company": "Acme", "role": "Eng", "status": "Applied"})
    assert r1.status_code == 201
    r2 = create_application(client, {"company": "Other", "role": "Mgr", "status": "rejected"})
    assert r2.status_code == 201

    # Filter with mixed-case status
    resp = client.get("/applications?status=APPLIED")
    assert resp.status_code == 200
    items = resp.get_json()["data"]
    assert all(item["status"] == "applied" for item in items)

    # Invalid filter value
    resp2 = client.get("/applications?status=unknown")
    assert resp2.status_code == 400
    err = resp2.get_json()
    assert err["error"] == "Bad Request"
    assert "status" in err["details"]


def test_get_single_404_when_missing(client):
    resp = client.get("/applications/999999")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"


def test_get_single_success(client):
    resp = create_application(client, {"company": "Acme", "role": "Engineer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["data"]["id"]

    resp2 = client.get(f"/applications/{new_id}")
    assert resp2.status_code == 200
    data = resp2.get_json()["data"]
    assert data["id"] == new_id
    assert data["company"] == "Acme"
    assert data["role"] == "Engineer"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["applied_date"])


def test_put_update_success_and_status_normalization(client):
    # Create
    resp = create_application(client, {"company": "Acme", "role": "Engineer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["data"]["id"]

    # Update with mixed case status and update notes
    update_payload = {"status": "OFFER", "notes": "verbal offer"}
    resp2 = client.put(f"/applications/{new_id}", json=update_payload)
    assert resp2.status_code == 200
    updated = resp2.get_json()["data"]
    assert updated["id"] == new_id
    assert updated["status"] == "offer"
    assert updated["notes"] == "verbal offer"

    # Confirm persisted via GET
    resp3 = client.get(f"/applications/{new_id}")
    assert resp3.status_code == 200
    assert resp3.get_json()["data"]["status"] == "offer"


def test_put_validation_no_fields(client):
    resp = create_application(client, {"company": "Acme", "role": "Engineer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["data"]["id"]

    # Empty object -> validator should reject
    resp2 = client.put(f"/applications/{new_id}", json={})
    assert resp2.status_code == 400
    err = resp2.get_json()
    assert err["error"] == "Bad Request"
    assert "non_field" in err.get("details", {})


def test_put_validation_unknown_field(client):
    resp = create_application(client, {"company": "Acme", "role": "Engineer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["data"]["id"]

    # Include an allowed field and an unknown one to trigger validation error
    resp2 = client.put(f"/applications/{new_id}", json={"company": "Acme 2", "bad_field": "x"})
    assert resp2.status_code == 400
    err = resp2.get_json()
    assert err["error"] == "Bad Request"
    assert "unknown" in err["details"]
    assert "bad_field" in err["details"]["unknown"]


def test_put_update_404_when_missing(client):
    resp = client.put("/applications/123456", json={"company": "X Corp"})
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"


def test_delete_success_and_404_after(client):
    resp = create_application(client, {"company": "Acme", "role": "Engineer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["data"]["id"]

    del_resp = client.delete(f"/applications/{new_id}")
    assert del_resp.status_code == 204
    assert del_resp.data == b""

    # Subsequent get should be 404
    resp2 = client.get(f"/applications/{new_id}")
    assert resp2.status_code == 404

    # Subsequent delete should be 404
    del_resp2 = client.delete(f"/applications/{new_id}")
    assert del_resp2.status_code == 404
    body = del_resp2.get_json()
    assert body["error"] == "Not Found"


def test_delete_404_when_missing(client):
    resp = client.delete("/applications/987654")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "Not Found"


def test_post_invalid_json_body_returns_400(client):
    resp = client.post("/applications", data="{bad json", content_type="application/json")
    assert resp.status_code == 400
    err = resp.get_json()
    assert err["error"] == "Bad Request"
    assert "json" in err["details"]


def test_put_invalid_json_body_returns_400(client):
    resp = create_application(client, {"company": "Acme", "role": "Engineer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["data"]["id"]

    resp2 = client.put(f"/applications/{new_id}", data="{bad json", content_type="application/json")
    assert resp2.status_code == 400
    err = resp2.get_json()
    assert err["error"] == "Bad Request"
    assert "json" in err["details"]