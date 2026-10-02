import sqlite3
from datetime import datetime

import pytest

import scrum_136 as mod


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "test_applications.sqlite")


def test_dateutil_validation_valid_and_invalid():
    # Valid dates
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd("2024-02-29") is True  # leap year
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd("1999-12-31") is True

    # Invalid dates and formats
    for val in [
        "2023-02-29",  # not leap year
        "2024-13-01",  # invalid month
        "2024-00-10",  # invalid month
        "2024-12-32",  # invalid day
        "abcd-ef-gh",  # letters
        "2024-2-2",    # wrong format
        "",            # empty
    ]:
        assert mod.DateUtil.is_valid_date_yyyy_mm_dd(val) is False

    # Non-string types
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd(None) is False
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd(123) is False
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd(["2024-01-01"]) is False


def test_validate_create_success_and_trim_and_normalize():
    payload = {
        "company": " ACME Corp ",
        "role": " Senior Dev ",
        "status": " OFFER ",
        "applied_date": "2024-01-02",
        "notes": "  keep  ",
    }
    sanitized, errors = mod.ApplicationValidator.validate_create(payload)
    assert errors == {}
    assert sanitized == {
        "company": "ACME Corp",
        "role": "Senior Dev",
        "status": "offer",
        "applied_date": "2024-01-02",
        "notes": "  keep  ",
    }


def test_validate_create_errors_with_unknown_and_required():
    payload = {
        "company": "   ",  # invalid empty after trim
        # role missing -> required
        "notes": 99,  # invalid type
        "foo": "bar",  # unknown
    }
    sanitized, errors = mod.ApplicationValidator.validate_create(payload)
    assert sanitized is None
    assert "company" in errors and "non-empty" in errors["company"]
    assert "role" in errors and errors["role"] == "is required"
    assert "notes" in errors and "string or null" in errors["notes"]
    assert "unknown" in errors and errors["unknown"] == ["foo"]


def test_validate_update_behavior_patch_like():
    # Empty payload -> non_field error
    sanitized, errors = mod.ApplicationValidator.validate_update({})
    assert sanitized is None
    assert "non_field" in errors and "no updatable fields" in errors["non_field"]

    # Partial update allowed and normalized
    sanitized, errors = mod.ApplicationValidator.validate_update({"status": " Interviewing "})
    assert errors == {}
    assert sanitized == {"status": "interviewing"}

    # Unknown field on update -> unknown error only (no non_field)
    sanitized, errors = mod.ApplicationValidator.validate_update({"foo": "bar"})
    assert sanitized is None
    assert "unknown" in errors and errors["unknown"] == ["foo"]
    assert "non_field" not in errors

    # Notes can be set to None
    sanitized, errors = mod.ApplicationValidator.validate_update({"notes": None})
    assert errors == {}
    assert sanitized == {"notes": None}


def test_status_filter_validation():
    s, errors = mod.ApplicationValidator.validate_status_filter(None)
    assert s is None and errors == {}

    s, errors = mod.ApplicationValidator.validate_status_filter(" APPLIED ")
    assert s == "applied" and errors == {}

    s, errors = mod.ApplicationValidator.validate_status_filter(123)
    assert s is None and "status" in errors

    s, errors = mod.ApplicationValidator.validate_status_filter("hired")
    assert s is None and "status" in errors


def test_repo_create_minimal_defaults(db_file):
    rec = mod.ApplicationRepo.create({"company": "ACME", "role": "Engineer"}, db_path=db_file)
    assert isinstance(rec["id"], int) and rec["id"] >= 1
    assert rec["company"] == "ACME"
    assert rec["role"] == "Engineer"
    assert rec["status"] == "applied"
    assert isinstance(rec["applied_date"], str) and len(rec["applied_date"]) == 10
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd(rec["applied_date"])
    assert rec["notes"] is None


