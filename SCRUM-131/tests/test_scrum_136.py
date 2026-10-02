import sqlite3
from datetime import datetime
from unittest import mock

import pytest

import scrum_136 as m


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_dateutil_is_valid_date():
    # Valid cases
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("2020-02-29") is True  # leap day
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("1999-12-31") is True

    # Invalid format
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("2020-2-2") is False
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("20-02-02") is False
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("abcd-ef-gh") is False
    assert m.DateUtil.is_valid_date_yyyy_mm_dd(20200202) is False  # non-string

    # Invalid calendar date
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("2019-02-29") is False
    assert m.DateUtil.is_valid_date_yyyy_mm_dd("2021-04-31") is False


def test_validate_create_success_trims_and_normalizes():
    payload = {
        "company": "  Acme Corp  ",
        "role": "  Engineer ",
        "status": "InTeRvIeWiNg",
        "applied_date": "2020-02-29",
        "notes": "  keep  ",
    }
    sanitized, errors = m.ApplicationValidator.validate_create(payload)
    assert errors == {}
    assert sanitized == {
        "company": "Acme Corp",
        "role": "Engineer",
        "status": "interviewing",
        "applied_date": "2020-02-29",
        "notes": "  keep  ",
    }


def test_validate_create_missing_required_and_unknown_and_type_errors():
    payload = {
        # "company" missing
        "role": 123,  # wrong type
        "status": "hired",  # invalid
        "applied_date": "2020-13-01",  # invalid
        "notes": [1, 2],  # wrong type
        "foo": "bar",  # unknown
    }
    sanitized, errors = m.ApplicationValidator.validate_create(payload)
    assert sanitized is None
    # Required company
    assert errors["company"] == "is required"
    # Role type error (not "is required" because we provided wrong type)
    assert errors["role"] == "must be a string"
    # Status invalid choice
    assert errors["status"].startswith("must be one of")
    # Applied date invalid format
    assert errors["applied_date"] == "must be a valid date in YYYY-MM-DD format"
    # Notes type error
    assert errors["notes"] == "must be a string or null"
    # Unknown fields captured
    assert errors["unknown"] == ["foo"]


def test_validate_update_empty_payload_error():
    sanitized, errors = m.ApplicationValidator.validate_update({})
    assert sanitized is None
    assert errors["non_field"] == "no updatable fields provided"


def test_validate_update_unknown_field_only():
    sanitized, errors = m.ApplicationValidator.validate_update({"bogus": 1})
    assert sanitized is None
    assert "unknown" in errors
    assert errors["unknown"] == ["bogus"]
    # Should not include non_field when unknown present
    assert "non_field" not in errors


def test_validate_update_partial_valid():
    sanitized, errors = m.ApplicationValidator.validate_update({"notes": None, "status": "Offer"})
    assert errors == {}
    assert sanitized == {"notes": None, "status": "offer"}


def test_validate_status_filter_cases():
    s, errors = m.ApplicationValidator.validate_status_filter(None)
    assert errors == {}
    assert s is None

    s, errors = m.ApplicationValidator.validate_status_filter(" Offer ")
    assert errors == {}
    assert s == "offer"

    s, errors = m.ApplicationValidator.validate_status_filter(123)  # type: ignore
    assert s is None
    assert errors["status"] == "must be a string"

    s, errors = m.ApplicationValidator.validate_status_filter("hired")
    assert s is None
    assert errors["status"].startswith("must be one of")


def test_repo_create_and_get_defaults(db_path):
    # Create minimal entity
    entity = m.ApplicationRepo.create({"company": "Acme", "role": "Dev"}, db_path=db_path)
    assert isinstance(entity["id"], int)
    assert entity["company"] == "Acme"
    assert entity["role"] == "Dev"
    assert entity["status"] == "applied"
    # Default applied_date should be today's UTC date in YYYY-MM-DD
    expected_date = datetime.utcnow().strftime("%Y-%m-%d")
    assert entity["applied_date"] == expected_date
    assert entity["notes"] is None

    # Fetch by id
    got = m.ApplicationRepo.get_by_id(entity["id"], db_path=db_path)
    assert got == entity


