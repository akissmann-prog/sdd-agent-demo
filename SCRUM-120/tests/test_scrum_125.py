import uuid as _uuid
from datetime import datetime
from typing import Dict, Any
import pytest

import scrum_125 as m


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test_applications.sqlite3")


def test_get_statuses() -> None:
    statuses = m.get_statuses()
    assert isinstance(statuses, tuple)
    assert statuses == ("applied", "interviewing", "offer", "rejected")


def test_list_applications_empty(db_path: str) -> None:
    assert m.list_applications(db_path) == []


def test_create_and_get_application_defaults_and_retrieval(db_path: str, monkeypatch) -> None:
    # Fix today's date for deterministic test
    monkeypatch.setattr(m, "_today_yyyy_mm_dd", lambda: "2024-01-31")

    app = m.create_application({"company": "Acme", "role": "Engineer"}, db_path=db_path)

    # Valid UUID
    uuid_obj = _uuid.UUID(app["id"])
    assert str(uuid_obj) == app["id"]

    assert app["company"] == "Acme"
    assert app["role"] == "Engineer"
    assert app["status"] == "applied"
    assert app["applied_date"] == "2024-01-31"
    assert app["notes"] == ""

    fetched = m.get_application(app["id"], db_path=db_path)
    assert fetched == app


def test_create_status_normalization_and_date_validation(db_path: str) -> None:
    app = m.create_application(
        {"company": "Globex", "role": "Manager", "status": " Offer ", "applied_date": "2024-03-05", "notes": "  "},
        db_path=db_path,
    )
    assert app["status"] == "offer"
    assert app["applied_date"] == "2024-03-05"
    assert app["notes"] == "  "  # notes are not trimmed


@pytest.mark.parametrize(
    "payload, err_msg",
    [
        ({"role": "Dev"}, "company is required"),
        ({"company": "X"}, "role is required"),
        ({"company": 123, "role": "Dev"}, "company must be a string"),
        ({"company": "X", "role": None}, "role must be a string"),
        ({"company": "   ", "role": "Dev"}, "company cannot be empty"),
        ({"company": "X", "role": "   "}, "role cannot be empty"),
        ({"company": "X", "role": "Dev", "status": 5}, "status must be a string"),
        ({"company": "X", "role": "Dev", "status": "unknown"}, "status must be one of"),
        ({"company": "X", "role": "Dev", "applied_date": 20240101}, "applied_date must be a string"),
        ({"company": "X", "role": "Dev", "applied_date": "2020-01-01x"}, "applied_date must be in YYYY-MM-DD format"),
        ({"company": "X", "role": "Dev", "applied_date": "2020-02-30"}, "applied_date must be in YYYY-MM-DD format"),
        ({"company": "X", "role": "Dev", "notes": 123}, "notes must be a string"),
    ],
)
def test_create_validation_errors(payload: Dict[str, Any], err_msg: str, db_path: str) -> None:
    with pytest.raises(m.ValidationError) as ei:
        m.create_application(payload, db_path=db_path)
    assert err_msg in str(ei.value)


def test_duplicate_id_integrity_error_leaks_message(db_path: str, monkeypatch) -> None:
    # First creation with fixed UUID, second should violate PK and trigger IntegrityError handling
    fixed = "11111111-1111-4111-8111-111111111111"  # valid UUID4 pattern
    class FakeUUID:
        def __init__(self, ids):
            self.ids = ids
            self.idx = 0
        def __call__(self):
            val = self.ids[self.idx]
            self.idx = min(self.idx + 1, len(self.ids) - 1)
            return _uuid.UUID(val)
    monkeypatch.setattr(m.uuid, "uuid4", FakeUUID([fixed, fixed]))

    a1 = m.create_application({"company": "Acme", "role": "Eng"}, db_path=db_path)
    assert a1["id"] == fixed
    with pytest.raises(m.ValidationError) as ei:
        m.create_application({"company": "Acme2", "role": "Eng2"}, db_path=db_path)
    # Code review warned about leaking sqlite3.IntegrityError; verify current behavior to cover issue
    assert "Integrity error:" in str(ei.value)


def test_update_application_happy_path(db_path: str) -> None:
    app = m.create_application({"company": "A", "role": "R"}, db_path=db_path)
    updated = m.update_application(
        app["id"],
        {
            "company": "  NewCo  ",
            "role": "  NewRole ",
            "status": "interviewing",
            "applied_date": "2024-04-01",
            "notes": "updated",
        },
        db_path=db_path,
    )
    assert updated["company"] == "NewCo"
    assert updated["role"] == "NewRole"
    assert updated["status"] == "interviewing"
    assert updated["applied_date"] == "2024-04-01"
    assert updated["notes"] == "updated"

    # Fetch to confirm persisted
    fetched = m.get_application(app["id"], db_path=db_path)
    assert fetched == updated


@pytest.mark.parametrize(
    "patch, err_msg",
    [
        ("not-a-dict", "patch must be an object"),
        ({}, "No fields to update"),
        ({"unknown": "x"}, "Unknown field in update"),
        ({"company": 123}, "company must be a string"),
        ({"role": None}, "role must be a string"),
        ({"status": 1}, "status must be a string"),
        ({"status": "bad"}, "status must be one of"),
        ({"applied_date": 1}, "applied_date must be a string"),
        ({"applied_date": "2020-01-01x"}, "applied_date must be in YYYY-MM-DD format"),
        ({"notes": 3.14}, "notes must be a string"),
    ],
)
def test_update_validation_errors(db_path: str, patch: Any, err_msg: str) -> None:
    app = m.create_application({"company": "C", "role": "R"}, db_path=db_path)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application(app["id"], patch, db_path=db_path)
    assert err_msg in str(ei.value)


