import uuid
from datetime import date

import pytest

import scrum_143 as m


def new_db(tmp_path):
    return str(tmp_path / "test.db")


def is_uuid4(s: str) -> bool:
    try:
        u = uuid.UUID(s)
    except Exception:
        return False
    return u.version == 4


def test_create_application_defaults_and_normalization(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company="  ACME  ", role=" Dev  ", db_path=db)
    assert is_uuid4(app["id"])
    assert app["company"] == "ACME"
    assert app["role"] == "Dev"
    assert app["status"] == "applied"
    assert app["notes"] is None
    assert app["applied_date"] == date.today().isoformat()

    # Persisted and retrievable
    fetched = m.get_application(app["id"], db_path=db)
    assert fetched == app


def test_create_application_status_notes_and_applied_date_normalization(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(
        company="X",
        role="Y",
        status="  OFFER  ",
        notes="  hello  ",
        applied_date=" 2022-01-02 ",
        db_path=db,
    )
    assert app["status"] == "offer"
    assert app["notes"] == "hello"
    assert app["applied_date"] == "2022-01-02"


def test_create_application_invalid_status_raises(tmp_path):
    db = new_db(tmp_path)
    with pytest.raises(ValueError):
        m.create_application(company="X", role="Y", status="invalid", db_path=db)


def test_create_application_required_fields_validation(tmp_path):
    db = new_db(tmp_path)
    with pytest.raises(ValueError):
        m.create_application(company="   ", role="Engineer", db_path=db)
    with pytest.raises(ValueError):
        m.create_application(company="Company", role=None, db_path=db)  # type: ignore[arg-type]


def test_create_application_non_string_company_role_coercion(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company=123, role=True, db_path=db)  # type: ignore[arg-type]
    assert app["company"] == "123"
    assert app["role"] == "True"


def test_get_applications_empty_and_status_filter(tmp_path):
    db = new_db(tmp_path)
    assert m.get_applications(db_path=db) == []

    a1 = m.create_application(company="A", role="R1", status="applied", db_path=db)
    a2 = m.create_application(company="B", role="R2", status="offer", db_path=db)

    apps_all = m.get_applications(db_path=db)
    assert {a["id"] for a in apps_all} == {a1["id"], a2["id"]}

    offers = m.get_applications(status="  OFFER  ", db_path=db)
    assert [a["id"] for a in offers] == [a2["id"]]


def test_ordering_by_applied_date_desc_and_company_case_insensitive(tmp_path):
    db = new_db(tmp_path)
    a_old = m.create_application(company="beta", role="R", applied_date="2023-09-10", db_path=db)
    a_same_date_upper = m.create_application(company="Alpha", role="R", applied_date="2023-09-10", db_path=db)
    a_new = m.create_application(company="gamma", role="R", applied_date="2023-09-11", db_path=db)

    apps = m.get_applications(db_path=db)
    # Expect newest date first, and for same date, company ascending case-insensitive: Alpha before beta
    assert [a["id"] for a in apps] == [a_new["id"], a_same_date_upper["id"], a_old["id"]]


def test_applied_date_accepts_arbitrary_and_lexicographic_sort_issue(tmp_path):
    db = new_db(tmp_path)
    # Demonstrate acceptance of non-ISO formats and lexicographic ordering behavior
    feb = m.create_application(company="C1", role="R", applied_date="2023-2-10", db_path=db)
    nov = m.create_application(company="C2", role="R", applied_date="2023-11-01", db_path=db)

    apps = m.get_applications(db_path=db)
    # Because ordering is lexicographic on strings, '2023-2-10' compares greater than '2023-11-01'
    # So DESC order yields the non-zero-padded date first, which is chronologically incorrect.
    assert [a["id"] for a in apps] == [feb["id"], nov["id"]]

    # Also show that completely arbitrary strings are accepted
    weird = m.create_application(company="C3", role="R", applied_date="banana", db_path=db)
    apps2 = m.get_applications(db_path=db)
    # 'banana' > '2023-...' lexicographically; thus appears first in DESC
    assert apps2[0]["id"] == weird["id"]
    assert apps2[0]["applied_date"] == "banana"


def test_get_application_and_update_preserve_unmodified_and_normalize(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company="Company", role="Role", notes="note", db_path=db)

    updated = m.update_application(app["id"], {"company": " New  ", "notes": "   "}, db_path=db)
    assert updated is not None
    assert updated["company"] == "New"
    assert updated["notes"] is None
    assert updated["role"] == app["role"]
    assert updated["applied_date"] == app["applied_date"]
    assert updated["status"] == app["status"]

    # Empty patch returns current record unchanged
    same = m.update_application(app["id"], {}, db_path=db)
    assert same == updated


def test_update_application_invalid_values_raise(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company="C", role="R", db_path=db)

    with pytest.raises(ValueError):
        m.update_application(app["id"], {"status": "not-a-status"}, db_path=db)

    with pytest.raises(ValueError):
        m.update_application(app["id"], {"company": "   "}, db_path=db)

    with pytest.raises(ValueError):
        m.update_application(app["id"], {"role": ""}, db_path=db)


def test_update_application_applied_date_empty_keeps_current_and_non_str_converted(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company="C", role="R", applied_date="2021-01-01", db_path=db)

    # Empty string keeps current value
    updated_same = m.update_application(app["id"], {"applied_date": "   "}, db_path=db)
    assert updated_same is not None
    assert updated_same["applied_date"] == "2021-01-01"

    # Non-string is converted to string
    updated_num = m.update_application(app["id"], {"applied_date": 123}, db_path=db)  # type: ignore[arg-type]
    assert updated_num is not None
    assert updated_num["applied_date"] == "123"


def test_update_nonexistent_returns_none(tmp_path):
    db = new_db(tmp_path)
    assert m.update_application("nonexistent-id", {"company": "X"}, db_path=db) is None


def test_delete_application_existing_and_non_existing(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company="C", role="R", db_path=db)

    assert m.get_application(app["id"], db_path=db) is not None

    deleted = m.delete_application(app["id"], db_path=db)
    assert deleted is True
    assert m.get_application(app["id"], db_path=db) is None

    deleted_again = m.delete_application(app["id"], db_path=db)
    assert deleted_again is False


def test_change_status_convenience(tmp_path):
    db = new_db(tmp_path)
    app = m.create_application(company="C", role="R", db_path=db)
    changed = m.change_status(app["id"], "INTERVIEWING", db_path=db)
    assert changed is not None
    assert changed["status"] == "interviewing"

    # Nonexistent id returns None
    assert m.change_status("no-such-id", "offer", db_path=db) is None


def test_list_grouped_by_status_keys_and_membership(tmp_path):
    db = new_db(tmp_path)
    groups = m.list_grouped_by_status(db_path=db)
    assert set(groups.keys()) == set(m.STATUSES)
    for k in m.STATUSES:
        assert isinstance(groups[k], list)
        assert groups[k] == []

    a1 = m.create_application(company="C1", role="R1", status="applied", db_path=db)
    a2 = m.create_application(company="C2", role="R2", status="offer", db_path=db)
    groups2 = m.list_grouped_by_status(db_path=db)

    assert a1["id"] in [a["id"] for a in groups2["applied"]]
    assert a2["id"] in [a["id"] for a in groups2["offer"]]

    # Unmentioned statuses remain present and are lists
    for s in m.STATUSES:
        assert isinstance(groups2[s], list)


def test_notes_normalization_variants(tmp_path):
    db = new_db(tmp_path)
    a1 = m.create_application(company="C1", role="R1", notes="", db_path=db)
    a2 = m.create_application(company="C2", role="R2", notes="   ", db_path=db)
    a3 = m.create_application(company="C3", role="R3", notes=42, db_path=db)  # type: ignore[arg-type]

    assert a1["notes"] is None
    assert a2["notes"] is None
    assert a3["notes"] == "42"


def test_get_application_not_found_returns_none(tmp_path):
    db = new_db(tmp_path)
    assert m.get_application("missing", db_path=db) is None