def test_repo_create_with_explicit_fields_and_list_filter(db_path):
    e1 = m.ApplicationRepo.create(
        {"company": "A", "role": "R1", "status": "interviewing", "applied_date": "2023-01-01", "notes": "n1"},
        db_path=db_path,
    )
    e2 = m.ApplicationRepo.create(
        {"company": "B", "role": "R2", "status": "offer", "applied_date": "2023-01-02", "notes": None},
        db_path=db_path,
    )
    e3 = m.ApplicationRepo.create({"company": "C", "role": "R3"}, db_path=db_path)

    all_items = m.ApplicationRepo.list_all(db_path=db_path)
    assert [i["id"] for i in all_items] == [e1["id"], e2["id"], e3["id"]]

    offers = m.ApplicationRepo.list_all(filter_status="offer", db_path=db_path)
    assert [i["id"] for i in offers] == [e2["id"]]


def test_repo_update_success_noop_and_not_found(db_path):
    e = m.ApplicationRepo.create({"company": "Acme", "role": "Dev"}, db_path=db_path)
    updated = m.ApplicationRepo.update(
        e["id"], {"role": "Senior Dev", "status": "interviewing", "notes": None}, db_path=db_path
    )
    assert updated is not None
    assert updated["role"] == "Senior Dev"
    assert updated["status"] == "interviewing"
    assert updated["notes"] is None

    # No-op update (empty data) returns current entity
    noop = m.ApplicationRepo.update(e["id"], {}, db_path=db_path)
    assert noop == updated

    # Not found update
    nf = m.ApplicationRepo.update(9999, {"role": "X"}, db_path=db_path)
    assert nf is None


def test_repo_delete(db_path):
    e1 = m.ApplicationRepo.create({"company": "A", "role": "R1"}, db_path=db_path)
    e2 = m.ApplicationRepo.create({"company": "B", "role": "R2"}, db_path=db_path)

    ok = m.ApplicationRepo.delete(e1["id"], db_path=db_path)
    assert ok is True
    assert m.ApplicationRepo.get_by_id(e1["id"], db_path=db_path) is None

    # Deleting again or non-existent
    ok2 = m.ApplicationRepo.delete(99999, db_path=db_path)
    assert ok2 is False

    remaining = m.ApplicationRepo.list_all(db_path=db_path)
    assert [i["id"] for i in remaining] == [e2["id"]]


def test_repo_constraints_raise_integrity_error(db_path):
    # Invalid status should violate CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        m.ApplicationRepo.create({"company": "A", "role": "R", "status": "invalid"}, db_path=db_path)

    # Empty company after trimming should violate CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        m.ApplicationRepo.create({"company": "   ", "role": "R"}, db_path=db_path)

    # Invalid applied_date pattern should violate CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        m.ApplicationRepo.create({"company": "A", "role": "R", "applied_date": "2020/01/01"}, db_path=db_path)


def test_controller_create_application_success_and_normalization(db_path):
    status_code, body = m.create_application(
        {"company": "  X  ", "role": " Y ", "status": "InTeRvIeWiNg", "applied_date": "2021-01-01"},
        db_path=db_path,
    )
    assert status_code == 201
    assert "data" in body
    data = body["data"]
    assert data["company"] == "X"
    assert data["role"] == "Y"
    assert data["status"] == "interviewing"
    assert data["applied_date"] == "2021-01-01"


def test_controller_create_application_validation_error(db_path):
    status_code, body = m.create_application({"role": ""}, db_path=db_path)
    assert status_code == 400
    assert body["error"] == "Bad Request"
    assert "details" in body
    assert "company" in body["details"]
    assert "role" in body["details"]


def test_controller_create_application_integrity_error_leakage(db_path, monkeypatch):
    def raise_integrity(_data, db_path=None):
        raise sqlite3.IntegrityError("CHECK constraint failed: applications")

    monkeypatch.setattr(m.ApplicationRepo, "create", raise_integrity)
    status_code, body = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    assert status_code == 400
    assert body["error"] == "Bad Request"
    assert "details" in body
    assert "db" in body["details"]
    # Ensure raw exception text is leaked (as per code review warning)
    assert body["details"]["db"].startswith("constraint violation:")
    assert "constraint" in body["details"]["db"].lower()


