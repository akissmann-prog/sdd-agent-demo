import pytest
from datetime import date

import scrum_99 as m


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "app.db")


def test_create_application_minimal_defaults(db_path):
    app = m.create_application({"company": "Acme", "role": "Developer"}, db_path=db_path)
    assert isinstance(app["id"], int)
    assert app["company"] == "Acme"
    assert app["role"] == "Developer"
    assert app["status"] == "applied"
    assert app["applied_date"] == date.today().isoformat()
    assert app["notes"] is None

    # Persisted and retrievable
    fetched = m.get_application(app["id"], db_path=db_path)
    assert fetched == app


def test_create_application_with_all_fields_and_normalizations(db_path):
    payload = {
        "company": "  ACME  ",
        "role": "  Engineer ",
        "status": " Offer ",
        "applied_date": "2023-02-03",
        "notes": "",
    }
    app = m.create_application(payload, db_path=db_path)
    assert app["company"] == "ACME"
    assert app["role"] == "Engineer"
    assert app["status"] == "offer"
    assert app["applied_date"] == "2023-02-03"
    assert app["notes"] == ""


def test_create_application_invalid_types_non_mapping_payload(db_path):
    with pytest.raises(m.BadRequestError) as ei:
        m.create_application(["not", "a", "dict"], db_path=db_path)
    err = ei.value
    assert err.status_code == 400
    resp = err.to_error_response()
    assert resp["message"] == "Invalid input."
    assert any(d["field"] == "body" and d["error"] == "Must be a JSON object." for d in resp.get("details", []))


def test_create_application_validation_errors_aggregated(db_path):
    payload = {
        "company": "   ",
        "role": "",
        "status": "pending",
        "applied_date": "2023-02-30",
        "notes": 123,
    }
    with pytest.raises(m.BadRequestError) as ei:
        m.create_application(payload, db_path=db_path)
    err = ei.value
    assert err.status_code == 400
    details = err.details
    assert {d["field"] for d in details} == {"company", "role", "status", "applied_date", "notes"}
    # Check specific messages
    msgs = {d["field"]: d["error"] for d in details}
    assert msgs["company"] == "Must be a non-empty string."
    assert msgs["role"] == "Must be a non-empty string."
    assert "Must be one of" in msgs["status"]
    assert msgs["applied_date"] == "Must be a valid date in YYYY-MM-DD format."
    assert msgs["notes"] == "Must be a string or null."


def test_list_applications_no_filter_ordering(db_path):
    a1 = m.create_application(
        {"company": "C1", "role": "R1", "applied_date": "2024-05-01"},
        db_path=db_path,
    )
    a2 = m.create_application(
        {"company": "C2", "role": "R2", "applied_date": "2024-06-01"},
        db_path=db_path,
    )
    a3 = m.create_application(
        {"company": "C3", "role": "R3", "applied_date": "2024-06-01"},
        db_path=db_path,
    )

    listed = m.list_applications(db_path=db_path)
    # Expect order by applied_date DESC, then id DESC
    assert [x["id"] for x in listed] == [a3["id"], a2["id"], a1["id"]]
    assert [x["applied_date"] for x in listed] == ["2024-06-01", "2024-06-01", "2024-05-01"]


def test_list_applications_status_filter_and_invalid(db_path):
    a1 = m.create_application({"company": "A", "role": "r", "status": "applied"}, db_path=db_path)
    a2 = m.create_application({"company": "B", "role": "r", "status": "offer"}, db_path=db_path)
    a3 = m.create_application({"company": "C", "role": "r", "status": "Offer"}, db_path=db_path)

    offers = m.list_applications(status="Offer", db_path=db_path)
    assert {x["id"] for x in offers} == {a2["id"], a3["id"]}
    assert all(x["status"] == "offer" for x in offers)

    all_listed = m.list_applications(db_path=db_path)
    assert {x["id"] for x in all_listed} == {a1["id"], a2["id"], a3["id"]}

    with pytest.raises(m.BadRequestError) as ei:
        m.list_applications(status="pending", db_path=db_path)
    err = ei.value
    assert err.status_code == 400
    assert err.message == "Invalid status filter."
    assert any(d["field"] == "status" for d in err.details)


