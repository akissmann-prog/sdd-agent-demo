import os
import pytest
from scrum_110 import (
    create_application,
    list_applications,
    get_application,
    update_application,
    delete_application,
    ValidationError,
    NotFoundError,
    today_utc_date,
)

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_create_with_defaults_uses_fixed_today(monkeypatch, db_path):
    fixed_today = "2024-05-01"
    monkeypatch.setattr("scrum_110.today_utc_date", lambda: fixed_today)
    rec = create_application({"company": "Acme Corp", "role": "Engineer"}, db_path=db_path)
    assert isinstance(rec["id"], int)
    assert rec["company"] == "Acme Corp"
    assert rec["role"] == "Engineer"
    assert rec["status"] == "applied"
    assert rec["applied_date"] == fixed_today
    assert rec["notes"] is None


def test_create_status_normalization_and_trim(db_path):
    rec = create_application(
        {"company": "Acme", "role": "Dev", "status": "  InTerViewIng  "},
        db_path=db_path,
    )
    assert rec["status"] == "interviewing"


def test_create_with_applied_date_datetime_string_truncated(db_path):
    # Current behavior: accepts ISO datetime and truncates to date
    rec = create_application(
        {"company": "Acme", "role": "Dev", "applied_date": "2023-05-03T10:20:30"},
        db_path=db_path,
    )
    assert rec["applied_date"] == "2023-05-03"


@pytest.mark.parametrize(
    "applied_date, expected_message_substr",
    [
        ("2023/05/01", "YYYY-MM-DD"),
        ("2023-13-01", "valid date"),
        ("2023-02-30", "valid date"),
        ("2023-05-01 10:20:30", "YYYY-MM-DD"),
    ],
)
def test_create_invalid_applied_date_formats(db_path, applied_date, expected_message_substr):
    with pytest.raises(ValidationError) as exc:
        create_application(
            {"company": "Acme", "role": "Dev", "applied_date": applied_date},
            db_path=db_path,
        )
    assert "applied_date" in str(exc.value)
    assert expected_message_substr in str(exc.value)
    assert exc.value.status_code == 400


def test_create_invalid_applied_date_type(db_path):
    with pytest.raises(ValidationError) as exc:
        create_application({"company": "Acme", "role": "Dev", "applied_date": 123}, db_path=db_path)
    assert "applied_date must be a string" in str(exc.value)
    assert exc.value.status_code == 400


def test_create_notes_validation_non_string(db_path):
    with pytest.raises(ValidationError) as exc:
        create_application({"company": "Acme", "role": "Dev", "notes": 123}, db_path=db_path)
    assert "notes must be a string or null" in str(exc.value)
    assert exc.value.status_code == 400


def test_create_company_role_validation_types_and_empty(db_path):
    with pytest.raises(ValidationError) as exc1:
        create_application({"company": 42, "role": "Dev"}, db_path=db_path)
    assert "company must be a string" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        create_application({"company": "Acme", "role": "   "}, db_path=db_path)
    assert "role is required and cannot be empty" in str(exc2.value)


def test_create_with_status_none_raises(db_path):
    with pytest.raises(ValidationError) as exc:
        create_application({"company": "Acme", "role": "Dev", "status": None}, db_path=db_path)
    assert "status must be a string" in str(exc.value)


def test_list_all_and_filter_with_status_normalization_and_order(db_path):
    a = create_application({"company": "A", "role": "R1", "status": "applied"}, db_path=db_path)
    b = create_application({"company": "B", "role": "R2", "status": "interviewing"}, db_path=db_path)
    c = create_application({"company": "C", "role": "R3", "status": "applied"}, db_path=db_path)

    all_recs = list_applications(db_path=db_path)
    assert [r["id"] for r in all_recs] == sorted([a["id"], b["id"], c["id"]])

    applied_recs = list_applications(status=" APPLIED ", db_path=db_path)
    assert len(applied_recs) == 2
    assert all(r["status"] == "applied" for r in applied_recs)

    with pytest.raises(ValidationError) as exc:
        list_applications(status="invalid", db_path=db_path)
    assert exc.value.status_code == 400


def test_get_by_id_found_and_notfound(db_path):
    rec = create_application({"company": "Acme", "role": "Dev"}, db_path=db_path)
    fetched = get_application(rec["id"], db_path=db_path)
    assert fetched["id"] == rec["id"]
    assert fetched["company"] == "Acme"

    with pytest.raises(NotFoundError) as exc_nf:
        get_application(9999, db_path=db_path)
    assert exc_nf.value.status_code == 404


@pytest.mark.parametrize("bad_id", ["1", 0, -1, 1.5])
def test_get_invalid_id_types_and_values(db_path, bad_id):
    with pytest.raises(ValidationError) as exc:
        get_application(bad_id, db_path=db_path)
    assert "id must be" in str(exc.value)


def test_update_partial_fields_and_notes_to_none(db_path):
    rec = create_application({"company": "Acme", "role": "Dev", "notes": "initial"}, db_path=db_path)
    updated = update_application(
        rec["id"],
        {"status": "interviewing", "notes": None},
        db_path=db_path,
    )
    assert updated["status"] == "interviewing"
    assert updated["notes"] is None
    assert updated["company"] == "Acme"
    assert updated["role"] == "Dev"


def test_update_with_datetime_applied_date_truncation(db_path):
    rec = create_application({"company": "Acme", "role": "Dev"}, db_path=db_path)
    updated = update_application(rec["id"], {"applied_date": "2023-01-01T00:00:00"}, db_path=db_path)
    assert updated["applied_date"] == "2023-01-01"


def test_update_with_invalid_payload_and_unknown_fields(db_path):
    rec = create_application({"company": "Acme", "role": "Dev"}, db_path=db_path)

    with pytest.raises(ValidationError) as exc1:
        update_application(rec["id"], {"status": "wrong"}, db_path=db_path)
    assert exc1.value.status_code == 400

    with pytest.raises(ValidationError) as exc2:
        update_application(rec["id"], {}, db_path=db_path)
    assert "at least one updatable field" in str(exc2.value)

    with pytest.raises(ValidationError) as exc3:
        update_application(rec["id"], {"foo": "bar"}, db_path=db_path)
    assert "at least one updatable field" in str(exc3.value)


def test_update_notfound(db_path):
    with pytest.raises(NotFoundError) as exc:
        update_application(9999, {"company": "X"}, db_path=db_path)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("bad_id", [0, -5, "3"])
def test_delete_invalid_id(db_path, bad_id):
    with pytest.raises(ValidationError) as exc:
        delete_application(bad_id, db_path=db_path)
    assert exc.value.status_code == 400


def test_delete_success_and_notfound(db_path):
    rec = create_application({"company": "Acme", "role": "Dev"}, db_path=db_path)
    all_recs = list_applications(db_path=db_path)
    assert len(all_recs) == 1

    delete_application(rec["id"], db_path=db_path)
    assert list_applications(db_path=db_path) == []

    with pytest.raises(NotFoundError):
        delete_application(rec["id"], db_path=db_path)


def test_list_on_empty_db_creates_schema_and_returns_empty(db_path):
    # No prior calls to create schema; list should return empty and not fail
    assert list_applications(db_path=db_path) == []