def test_controller_create_application_database_error(db_path, monkeypatch):
    def raise_db(_data, db_path=None):
        raise sqlite3.DatabaseError("db down")

    monkeypatch.setattr(m.ApplicationRepo, "create", raise_db)
    status_code, body = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    assert status_code == 500
    assert body["error"] == "Internal Server Error"
    assert "db down" in body["details"]["db"]


def test_controller_list_applications_and_filter_and_errors(db_path, monkeypatch):
    # Seed some data
    m.create_application({"company": "A", "role": "R1", "status": "applied"}, db_path=db_path)
    m.create_application({"company": "B", "role": "R2", "status": "offer"}, db_path=db_path)
    m.create_application({"company": "C", "role": "R3", "status": "interviewing"}, db_path=db_path)

    status, body = m.list_applications(db_path=db_path)
    assert status == 200
    assert len(body["data"]) == 3

    status, body = m.list_applications(status=" Offer ", db_path=db_path)
    assert status == 200
    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "offer"

    status, body = m.list_applications(status=123, db_path=db_path)  # type: ignore
    assert status == 400
    assert body["error"] == "Bad Request"

    with mock.patch.object(m.ApplicationRepo, "list_all", side_effect=sqlite3.DatabaseError("boom")):
        status, body = m.list_applications(db_path=db_path)
        assert status == 500
        assert body["error"] == "Internal Server Error"
        assert "boom" in body["details"]["db"]


def test_controller_get_application_found_not_found_and_db_error(db_path):
    # Not found case
    status, body = m.get_application(9999, db_path=db_path)
    assert status == 404
    assert body["error"] == "Not Found"

    # Create one and fetch
    status, body = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    app_id = body["data"]["id"]
    status, body = m.get_application(app_id, db_path=db_path)
    assert status == 200
    assert body["data"]["id"] == app_id

    # DB error case
    with mock.patch.object(m.ApplicationRepo, "get_by_id", side_effect=sqlite3.DatabaseError("fail")):
        status, body = m.get_application(app_id, db_path=db_path)
        assert status == 500
        assert body["error"] == "Internal Server Error"
        assert "fail" in body["details"]["db"]


def test_controller_update_application_flow(db_path, monkeypatch):
    # Create
    status, body = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    app_id = body["data"]["id"]

    # Validation error
    status, body = m.update_application(app_id, {}, db_path=db_path)
    assert status == 400
    assert body["error"] == "Bad Request"
    assert "non_field" in body["details"]

    # Not found
    status, body = m.update_application(9999, {"status": "offer"}, db_path=db_path)
    assert status == 404
    assert body["error"] == "Not Found"

    # Success with normalization
    status, body = m.update_application(app_id, {"status": "InTeRvIeWiNg"}, db_path=db_path)
    assert status == 200
    assert body["data"]["status"] == "interviewing"

    # Integrity error mapping
    def raise_integrity(_id, _data, db_path=None):
        raise sqlite3.IntegrityError("CHECK constraint failed: applications")

    monkeypatch.setattr(m.ApplicationRepo, "update", raise_integrity)
    status, body = m.update_application(app_id, {"status": "offer"}, db_path=db_path)
    assert status == 400
    assert body["error"] == "Bad Request"
    assert "constraint violation" in body["details"]["db"].lower()

    # Database error mapping
    def raise_db(_id, _data, db_path=None):
        raise sqlite3.DatabaseError("down")

    monkeypatch.setattr(m.ApplicationRepo, "update", raise_db)
    status, body = m.update_application(app_id, {"status": "offer"}, db_path=db_path)
    assert status == 500
    assert body["error"] == "Internal Server Error"
    assert "down" in body["details"]["db"]


def test_controller_delete_application_success_not_found_and_db_error(db_path):
    # Create
    status, body = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    app_id = body["data"]["id"]

    # Success
    status, body = m.delete_application(app_id, db_path=db_path)
    assert status == 204
    assert body is None

    # Not found
    status, body = m.delete_application(9999, db_path=db_path)
    assert status == 404
    assert body["error"] == "Not Found"

    # DB error
    with mock.patch.object(m.ApplicationRepo, "delete", side_effect=sqlite3.DatabaseError("oops")):
        status, body = m.delete_application(app_id, db_path=db_path)
        assert status == 500
        assert body["error"] == "Internal Server Error"
        assert "oops" in body["details"]["db"]