def test_update_no_valid_fields_to_update(db_path: str) -> None:
    app = m.create_application({"company": "C", "role": "R"}, db_path=db_path)
    with pytest.raises(m.ValidationError) as ei:
        m.update_application(app["id"], {"company": "   "}, db_path=db_path)
    assert "company cannot be empty" in str(ei.value)


def test_update_not_found(db_path: str) -> None:
    with pytest.raises(m.NotFoundError):
        m.update_application("nonexistent-id", {"company": "X"}, db_path=db_path)


def test_change_status_convenience(db_path: str) -> None:
    app = m.create_application({"company": "Co", "role": "Dev"}, db_path=db_path)
    changed = m.change_status(app["id"], "offer", db_path=db_path)
    assert changed["status"] == "offer"


def test_delete_application_success_and_not_found(db_path: str) -> None:
    app = m.create_application({"company": "Del", "role": "Me"}, db_path=db_path)
    # Successful delete returns None
    out = m.delete_application(app["id"], db_path=db_path)
    assert out is None

    # Subsequent get should fail
    with pytest.raises(m.NotFoundError):
        m.get_application(app["id"], db_path=db_path)

    # Deleting non-existent id raises NotFoundError
    with pytest.raises(m.NotFoundError):
        m.delete_application("nope", db_path=db_path)


def test_group_applications_by_status_grouping_and_order(db_path: str) -> None:
    # Create multiple with varied statuses and dates to test ordering
    a1 = m.create_application(
        {"company": "Beta", "role": "Dev", "status": "applied", "applied_date": "2024-01-02"}, db_path=db_path
    )
    a2 = m.create_application(
        {"company": "Alpha", "role": "Analyst", "status": "applied", "applied_date": "2024-01-02"}, db_path=db_path
    )
    a3 = m.create_application(
        {"company": "Gamma", "role": "Z-Role", "status": "offer", "applied_date": "2023-12-31"}, db_path=db_path
    )
    a4 = m.create_application(
        {"company": "Alpha", "role": "B-Role", "status": "applied", "applied_date": "2023-12-31"}, db_path=db_path
    )

    grouped = m.group_applications_by_status(db_path=db_path)
    # All statuses present
    for s in m.STATUSES:
        assert s in grouped
        assert isinstance(grouped[s], list)

    # Applied group should contain a1, a2, a4 in the overall ORDER BY:
    # applied_date DESC, company ASC, role ASC
    # For applied: a1 and a2 share 2024-01-02, order by company then role
    applied = grouped["applied"]
    applied_ids = [x["id"] for x in applied]
    expected_order = [a2["id"], a1["id"], a4["id"]]  # a2(Alpha, 2024-01-02), a1(Beta, 2024-01-02), a4(Alpha, 2023-12-31)
    assert applied_ids == expected_order

    # Offer group contains a3
    assert grouped["offer"] == [a3]


def test_list_applications_ordering_across_all(db_path: str) -> None:
    # Mix records to test ORDER BY fully
    r1 = m.create_application({"company": "B", "role": "A", "applied_date": "2024-05-01"}, db_path=db_path)
    r2 = m.create_application({"company": "A", "role": "B", "applied_date": "2024-05-01"}, db_path=db_path)
    r3 = m.create_application({"company": "A", "role": "A", "applied_date": "2024-04-30"}, db_path=db_path)
    lst = m.list_applications(db_path=db_path)
    assert [x["id"] for x in lst] == [r2["id"], r1["id"], r3["id"]]


def test_get_application_not_found(db_path: str) -> None:
    with pytest.raises(m.NotFoundError):
        m.get_application("does-not-exist", db_path=db_path)


def test_validate_create_defaults_and_errors(monkeypatch) -> None:
    monkeypatch.setattr(m, "_today_yyyy_mm_dd", lambda: "2024-02-15")
    out = m.validate_create({"company": "  Co  ", "role": "  Dev  "})
    assert out == {
        "company": "Co",
        "role": "Dev",
        "status": "applied",
        "applied_date": "2024-02-15",
        "notes": "",
    }

    with pytest.raises(m.ValidationError):
        m.validate_create({"role": "Dev"})

    with pytest.raises(m.ValidationError):
        m.validate_create({"company": "Co"})

    with pytest.raises(m.ValidationError):
        m.validate_create({"company": "Co", "role": "Dev", "status": "BAD"})

    with pytest.raises(m.ValidationError):
        m.validate_create({"company": "Co", "role": "Dev", "applied_date": "2020-13-01"})

    with pytest.raises(m.ValidationError):
        m.validate_create({"company": "Co", "role": "Dev", "notes": 123})


def test_validate_update_sanitization_and_errors() -> None:
    out = m.validate_update({"company": "  X  ", "role": "  Y  ", "status": " Offer ", "applied_date": "2024-06-01", "notes": "ok"})
    assert out["company"] == "X"
    assert out["role"] == "Y"
    assert out["status"] == "offer"
    assert out["applied_date"] == "2024-06-01"
    assert out["notes"] == "ok"

    with pytest.raises(m.ValidationError):
        m.validate_update({})

    with pytest.raises(m.ValidationError):
        m.validate_update("not-a-dict")  # type: ignore[arg-type]

    with pytest.raises(m.ValidationError):
        m.validate_update({"unknown": "x"})

    with pytest.raises(m.ValidationError):
        m.validate_update({"applied_date": "2020-01-01x"})