def test_repo_list_filter_and_order(db_file):
    a1 = mod.ApplicationRepo.create({"company": "A", "role": "R1", "status": "applied"}, db_path=db_file)
    a2 = mod.ApplicationRepo.create({"company": "B", "role": "R2", "status": "offer"}, db_path=db_file)
    a3 = mod.ApplicationRepo.create({"company": "C", "role": "R3", "status": "applied"}, db_path=db_file)

    all_items = mod.ApplicationRepo.list_all(db_path=db_file)
    assert [i["id"] for i in all_items] == sorted([a1["id"], a2["id"], a3["id"]])

    applied = mod.ApplicationRepo.list_all(filter_status="applied", db_path=db_file)
    assert [i["id"] for i in applied] == [a1["id"], a3["id"]]
    assert all(i["status"] == "applied" for i in applied)


def test_repo_get_update_delete(db_file):
    created = mod.ApplicationRepo.create(
        {"company": "ACME", "role": "Engineer", "status": "applied", "notes": "n"},
        db_path=db_file,
    )

    fetched = mod.ApplicationRepo.get_by_id(created["id"], db_path=db_file)
    assert fetched == created

    updated = mod.ApplicationRepo.update(
        created["id"],
        {"role": "Senior Engineer", "status": "interviewing", "applied_date": "2024-03-10", "notes": None},
        db_path=db_file,
    )
    assert updated is not None
    assert updated["role"] == "Senior Engineer"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2024-03-10"
    assert updated["notes"] is None

    not_found = mod.ApplicationRepo.update(9999, {"company": "X"}, db_path=db_file)
    assert not_found is None

    assert mod.ApplicationRepo.delete(created["id"], db_path=db_file) is True
    assert mod.ApplicationRepo.get_by_id(created["id"], db_path=db_file) is None
    assert mod.ApplicationRepo.delete(created["id"], db_path=db_file) is False


def test_repo_update_no_fields_returns_current_entity(db_file):
    rec = mod.ApplicationRepo.create({"company": "ACME", "role": "Eng"}, db_path=db_file)
    no_change = mod.ApplicationRepo.update(rec["id"], {}, db_path=db_file)
    assert no_change == rec


def test_repo_constraints_enforced_and_glob_date_check(db_file):
    # Status must be one of allowed; direct repo call with uppercase should fail DB CHECK
    with pytest.raises(sqlite3.IntegrityError):
        mod.ApplicationRepo.create({"company": "ACME", "role": "Eng", "status": "Offer"}, db_path=db_file)

    # applied_date DB CHECK uses pattern only; invalid calendar date still accepted at repo level
    rec = mod.ApplicationRepo.create(
        {"company": "ACME", "role": "Eng", "applied_date": "2023-02-29"},
        db_path=db_file,
    )
    assert rec["applied_date"] == "2023-02-29"


def test_controller_create_get_list_delete_flow(db_file):
    status, body = mod.create_application(
        {"company": " ACME ", "role": " Dev ", "status": " INTERVIEWING ", "notes": "n1"},
        db_path=db_file,
    )
    assert status == 201
    app1 = body["data"]
    assert app1["company"] == "ACME"
    assert app1["role"] == "Dev"
    assert app1["status"] == "interviewing"
    assert app1["notes"] == "n1"
    assert mod.DateUtil.is_valid_date_yyyy_mm_dd(app1["applied_date"])

    status, body = mod.create_application({"company": "Beta", "role": "DevOps"}, db_path=db_file)
    assert status == 201
    app2 = body["data"]
    assert app2["status"] == "applied"

    status, body = mod.list_applications(db_path=db_file)
    assert status == 200 and len(body["data"]) == 2

    status, body = mod.list_applications(" APPLIED ", db_path=db_file)
    assert status == 200
    ids = [i["id"] for i in body["data"]]
    assert app2["id"] in ids and app1["id"] not in ids

    status, body = mod.get_application(app1["id"], db_path=db_file)
    assert status == 200 and body["data"]["id"] == app1["id"]

    status, body = mod.get_application(9999, db_path=db_file)
    assert status == 404 and body["error"] == "Not Found"

    status, body = mod.delete_application(app1["id"], db_path=db_file)
    assert status == 204 and body is None

    status, body = mod.delete_application(app1["id"], db_path=db_file)
    assert status == 404 and body["error"] == "Not Found"


