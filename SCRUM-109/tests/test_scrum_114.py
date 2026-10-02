import os
import re
import sqlite3
import time
from datetime import date

import pytest

import scrum_114 as m


def make_db_path(tmp_path, name="test.db"):
    return str(tmp_path / name)


def test_get_allowed_statuses_contents():
    statuses = m.get_allowed_statuses()
    assert isinstance(statuses, tuple)
    assert set(statuses) == {"applied", "interviewing", "offer", "rejected"}


def test_get_applications_empty_returns_empty_list(tmp_path):
    db = make_db_path(tmp_path)
    apps = m.get_applications(db_path=db)
    assert apps == []


def test_create_application_defaults_and_iso_fields(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "Acme", "role": "Engineer"}, db_path=db)
    assert app["company"] == "Acme"
    assert app["role"] == "Engineer"
    assert app["status"] == "applied"
    assert app["applied_date"] == date.today().isoformat()
    assert app["notes"] is None
    # ISO 8601 with Z and created_at == updated_at at creation
    assert isinstance(app["created_at"], str)
    assert isinstance(app["updated_at"], str)
    assert app["created_at"].endswith("Z")
    assert app["updated_at"].endswith("Z")
    assert app["created_at"] == app["updated_at"]


def test_create_application_with_status_and_applied_date_and_notes(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application(
        {
            "company": "Beta",
            "role": "Analyst",
            "status": " INTERVIEWING ",
            "applied_date": " 2024-01-02 ",
            "notes": "Initial screen",
        },
        db_path=db,
    )
    assert app["status"] == "interviewing"
    assert app["applied_date"] == "2024-01-02"
    assert app["notes"] == "Initial screen"


def test_create_application_validation_errors(tmp_path):
    db = make_db_path(tmp_path)
    too_long_notes = "x" * (m.MAX_NOTES_LEN + 1)
    with pytest.raises(m.ValidationError) as ei:
        m.create_application(
            {
                "company": "C",
                "role": "R",
                "status": "unknown",
                "applied_date": "2020/01/01",
                "notes": too_long_notes,
            },
            db_path=db,
        )
    err = ei.value
    assert "status" in err.field_errors
    assert "applied_date" in err.field_errors
    assert "notes" in err.field_errors
    assert "must be one of" in err.field_errors["status"]
    assert "YYYY-MM-DD" in err.field_errors["applied_date"]
    assert "at most" in err.field_errors["notes"]


def test_create_application_missing_company_and_role(tmp_path):
    db = make_db_path(tmp_path)
    with pytest.raises(m.ValidationError) as ei:
        m.create_application({}, db_path=db)
    fe = ei.value.field_errors
    assert fe.get("company") == "Company is required"
    assert fe.get("role") == "Role is required"


def test_get_application_by_id_and_ordering(tmp_path):
    db = make_db_path(tmp_path)
    # Insert three apps with different dates; two share same date to test id DESC tie-breaker
    a1 = m.create_application({"company": "A", "role": "R1", "applied_date": "2023-01-01"}, db_path=db)
    a2 = m.create_application({"company": "B", "role": "R2", "applied_date": "2024-01-01"}, db_path=db)
    a3 = m.create_application({"company": "C", "role": "R3", "applied_date": "2024-01-01"}, db_path=db)

    # Fetch by id works
    got = m.get_application_by_id(a2["id"], db_path=db)
    assert got["company"] == "B"

    # Ordering: applied_date DESC then id DESC
    apps = m.get_applications(db_path=db)
    assert [x["id"] for x in apps] == [a3["id"], a2["id"], a1["id"]]


def test_group_applications_by_status_returns_all_keys_and_sorted(tmp_path):
    db = make_db_path(tmp_path)
    # Create across statuses
    a1 = m.create_application({"company": "A", "role": "R", "status": "applied", "applied_date": "2024-01-01"}, db_path=db)
    a2 = m.create_application({"company": "B", "role": "R", "status": "offer", "applied_date": "2024-01-03"}, db_path=db)
    a3 = m.create_application({"company": "C", "role": "R", "status": "offer", "applied_date": "2024-01-02"}, db_path=db)
    a4 = m.create_application({"company": "D", "role": "R", "status": "rejected", "applied_date": "2023-12-31"}, db_path=db)

    grouped = m.group_applications_by_status(db_path=db)
    # All allowed statuses as keys
    assert set(grouped.keys()) == set(m.ALLOWED_STATUSES)

    # Counts per status
    assert grouped["applied"] and grouped["applied"][0]["id"] == a1["id"]
    assert [x["id"] for x in grouped["offer"]] == [a2["id"], a3["id"]]
    assert grouped["rejected"] and grouped["rejected"][0]["id"] == a4["id"]
    # interviewing empty as none created
    assert grouped["interviewing"] == []


def test_group_applications_by_status_fallback_on_unknown_status(monkeypatch):
    # Monkeypatch get_applications to return an unknown status
    fake_apps = [
        {
            "id": 1,
            "company": "X",
            "role": "R",
            "status": "applied",
            "applied_date": "2024-01-01",
            "notes": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        },
        {
            "id": 2,
            "company": "Y",
            "role": "R",
            "status": "obsolete",
            "applied_date": "2024-01-02",
            "notes": None,
            "created_at": "2024-01-02T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        },
    ]
    monkeypatch.setattr(m, "get_applications", lambda db_path=m.DEFAULT_DB_PATH: fake_apps)
    grouped = m.group_applications_by_status()
    # Unknown status should be grouped under 'applied' fallback
    assert any(app["id"] == 1 for app in grouped["applied"])
    assert any(app["id"] == 2 for app in grouped["applied"])


def test_update_application_partial_and_updated_at_changes(tmp_path, monkeypatch):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "Acme", "role": "Engineer", "notes": "old"}, db_path=db)
    old_updated_at = app["updated_at"]

    monkeypatch.setattr(m, "_now_iso", lambda: "2099-01-01T00:00:00Z")
    updated = m.update_application(app["id"], {"notes": "new"}, db_path=db)
    assert updated["notes"] == "new"
    assert updated["created_at"] == app["created_at"]
    assert updated["updated_at"] == "2099-01-01T00:00:00Z"
    assert updated["updated_at"] != old_updated_at


