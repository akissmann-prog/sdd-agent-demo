import pytest
from scrum_121 import (
    create_application,
    list_applications,
    get_application_by_id,
    require_application_by_id,
    update_application,
    delete_application,
    validate_filter_status,
    ValidationError,
    NotFoundError,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_create_application_minimal_defaults_and_trimming(monkeypatch, db_path):
    # Patch today's date for deterministic behavior
    monkeypatch.setattr("scrum_121._utc_today", lambda: "2023-12-25")
    app = create_application("  Acme Corp  ", "  Engineer  ", db_path=db_path)
    assert isinstance(app["id"], int)
    assert app["company"] == "Acme Corp"
    assert app["role"] == "Engineer"
    assert app["status"] == "applied"
    assert app["applied_date"] == "2023-12-25"
    assert app["notes"] is None

    # Verify persistence by fetching via get
    fetched = get_application_by_id(app["id"], db_path=db_path)
    assert fetched == app


def test_create_application_with_status_and_notes_case_and_trimming(db_path):
    app = create_application(
        "Company",
        "Role",
        status=" Offer ",
        applied_date=" 2021-01-01 ",
        notes="  Important  ",
        db_path=db_path,
    )
    assert app["status"] == "offer"
    assert app["applied_date"] == "2021-01-01"
    assert app["notes"] == "Important"


@pytest.mark.parametrize(
    "company,role,err_msg",
    [
        ("", "Role", "company is required"),
        ("   ", "Role", "company is required"),
        ("Company", "", "role is required"),
        ("Company", "   ", "role is required"),
    ],
)
def test_create_application_required_fields_validation(company, role, err_msg, db_path):
    with pytest.raises(ValidationError) as exc:
        create_application(company, role, db_path=db_path)
    assert err_msg in str(exc.value)


@pytest.mark.parametrize(
    "status",
    ["", "   ", "pending", "HIRED"],
)
def test_create_application_invalid_status(status, db_path):
    with pytest.raises(ValidationError) as exc:
        create_application("Company", "Role", status=status, applied_date="2021-01-01", db_path=db_path)
    assert "Invalid status" in str(exc.value) or "status" in str(exc.value)


@pytest.mark.parametrize(
    "applied_date,err_msg",
    [
        ("", "applied_date cannot be empty"),
        ("  ", "applied_date cannot be empty"),
        ("2020-1-01", "YYYY-MM-DD"),
        ("2020-13-01", "not a valid date"),
        ("2020-02-30", "not a valid date"),
        ("20-02-02", "YYYY-MM-DD"),
    ],
)
def test_create_application_invalid_applied_date(applied_date, err_msg, db_path):
    with pytest.raises(ValidationError) as exc:
        create_application("Company", "Role", applied_date=applied_date, db_path=db_path)
    assert err_msg in str(exc.value)


def test_list_applications_empty_db_returns_empty_list(db_path):
    apps = list_applications(db_path=db_path)
    assert apps == []


def test_list_applications_with_persistence_and_filtering(db_path):
    a1 = create_application("A", "R1", status="applied", applied_date="2021-01-01", db_path=db_path)
    a2 = create_application("B", "R2", status="offer", applied_date="2021-01-02", db_path=db_path)
    a3 = create_application("C", "R3", status="rejected", applied_date="2021-01-03", db_path=db_path)

    all_apps = list_applications(db_path=db_path)
    assert {a["id"] for a in all_apps} == {a1["id"], a2["id"], a3["id"]}

    offers = list_applications(status=" Offer ", db_path=db_path)
    assert len(offers) == 1
    assert offers[0]["id"] == a2["id"]
    assert offers[0]["status"] == "offer"

    with pytest.raises(ValidationError):
        list_applications(status="", db_path=db_path)
    with pytest.raises(ValidationError):
        list_applications(status="unknown", db_path=db_path)


def test_get_and_require_application_by_id(db_path):
    app = create_application("Acme", "Dev", applied_date="2022-02-02", db_path=db_path)
    got = get_application_by_id(app["id"], db_path=db_path)
    assert got == app

    assert get_application_by_id(9999, db_path=db_path) is None

    req = require_application_by_id(app["id"], db_path=db_path)
    assert req == app

    with pytest.raises(NotFoundError):
        require_application_by_id(9999, db_path=db_path)


def test_update_application_happy_path(db_path):
    app = create_application("OldCo", "OldRole", status="applied", applied_date="2021-01-01", notes=None, db_path=db_path)

    updated = update_application(
        app["id"],
        company="  NewCo  ",
        role="NewRole",
        status="INTERVIEWING",
        applied_date="2022-01-31",
        notes="  Updated notes ",
        db_path=db_path,
    )

    assert updated["id"] == app["id"]
    assert updated["company"] == "NewCo"
    assert updated["role"] == "NewRole"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2022-01-31"
    assert updated["notes"] == "Updated notes"

    # Verify persisted
    fetched = get_application_by_id(app["id"], db_path=db_path)
    assert fetched == updated


def test_update_application_no_fields_provided_raises(db_path):
    app = create_application("Acme", "Dev", applied_date="2021-01-01", db_path=db_path)
    with pytest.raises(ValidationError) as exc:
        update_application(app["id"], db_path=db_path)
    assert "No updatable fields provided" in str(exc.value)


@pytest.mark.parametrize(
    "kwargs,err_msg",
    [
        ({"company": "   "}, "company cannot be empty"),
        ({"role": ""}, "role cannot be empty"),
        ({"status": "  "}, "status cannot be empty"),
        ({"status": "waiting"}, "Invalid status"),
        ({"applied_date": ""}, "applied_date cannot be empty"),
        ({"applied_date": "2020-1-01"}, "YYYY-MM-DD"),
        ({"applied_date": "2020-02-30"}, "not a valid date"),
    ],
)
def test_update_application_invalid_values(kwargs, err_msg, db_path):
    app = create_application("Acme", "Dev", applied_date="2021-01-01", db_path=db_path)
    with pytest.raises(ValidationError) as exc:
        update_application(app["id"], db_path=db_path, **kwargs)
    assert err_msg in str(exc.value)


def test_update_application_noop_update_does_not_404(db_path):
    # Covers the code review critical issue: updating to same values should not 404
    app = create_application("Co", "Role", status="applied", applied_date="2021-01-01", notes="x", db_path=db_path)

    # Update to same values
    updated = update_application(
        app["id"],
        company="Co",
        role="Role",
        status="applied",
        applied_date="2021-01-01",
        notes="x",
        db_path=db_path,
    )

    assert updated == get_application_by_id(app["id"], db_path=db_path)


def test_update_application_nonexistent_id_raises_not_found(db_path):
    with pytest.raises(NotFoundError) as exc:
        update_application(9999, company="New", db_path=db_path)
    assert "not found" in str(exc.value)


def test_delete_application_behavior(db_path):
    a1 = create_application("A", "R1", applied_date="2021-01-01", db_path=db_path)
    a2 = create_application("B", "R2", applied_date="2021-01-02", db_path=db_path)

    assert delete_application(a1["id"], db_path=db_path) is True
    # Deleting again should return False
    assert delete_application(a1["id"], db_path=db_path) is False

    assert get_application_by_id(a1["id"], db_path=db_path) is None

    remaining = list_applications(db_path=db_path)
    assert len(remaining) == 1
    assert remaining[0]["id"] == a2["id"]


def test_validate_filter_status_helper():
    assert validate_filter_status(None) is None
    assert validate_filter_status(" Offer ") == "offer"
    with pytest.raises(ValidationError):
        validate_filter_status("")
    with pytest.raises(ValidationError):
        validate_filter_status("unknown")