def test_get_application_found_and_not_found(db_path):
    app = m.create_application({"company": "Acme", "role": "Dev"}, db_path=db_path)
    fetched = m.get_application(app["id"], db_path=db_path)
    assert fetched == app

    with pytest.raises(m.NotFoundError) as ei:
        m.get_application(9999, db_path=db_path)
    err = ei.value
    assert err.status_code == 404
    assert err.message == "Application not found."
    assert err.details == []


def test_update_application_nonexistent_raises(db_path):
    with pytest.raises(m.NotFoundError):
        m.update_application(42, {"company": "X"}, db_path=db_path)


def test_update_application_non_mapping_raises(db_path):
    app = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    original = m.get_application(app["id"], db_path=db_path)
    with pytest.raises(m.BadRequestError) as ei:
        m.update_application(app["id"], ["not", "mapping"], db_path=db_path)
    err = ei.value
    assert err.status_code == 400
    assert any(d["field"] == "body" and d["error"] == "Must be a JSON object." for d in err.details)
    # Ensure nothing changed
    after = m.get_application(app["id"], db_path=db_path)
    assert after == original


def test_update_application_no_allowed_fields_returns_existing(db_path):
    app = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    updated = m.update_application(app["id"], {"ignored": "value"}, db_path=db_path)
    assert updated == app


def test_update_application_success_partial_and_full(db_path):
    app = m.create_application(
        {"company": "OldCo", "role": "OldRole", "status": "applied", "applied_date": "2024-01-01", "notes": "n"},
        db_path=db_path,
    )

    # Partial update: set notes to None
    upd1 = m.update_application(app["id"], {"notes": None}, db_path=db_path)
    assert upd1["notes"] is None
    assert upd1["company"] == "OldCo"
    assert upd1["role"] == "OldRole"
    assert upd1["status"] == "applied"
    assert upd1["applied_date"] == "2024-01-01"

    # Full update with normalization
    upd2 = m.update_application(
        app["id"],
        {
            "company": "  New Co ",
            "role": " New Role ",
            "status": "REJECTED ",
            "applied_date": "2024-01-15",
            "notes": "hello",
        },
        db_path=db_path,
    )
    assert upd2["company"] == "New Co"
    assert upd2["role"] == "New Role"
    assert upd2["status"] == "rejected"
    assert upd2["applied_date"] == "2024-01-15"
    assert upd2["notes"] == "hello"

    # Persisted state matches
    fetched = m.get_application(app["id"], db_path=db_path)
    assert fetched == upd2


def test_update_application_validation_errors_and_no_change(db_path):
    app = m.create_application(
        {"company": "Co", "role": "Role", "status": "applied", "applied_date": "2024-04-04", "notes": "x"},
        db_path=db_path,
    )
    original = m.get_application(app["id"], db_path=db_path)

    with pytest.raises(m.BadRequestError) as ei:
        m.update_application(
            app["id"],
            {"company": "", "applied_date": "notadate", "status": "pend", "notes": 0},
            db_path=db_path,
        )
    err = ei.value
    assert err.status_code == 400
    details = {d["field"]: d["error"] for d in err.details}
    assert details["company"] == "Must be a non-empty string."
    assert "Must be one of" in details["status"]
    assert details["applied_date"] == "Must be a valid date in YYYY-MM-DD format."
    assert details["notes"] == "Must be a string or null."

    # Ensure unchanged
    after = m.get_application(app["id"], db_path=db_path)
    assert after == original


def test_delete_application_success_and_not_found(db_path):
    app = m.create_application({"company": "Acme", "role": "Dev"}, db_path=db_path)
    # Delete existing
    result = m.delete_application(app["id"], db_path=db_path)
    assert result is None
    # Now getting should raise NotFound
    with pytest.raises(m.NotFoundError):
        m.get_application(app["id"], db_path=db_path)
    # Deleting again raises NotFound
    with pytest.raises(m.NotFoundError):
        m.delete_application(app["id"], db_path=db_path)