def test_controller_create_validation_errors(db_file):
    status, body = mod.create_application({"company": " ", "notes": 123, "foo": "bar"}, db_path=db_file)
    assert status == 400
    assert body["error"] == "Bad Request"
    details = body["details"]
    assert "company" in details
    assert "role" in details and details["role"] == "is required"
    assert "notes" in details
    assert "unknown" in details and details["unknown"] == ["foo"]


def test_controller_update_patch_like_and_errors(db_file):
    # Create initial
    status, body = mod.create_application({"company": "ACME", "role": "Eng"}, db_path=db_file)
    assert status == 201
    app = body["data"]

    # Partial update allowed (PATCH-like behavior)
    status, body = mod.update_application(app["id"], {"status": " OFFER "}, db_path=db_file)
    assert status == 200
    assert body["data"]["status"] == "offer"

    # Empty payload -> 400 non_field
    status, body = mod.update_application(app["id"], {}, db_path=db_file)
    assert status == 400 and "non_field" in body["details"]

    # Invalid date
    status, body = mod.update_application(app["id"], {"applied_date": "2024-02-30"}, db_path=db_file)
    assert status == 400 and "applied_date" in body["details"]

    # Non-existent id
    status, body = mod.update_application(9999, {"status": "applied"}, db_path=db_file)
    assert status == 404 and body["error"] == "Not Found"

    # notes set to None
    status, body = mod.update_application(app["id"], {"notes": None}, db_path=db_file)
    assert status == 200 and body["data"]["notes"] is None


def test_controller_integrity_error_leak_on_create(monkeypatch, db_file):
    def boom(*args, **kwargs):
        raise sqlite3.IntegrityError("CHECK constraint failed: applications.status")

    monkeypatch.setattr(mod.ApplicationRepo, "create", boom)
    status, body = mod.create_application({"company": "ACME", "role": "Eng"}, db_path=db_file)
    assert status == 400
    assert "constraint violation:" in body["details"]["db"]
    assert "CHECK constraint failed" in body["details"]["db"]


def test_controller_integrity_error_leak_on_update(monkeypatch, db_file):
    def boom(*args, **kwargs):
        raise sqlite3.IntegrityError("unique failed: applications.id")

    monkeypatch.setattr(mod.ApplicationRepo, "update", boom)
    status, body = mod.update_application(1, {"status": "applied"}, db_path=db_file)
    assert status == 400
    assert "constraint violation:" in body["details"]["db"]
    assert "unique failed" in body["details"]["db"]


def test_controller_database_error_handling(monkeypatch, db_file):
    # create_application
    def create_boom(*args, **kwargs):
        raise sqlite3.DatabaseError("db down")

    monkeypatch.setattr(mod.ApplicationRepo, "create", create_boom)
    status, body = mod.create_application({"company": "ACME", "role": "Eng"}, db_path=db_file)
    assert status == 500 and body["details"]["db"] == "db down"

    # list_applications
    def list_boom(*args, **kwargs):
        raise sqlite3.DatabaseError("cant list")

    monkeypatch.setattr(mod.ApplicationRepo, "list_all", list_boom)
    status, body = mod.list_applications(db_path=db_file)
    assert status == 500 and body["details"]["db"] == "cant list"

    # get_application
    def get_boom(*args, **kwargs):
        raise sqlite3.DatabaseError("cant get")

    monkeypatch.setattr(mod.ApplicationRepo, "get_by_id", get_boom)
    status, body = mod.get_application(1, db_path=db_file)
    assert status == 500 and body["details"]["db"] == "cant get"

    # update_application
    def update_boom(*args, **kwargs):
        raise sqlite3.DatabaseError("cant update")

    monkeypatch.setattr(mod.ApplicationRepo, "update", update_boom)
    status, body = mod.update_application(1, {"company": "X"}, db_path=db_file)
    assert status == 500 and body["details"]["db"] == "cant update"

    # delete_application
    def delete_boom(*args, **kwargs):
        raise sqlite3.DatabaseError("cant delete")

    monkeypatch.setattr(mod.ApplicationRepo, "delete", delete_boom)
    status, body = mod.delete_application(1, db_path=db_file)
    assert status == 500 and body["details"]["db"] == "cant delete"