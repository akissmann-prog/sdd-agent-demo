import sqlite3
import pytest
from scrum_103 import (
    Application,
    STATUS_APPLIED,
    STATUS_INTERVIEWING,
    STATUS_OFFER,
    STATUS_REJECTED,
    AppError,
    ValidationError,
    NotFoundError,
    sanitize_text,
    validate_status,
    validate_application_fields,
    add_application,
    get_application,
    list_applications,
    update_application,
    set_application_status,
    delete_application,
    group_applications_by_status,
    bulk_insert_applications,
    error_to_message,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_sanitize_text():
    assert sanitize_text(None) is None
    assert sanitize_text("   ") is None
    assert sanitize_text("  abc  ") == "abc"


def test_validate_status_normalization_and_validation():
    assert validate_status(" Applied ") == STATUS_APPLIED
    assert validate_status("INTERVIEWING") == STATUS_INTERVIEWING
    with pytest.raises(ValidationError) as exc:
        validate_status("unknown")
    assert "Invalid status" in str(exc.value)


def test_validate_application_fields_creation_requirements():
    # Missing company
    with pytest.raises(ValidationError) as exc:
        validate_application_fields(company=None, role="Dev", status=None, applied_date=None, for_update=False)
    assert "Company is required" in str(exc.value)

    # Missing role
    with pytest.raises(ValidationError) as exc:
        validate_application_fields(company="Acme", role=None, status=None, applied_date=None, for_update=False)
    assert "Role is required" in str(exc.value)

    # Invalid applied_date
    with pytest.raises(ValidationError) as exc:
        validate_application_fields(company="Acme", role="Dev", status=None, applied_date="2024-13-01", for_update=False)
    assert "YYYY-MM-DD" in str(exc.value)


def test_validate_application_fields_update_rules():
    # Omitting fields in update is allowed
    s_company, s_role, s_status, s_date = validate_application_fields(
        company=None, role=None, status=None, applied_date=None, for_update=True
    )
    assert (s_company, s_role, s_status, s_date) == (None, None, None, None)

    # Providing empty company should error
    with pytest.raises(ValidationError) as exc:
        validate_application_fields(company="   ", role=None, status=None, applied_date=None, for_update=True)
    assert "Company cannot be empty" in str(exc.value)

    # Providing empty role should error
    with pytest.raises(ValidationError) as exc:
        validate_application_fields(company=None, role="   ", status=None, applied_date=None, for_update=True)
    assert "Role cannot be empty" in str(exc.value)


def test_add_and_get_application_with_defaults(db_path, monkeypatch):
    monkeypatch.setattr("scrum_103.today_iso", lambda: "2024-01-02")
    app = add_application(company="Acme", role="Dev", db_path=db_path)
    assert isinstance(app, Application)
    assert app.company == "Acme"
    assert app.role == "Dev"
    assert app.status == STATUS_APPLIED
    assert app.applied_date == "2024-01-02"
    assert app.notes is None

    fetched = get_application(app.id, db_path=db_path)
    assert fetched == app


def test_add_application_with_invalid_date_raises(db_path):
    with pytest.raises(ValidationError) as exc:
        add_application(company="Acme", role="Dev", applied_date="2024-13-01", db_path=db_path)
    assert "YYYY-MM-DD" in str(exc.value)


def test_list_applications_ordering_and_whitelist(db_path):
    # Insert three applications with controlled dates
    a = add_application(company="B", role="R", status="applied", applied_date="2024-01-02", db_path=db_path)
    b = add_application(company="A", role="R", status="offer", applied_date="2024-01-01", db_path=db_path)
    c = add_application(company="C", role="R", status="applied", applied_date="2024-01-02", db_path=db_path)

    # Default ordering: applied_date DESC, tie-breaker id DESC
    results = list_applications(db_path=db_path)
    assert [r.id for r in results] == [c.id, a.id, b.id]

    # Invalid order_by should fall back to default and not error
    results_bogus = list_applications(db_path=db_path, order_by="company; DROP TABLE applications")
    assert [r.id for r in results_bogus] == [c.id, a.id, b.id]

    # Order by company ascending
    results_company_asc = list_applications(db_path=db_path, order_by="company", descending=False)
    assert [r.company for r in results_company_asc] == ["A", "B", "C"]


def test_list_applications_order_by_created_updated_columns(db_path):
    # Ensure no error when ordering by created_at or updated_at
    a = add_application(company="X", role="R", applied_date="2024-01-01", db_path=db_path)
    b = add_application(company="Y", role="R", applied_date="2024-01-02", db_path=db_path)

    res_created = list_applications(db_path=db_path, order_by="created_at", descending=True)
    assert len(res_created) == 2

    res_updated = list_applications(db_path=db_path, order_by="updated_at", descending=True)
    assert len(res_updated) == 2

    # Ensure IDs are in expected order by default tiebreaker behavior (id desc)
    assert res_created[0].id == b.id
    assert res_updated[0].id == b.id


def test_update_application_partial_and_clear_notes(db_path):
    app = add_application(company="Acme", role="Dev", notes=" initial note ", applied_date="2024-01-01", db_path=db_path)

    # Update role only (trimmed)
    updated = update_application(app.id, role=" Senior Dev ", db_path=db_path)
    assert updated.role == "Senior Dev"
    assert updated.company == "Acme"
    assert updated.notes == "initial note"

    # Clear notes
    updated2 = update_application(app.id, notes="", db_path=db_path)
    assert updated2.notes is None

    # Invalid applied_date on update
    with pytest.raises(ValidationError) as exc:
        update_application(app.id, applied_date="2024-13-01", db_path=db_path)
    assert "YYYY-MM-DD" in str(exc.value)

    # No fields provided
    with pytest.raises(ValidationError) as exc:
        update_application(app.id, db_path=db_path)
    assert "No fields provided" in str(exc.value)


def test_set_application_status_validates_and_updates(db_path):
    app = add_application(company="Acme", role="Dev", db_path=db_path)
    # Valid update with normalization
    updated = set_application_status(app.id, "Offer", db_path=db_path)
    assert updated.status == STATUS_OFFER

    # Invalid status
    with pytest.raises(ValidationError):
        set_application_status(app.id, "unknown", db_path=db_path)


def test_delete_application_and_notfound(db_path):
    app = add_application(company="Acme", role="Dev", db_path=db_path)
    # Delete once
    delete_application(app.id, db_path=db_path)
    # Subsequent fetch should raise NotFound
    with pytest.raises(NotFoundError):
        get_application(app.id, db_path=db_path)
    # Deleting non-existent should raise NotFound
    with pytest.raises(NotFoundError):
        delete_application(app.id, db_path=db_path)


def test_bulk_insert_applications_success_and_defaults(db_path, monkeypatch):
    monkeypatch.setattr("scrum_103.today_iso", lambda: "2023-12-31")
    items = [
        {"company": "Acme", "role": "Dev", "notes": "   "},  # defaults status/date, notes trimmed to None
        {"company": "Beta", "role": "QA", "status": "InTeRvIeWiNg", "applied_date": "2023-12-30", "notes": " note "},
    ]
    created = bulk_insert_applications(items, db_path=db_path)
    assert len(created) == 2

    acme = next(x for x in created if x.company == "Acme")
    beta = next(x for x in created if x.company == "Beta")

    assert acme.status == STATUS_APPLIED
    assert acme.applied_date == "2023-12-31"
    assert acme.notes is None

    assert beta.status == STATUS_INTERVIEWING
    assert beta.applied_date == "2023-12-30"
    assert beta.notes == "note"

    # Verify persistence via list
    all_apps = list_applications(db_path=db_path, order_by="company", descending=False)
    assert [a.company for a in all_apps] == ["Acme", "Beta"]


def test_bulk_insert_applications_rollback_on_validation_error(db_path, monkeypatch):
    monkeypatch.setattr("scrum_103.today_iso", lambda: "2023-12-31")
    items = [
        {"company": "Acme", "role": "Dev"},
        {"company": "Oops", "role": "   "},  # invalid role (empty after trim)
        {"company": "WillNotInsert", "role": "Eng"},
    ]
    with pytest.raises(ValidationError):
        bulk_insert_applications(items, db_path=db_path)

    # Ensure nothing persisted (transaction rolled back)
    assert list_applications(db_path=db_path) == []


def test_group_applications_by_status_and_other_key():
    apps = [
        Application(id=1, company="A", role="R", status=STATUS_APPLIED, applied_date="2024-01-01"),
        Application(id=2, company="B", role="R", status=STATUS_OFFER, applied_date="2024-01-02"),
        Application(id=3, company="C", role="R", status="weird", applied_date="2024-01-03"),
    ]
    grouped = group_applications_by_status(apps)
    assert set([STATUS_APPLIED, STATUS_INTERVIEWING, STATUS_OFFER, STATUS_REJECTED]).issubset(grouped.keys())
    assert "other" in grouped
    assert [a.id for a in grouped["other"]] == [3]
    assert [a.id for a in grouped[STATUS_APPLIED]] == [1]
    assert [a.id for a in grouped[STATUS_OFFER]] == [2]

    # No unknown statuses -> no 'other' key added
    apps2 = [
        Application(id=4, company="D", role="R", status=STATUS_APPLIED, applied_date="2024-01-04"),
        Application(id=5, company="E", role="R", status=STATUS_REJECTED, applied_date="2024-01-05"),
    ]
    grouped2 = group_applications_by_status(apps2)
    assert "other" not in grouped2
    assert [a.id for a in grouped2[STATUS_REJECTED]] == [5]


def test_error_to_message_mappings():
    assert error_to_message(ValidationError("oops")) == "oops"
    assert error_to_message(NotFoundError("missing")) == "missing"
    assert error_to_message(sqlite3.IntegrityError("constraint")) == "Data integrity error. Please check your inputs."
    assert error_to_message(RuntimeError("boom")).startswith("An unexpected error occurred")


def test_get_application_not_found(db_path):
    with pytest.raises(NotFoundError):
        get_application(9999, db_path=db_path)


def test_update_application_not_found(db_path):
    with pytest.raises(NotFoundError):
        update_application(9999, company="X", db_path=db_path)


def test_set_application_status_not_found(db_path):
    with pytest.raises(NotFoundError):
        set_application_status(9999, STATUS_APPLIED, db_path=db_path)


def test_delete_application_not_found(db_path):
    with pytest.raises(NotFoundError):
        delete_application(9999, db_path=db_path)


def test_application_to_dict(db_path):
    app = add_application(company="Acme", role="Dev", notes=" hello ", applied_date="2024-01-01", db_path=db_path)
    d = app.to_dict()
    assert d["id"] == app.id
    assert d["company"] == "Acme"
    assert d["role"] == "Dev"
    assert d["status"] == STATUS_APPLIED
    assert d["applied_date"] == "2024-01-01"
    assert d["notes"] == "hello"