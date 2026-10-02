import sys
import types
import importlib
from flask import Flask
import pytest


@pytest.fixture
def client(tmp_path):
    # Prepare dynamic config module with DB_PATH pointing to temp sqlite file
    db_file = tmp_path / "test_applications.db"
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = str(db_file)
    sys.modules["config"] = config_mod

    # Ensure fresh import of routes to bind to this config
    sys.modules.pop("scrum_125_routes", None)
    routes = importlib.import_module("scrum_125_routes")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(routes.bp)
    return app.test_client()


def test_dashboard_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in (resp.headers.get("Content-Type") or "")
    assert b"Job Applications Dashboard" in resp.data


def test_statuses_endpoint(client):
    import scrum_125 as logic

    resp = client.get("/applications/statuses")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert "statuses" in data
    assert data["statuses"] == list(logic.get_statuses())


def test_grouped_initially_empty(client):
    import scrum_125 as logic

    resp = client.get("/applications/grouped")
    assert resp.status_code == 200
    grouped = resp.get_json()
    assert isinstance(grouped, dict)
    for s in logic.get_statuses():
        assert s in grouped
        assert grouped[s] == []


def test_crud_end_to_end_and_schema_smoke(client):
    # Initial list should be empty
    resp = client.get("/applications")
    assert resp.status_code == 200
    assert resp.get_json() == []

    # Create with mixed case status (should normalize) and explicit applied_date
    payload = {
        "company": "Acme",
        "role": "Engineer",
        "status": "Applied",
        "applied_date": "2023-01-02",
        "notes": "First entry",
    }
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 201
    created = resp.get_json()
    assert created["company"] == "Acme"
    assert created["role"] == "Engineer"
    assert created["status"] == "applied"  # normalized
    assert created["applied_date"] == "2023-01-02"
    assert created["notes"] == "First entry"
    app_id = created["id"]
    assert isinstance(app_id, str) and app_id

    # Schema smoke test: GET list and ensure all expected keys are present
    resp = client.get("/applications")
    assert resp.status_code == 200
    items = resp.get_json()
    assert isinstance(items, list)
    assert len(items) == 1
    got = items[0]
    expected_keys = {"id", "company", "role", "status", "applied_date", "notes"}
    assert set(got.keys()) == expected_keys

    # GET single
    resp = client.get(f"/applications/{app_id}")
    assert resp.status_code == 200
    single = resp.get_json()
    assert single["id"] == app_id

    # PUT update including mandatory fields and upper-case status (should normalize)
    patch = {
        "company": "Acme Corp",
        "role": "Senior Engineer",
        "status": "APPLIED",
        "applied_date": "2023-02-03",
        "notes": "Updated notes",
    }
    resp = client.put(f"/applications/{app_id}", json=patch)
    assert resp.status_code == 200
    updated = resp.get_json()
    assert updated["company"] == "Acme Corp"
    assert updated["role"] == "Senior Engineer"
    assert updated["status"] == "applied"
    assert updated["applied_date"] == "2023-02-03"
    assert updated["notes"] == "Updated notes"

    # Dedicated status route with mixed case; should normalize and move to interviewing
    resp = client.put(f"/applications/{app_id}/status", json={"status": "InTeRvIeWiNg"})
    assert resp.status_code == 200
    updated2 = resp.get_json()
    assert updated2["status"] == "interviewing"

    # Grouped should reflect the app in 'interviewing'
    resp = client.get("/applications/grouped")
    assert resp.status_code == 200
    grouped = resp.get_json()
    assert any(app["id"] == app_id for app in grouped["interviewing"])

    # DELETE
    resp = client.delete(f"/applications/{app_id}")
    assert resp.status_code == 200
    assert resp.get_json() == {"deleted": True}

    # GET single after delete should 404
    resp = client.get(f"/applications/{app_id}")
    assert resp.status_code == 404

    # List should be empty again
    resp = client.get("/applications")
    assert resp.status_code == 200
    assert resp.get_json() == []


@pytest.mark.parametrize(
    "missing_field, payload",
    [
        ("company", {"role": "Engineer", "status": "applied", "applied_date": "2023-01-01"}),
        ("role", {"company": "Acme", "status": "applied", "applied_date": "2023-01-01"}),
    ],
)
def test_validation_missing_required_fields_returns_422(client, missing_field, payload):
    resp = client.post("/applications", json=payload)
    # ValidationError in logic maps to 422 via error handler
    assert resp.status_code == 422
    data = resp.get_json()
    assert "error" in data
    assert missing_field in data["error"]


def test_status_normalization_accepts_mixed_case_on_post_and_put(client):
    # Create with uppercase status
    p = {
        "company": "Globex",
        "role": "Analyst",
        "status": "APPLIED",
        "applied_date": "2023-05-06",
        "notes": "",
    }
    resp = client.post("/applications", json=p)
    assert resp.status_code == 201
    created = resp.get_json()
    assert created["status"] == "applied"
    app_id = created["id"]

    # Update status via PUT with mixed case
    resp = client.put(f"/applications/{app_id}", json={"company": "Globex", "role": "Analyst", "status": "OfFeR", "applied_date": "2023-05-06"})
    assert resp.status_code == 200
    updated = resp.get_json()
    assert updated["status"] == "offer"

    # Update via dedicated status endpoint with mixed case
    resp = client.put(f"/applications/{app_id}/status", json={"status": "ReJeCtEd"})
    assert resp.status_code == 200
    updated2 = resp.get_json()
    assert updated2["status"] == "rejected"


def test_get_missing_returns_404(client):
    resp = client.get("/applications/nonexistent-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_delete_missing_returns_404(client):
    resp = client.delete("/applications/nonexistent-id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_put_missing_returns_404(client):
    # Providing required fields for update but with unknown id
    resp = client.put(
        "/applications/nonexistent-id",
        json={"company": "X", "role": "Y", "status": "applied", "applied_date": "2023-01-01"},
    )
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_request_body_must_be_json_errors(client):
    # POST with non-JSON
    resp = client.post("/applications", data="not json", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 400
    # PUT with non-JSON
    # First create a valid record
    create_resp = client.post(
        "/applications",
        json={"company": "Init", "role": "Tester", "status": "applied", "applied_date": "2023-01-01"},
    )
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    resp = client.put(f"/applications/{app_id}", data="not json", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 400

    # Status endpoint with wrong type
    resp = client.put(f"/applications/{app_id}/status", json={"status": 123})
    assert resp.status_code == 422