import sys
import types
import importlib
import uuid
import pytest
from flask import Flask


@pytest.fixture
def client(tmp_path):
    # Provide a config module with DB_PATH before importing routes
    db_file = tmp_path / "test.db"
    config_mod = types.ModuleType("config")
    config_mod.DB_PATH = str(db_file)
    sys.modules["config"] = config_mod

    # Ensure a clean import of the routes blueprint
    if "scrum_143_routes" in sys.modules:
        del sys.modules["scrum_143_routes"]

    app = Flask(__name__)
    routes = importlib.import_module("scrum_143_routes")
    app.register_blueprint(routes.bp)

    with app.test_client() as c:
        yield c


def create_app_via_http(client, company="Acme", role="Engineer", status=None, notes=None, applied_date=None):
    payload = {"company": company, "role": role}
    if status is not None:
        payload["status"] = status
    if notes is not None:
        payload["notes"] = notes
    if applied_date is not None:
        payload["applied_date"] = applied_date
    resp = client.post("/applications", json=payload)
    return resp


def test_post_create_application_success_and_schema_keys(client):
    resp = create_app_via_http(client, company="Acme Corp", role="Backend Dev")
    assert resp.status_code == 201
    data = resp.get_json()
    assert isinstance(data, dict)
    for key in ["id", "company", "role", "applied_date", "status", "notes"]:
        assert key in data
    assert data["company"] == "Acme Corp"
    assert data["role"] == "Backend Dev"
    assert data["status"] == "applied"
    assert data["id"]

    # Schema smoke test: GET list and ensure keys are present
    list_resp = client.get("/applications")
    assert list_resp.status_code == 200
    items = list_resp.get_json()
    assert isinstance(items, list)
    assert any(item["id"] == data["id"] for item in items)
    for item in items:
        for key in ["id", "company", "role", "applied_date", "status", "notes"]:
            assert key in item

    # GET single
    get_resp = client.get(f"/applications/{data['id']}")
    assert get_resp.status_code == 200
    single = get_resp.get_json()
    assert single["id"] == data["id"]
    assert single["company"] == "Acme Corp"
    assert single["role"] == "Backend Dev"
    assert single["status"] == "applied"


@pytest.mark.parametrize("missing_field,payload", [
    ("company", {"role": "Engineer"}),
    ("role", {"company": "Acme"}),
])
def test_post_validation_missing_required_fields(client, missing_field, payload):
    resp = client.post("/applications", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
    assert missing_field in data["error"].lower()


@pytest.mark.parametrize("status_value", ["Applied", "APPLIED", " applied ", "InTeRvIeWiNg", "OFFER", "rejected"])
def test_post_status_normalization_accepts_mixed_case(client, status_value):
    resp = create_app_via_http(client, company="StatCo", role="QA", status=status_value)
    assert resp.status_code == 201
    app_data = resp.get_json()
    assert app_data["status"] == status_value.strip().lower()


def test_post_invalid_status_rejected(client):
    resp = create_app_via_http(client, company="BadStat", role="QA", status="unknown")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
    assert "invalid status" in data["error"].lower()


def test_get_list_and_filter_by_status(client):
    # create multiple apps with various statuses
    r1 = create_app_via_http(client, company="A", role="R", status="Applied")
    r2 = create_app_via_http(client, company="B", role="R", status="Offer")
    r3 = create_app_via_http(client, company="C", role="R", status="INTERVIEWING")
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 201

    # list all
    resp_all = client.get("/applications")
    assert resp_all.status_code == 200
    items = resp_all.get_json()
    assert len(items) >= 3

    # filter by status (mixed case in query)
    resp_offer = client.get("/applications?status=Offer")
    assert resp_offer.status_code == 200
    offer_items = resp_offer.get_json()
    assert all(it["status"] == "offer" for it in offer_items)
    assert any(it["company"] == "B" for it in offer_items)


def test_get_single_not_found(client):
    fake_id = str(uuid.uuid4())
    resp = client.get(f"/applications/{fake_id}")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_put_update_success_and_status_normalization(client):
    # create
    create_resp = create_app_via_http(client, company="InitCo", role="Dev", status="applied", notes="orig")
    assert create_resp.status_code == 201
    app_data = create_resp.get_json()
    app_id = app_data["id"]

    # update with new values
    patch = {
        "company": "UpdatedCo",
        "role": "Senior Dev",
        "status": "REJECTED",
        "notes": "updated note",
    }
    put_resp = client.put(f"/applications/{app_id}", json=patch)
    assert put_resp.status_code == 200
    updated = put_resp.get_json()
    assert updated["id"] == app_id
    assert updated["company"] == "UpdatedCo"
    assert updated["role"] == "Senior Dev"
    assert updated["status"] == "rejected"
    assert updated["notes"] == "updated note"

    # verify via GET
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 200
    got = get_resp.get_json()
    assert got["company"] == "UpdatedCo"
    assert got["status"] == "rejected"


@pytest.mark.parametrize("field", ["company", "role"])
def test_put_validation_empty_required_fields_when_provided(client, field):
    # create baseline
    create_resp = create_app_via_http(client, company="KeepCo", role="KeepRole")
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # attempt to set required field to empty
    bad_patch = {field: "   "}
    put_resp = client.put(f"/applications/{app_id}", json=bad_patch)
    assert put_resp.status_code == 400
    data = put_resp.get_json()
    assert "error" in data
    assert field in data["error"].lower()


def test_put_not_found(client):
    fake_id = str(uuid.uuid4())
    resp = client.put(f"/applications/{fake_id}", json={"company": "X", "role": "Y"})
    assert resp.status_code == 404


def test_delete_success_and_not_found(client):
    # create
    create_resp = create_app_via_http(client, company="DelCo", role="Ops")
    assert create_resp.status_code == 201
    app_id = create_resp.get_json()["id"]

    # delete
    del_resp = client.delete(f"/applications/{app_id}")
    assert del_resp.status_code == 200
    del_data = del_resp.get_json()
    assert del_data.get("deleted") is True

    # ensure gone
    get_resp = client.get(f"/applications/{app_id}")
    assert get_resp.status_code == 404

    # delete again -> 404
    del_again = client.delete(f"/applications/{app_id}")
    assert del_again.status_code == 404


def test_grouped_by_status(client):
    # create apps across statuses
    r1 = create_app_via_http(client, company="G1", role="R", status="applied")
    r2 = create_app_via_http(client, company="G2", role="R", status="offer")
    r3 = create_app_via_http(client, company="G3", role="R", status="interviewing")
    r4 = create_app_via_http(client, company="G4", role="R", status="rejected")
    assert all(r.status_code == 201 for r in [r1, r2, r3, r4])

    grp_resp = client.get("/applications/grouped")
    assert grp_resp.status_code == 200
    groups = grp_resp.get_json()
    assert isinstance(groups, dict)
    for key in ["applied", "interviewing", "offer", "rejected"]:
        assert key in groups
        assert isinstance(groups[key], list)
    # basic sanity: at least one per status as created
    assert any(app["company"] == "G1" for app in groups["applied"])
    assert any(app["company"] == "G2" for app in groups["offer"])
    assert any(app["company"] == "G3" for app in groups["interviewing"])
    assert any(app["company"] == "G4" for app in groups["rejected"])