def test_update_application_validation_errors(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R"}, db_path=db)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application(
            app["id"],
            {"company": " ", "role": "", "status": "bad", "applied_date": "2020/13/40"},
            db_path=db,
        )
    fe = ei.value.field_errors
    assert fe["company"] == "Company is required"
    assert fe["role"] == "Role is required"
    assert "must be one of" in fe["status"]
    assert "YYYY-MM-DD" in fe["applied_date"]


def test_update_application_applied_date_required_when_present(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R"}, db_path=db)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application(app["id"], {"applied_date": ""}, db_path=db)
    assert ei.value.field_errors["applied_date"] == "applied_date is required"

    with pytest.raises(m.ValidationError) as ei2:
        m.update_application(app["id"], {"applied_date": None}, db_path=db)
    assert ei2.value.field_errors["applied_date"] == "applied_date is required"


def test_update_application_no_valid_fields(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R"}, db_path=db)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application(app["id"], {}, db_path=db)
    assert "No valid fields to update" in str(ei.value)


def test_update_application_nonexistent_id_raises_not_found(tmp_path):
    db = make_db_path(tmp_path)
    # Ensures the critical review point: updating non-existent id yields NotFoundError
    with pytest.raises(m.NotFoundError):
        m.update_application(999999, {"company": "X"}, db_path=db)


def test_update_application_non_int_id_validation(tmp_path):
    db = make_db_path(tmp_path)
    m.create_application({"company": "C", "role": "R"}, db_path=db)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application("1", {"company": "X"}, db_path=db)  # type: ignore
    assert ei.value.field_errors.get("id") == "id must be an integer"


def test_delete_application_and_not_found(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R"}, db_path=db)
    # Delete successfully
    m.delete_application(app["id"], db_path=db)
    # Fetching after delete should raise not found
    with pytest.raises(m.NotFoundError):
        m.get_application_by_id(app["id"], db_path=db)
    # Deleting again should raise not found
    with pytest.raises(m.NotFoundError):
        m.delete_application(app["id"], db_path=db)


def test_delete_application_non_int_id_validation(tmp_path):
    db = make_db_path(tmp_path)
    m.create_application({"company": "C", "role": "R"}, db_path=db)
    with pytest.raises(m.ValidationError) as ei:
        m.delete_application("1", db_path=db)  # type: ignore
    assert ei.value.field_errors.get("id") == "id must be an integer"


def test_change_application_status(tmp_path, monkeypatch):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R"}, db_path=db)
    old_updated_at = app["updated_at"]
    monkeypatch.setattr(m, "_now_iso", lambda: "2100-01-01T00:00:00Z")
    updated = m.change_application_status(app["id"], "offer", db_path=db)
    assert updated["status"] == "offer"
    assert updated["updated_at"] == "2100-01-01T00:00:00Z"
    assert updated["created_at"] == app["created_at"]
    assert updated["updated_at"] != old_updated_at


def test_notes_length_boundaries_on_create_and_update(tmp_path):
    db = make_db_path(tmp_path)
    # Create with max length notes is allowed
    notes = "n" * m.MAX_NOTES_LEN
    app = m.create_application({"company": "C", "role": "R", "notes": notes}, db_path=db)
    assert app["notes"] == notes

    # Update exceeding max should error
    too_long = "n" * (m.MAX_NOTES_LEN + 1)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application(app["id"], {"notes": too_long}, db_path=db)
    assert "at most" in ei.value.field_errors["notes"]


def test_update_notes_can_be_cleared_to_none_or_empty_string(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R", "notes": "some"}, db_path=db)

    # Clear to None
    updated = m.update_application(app["id"], {"notes": None}, db_path=db)
    assert updated["notes"] is None

    # Set to empty string allowed
    updated2 = m.update_application(app["id"], {"notes": ""}, db_path=db)
    assert updated2["notes"] == ""


def test_update_applied_date_with_whitespace_parsed(tmp_path):
    db = make_db_path(tmp_path)
    app = m.create_application({"company": "C", "role": "R"}, db_path=db)
    updated = m.update_application(app["id"], {"applied_date": " 2024-02-02 "}, db_path=db)
    assert updated["applied_date"] == "2024-02-02"