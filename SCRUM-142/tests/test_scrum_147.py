import uuid
import pytest

import scrum_147 as m


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.sqlite")


def test_create_application_defaults_and_normalization(monkeypatch, db_path):
    fixed_date = "2023-03-05"
    monkeypatch.setattr(m, "_today_utc_ymd", lambda: fixed_date)
    monkeypatch.setattr(m.uuid, "uuid4", lambda: uuid.UUID("00000000-0000-0000-0000-000000000001"))
    payload = {
        "company": "  Acme  ",
        "role": "  Engineer ",
        "status": None,
        "applied_date": None,
    }
    created = m.ApplicationService.create_application(payload, db_path=db_path)
    assert created["id"] == "00000000-0000-0000-0000-000000000001"
    assert created["company"] == "Acme"
    assert created["role"] == "Engineer"
    assert created["status"] == "applied"
    assert created["applied_date"] == fixed_date

    # Verify persistence
    fetched = m.ApplicationRepository.get_by_id(created["id"], db_path=db_path)
    assert fetched == created


def test_create_application_with_status_and_date_validation_and_normalization(monkeypatch, db_path):
    monkeypatch.setattr(m.uuid, "uuid4", lambda: uuid.UUID("00000000-0000-0000-0000-000000000002"))
    payload = {
        "company": "Co",
        "role": "Dev",
        "status": " INTERVIEWING ",
        "applied_date": "2023-01-01 ",
    }
    created = m.ApplicationService.create_application(payload, db_path=db_path)
    assert created["status"] == "interviewing"
    assert created["applied_date"] == "2023-01-01"


def test_create_application_invalid_inputs(db_path):
    # Missing company
    with pytest.raises(m.BadRequestError) as e1:
        m.ApplicationService.create_application({"role": "Engineer"}, db_path=db_path)
    assert str(e1.value) == "400: company is required"

    # Missing role
    with pytest.raises(m.BadRequestError) as e2:
        m.ApplicationService.create_application({"company": "Acme"}, db_path=db_path)
    assert str(e2.value) == "400: role is required"

    # Invalid status
    with pytest.raises(m.BadRequestError) as e3:
        m.ApplicationService.create_application({"company": "Acme", "role": "Engineer", "status": "unknown"}, db_path=db_path)
    assert str(e3.value) == "400: invalid status"

    # Invalid applied_date format
    with pytest.raises(m.BadRequestError) as e4:
        m.ApplicationService.create_application({"company": "Acme", "role": "Engineer", "applied_date": "2023/01/01"}, db_path=db_path)
    assert str(e4.value) == "400: applied_date must be in YYYY-MM-DD format"

    # Empty applied_date string
    with pytest.raises(m.BadRequestError) as e5:
        m.ApplicationService.create_application({"company": "Acme", "role": "Engineer", "applied_date": "  "}, db_path=db_path)
    assert str(e5.value) == "400: applied_date must be in YYYY-MM-DD format"


def test_list_applications_ordering_and_filtering(monkeypatch, db_path):
    # Deterministic IDs for ordering checks
    ids = [
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        uuid.UUID("00000000-0000-0000-0000-000000000002"),
        uuid.UUID("00000000-0000-0000-0000-000000000003"),
    ]

    def id_gen():
        it = iter(ids)
        return lambda: next(it)

    monkeypatch.setattr(m.uuid, "uuid4", id_gen())

    # Create three records with different dates/statuses
    a = m.ApplicationService.create_application(
        {"company": "A", "role": "R", "status": "applied", "applied_date": "2023-01-02"},
        db_path=db_path,
    )
    b = m.ApplicationService.create_application(
        {"company": "B", "role": "R", "status": "offer", "applied_date": "2023-01-03"},
        db_path=db_path,
    )
    c = m.ApplicationService.create_application(
        {"company": "C", "role": "R", "status": "interviewing", "applied_date": "2023-01-03"},
        db_path=db_path,
    )

    items = m.ApplicationService.list_applications(None, db_path=db_path)
    assert [i["id"] for i in items] == [b["id"], c["id"], a["id"]]

    # Filter by status with normalization
    filtered = m.ApplicationService.list_applications("  InterViewIng ", db_path=db_path)
    assert [i["id"] for i in filtered] == [c["id"]]

    # Controller wrapper
    code, body = m.get_applications(db_path=db_path)
    assert code == 200
    assert "items" in body and isinstance(body["items"], list)
    assert len(body["items"]) == 3

    # Invalid status in controller
    code2, body2 = m.get_applications(status="bad", db_path=db_path)
    assert code2 == 400
    assert body2 == {"message": "invalid status"}


def test_get_application_by_id_happy_and_errors(monkeypatch, db_path):
    monkeypatch.setattr(m.uuid, "uuid4", lambda: uuid.UUID("00000000-0000-0000-0000-000000000099"))
    created = m.ApplicationService.create_application(
        {"company": "Acme", "role": "Engineer", "applied_date": "2023-02-01"},
        db_path=db_path,
    )

    # Happy path via controller
    code, item = m.get_application_by_id(created["id"], db_path=db_path)
    assert code == 200
    assert item == created

    # Non-existent valid UUID -> 404
    missing_id = str(uuid.uuid4())
    code2, body2 = m.get_application_by_id(missing_id, db_path=db_path)
    assert code2 == 404
    assert body2 == {"message": "application not found"}

    # Invalid ID format -> 400 (covers review warning)
    code3, body3 = m.get_application_by_id("not-a-uuid", db_path=db_path)
    assert code3 == 400
    assert body3 == {"message": "invalid id"}


def test_update_application_happy_partial_updates_and_normalization(db_path):
    created = m.ApplicationService.create_application(
        {"company": "OldCo", "role": "Dev", "status": "applied", "applied_date": "2023-01-01"},
        db_path=db_path,
    )

    updated = m.ApplicationService.update_application(
        created["id"],
        {"company": "  NewCo   ", "status": " OFFER "},
        db_path=db_path,
    )
    assert updated["company"] == "NewCo"
    assert updated["status"] == "offer"
    assert updated["role"] == "Dev"
    assert updated["applied_date"] == "2023-01-01"

    # Update applied_date with trimming
    updated2 = m.ApplicationService.update_application(
        created["id"],
        {"applied_date": "2023-01-05 "},
        db_path=db_path,
    )
    assert updated2["applied_date"] == "2023-01-05"


def test_update_application_validation_errors(db_path):
    created = m.ApplicationService.create_application(
        {"company": "Acme", "role": "Engineer", "applied_date": "2023-01-01"},
        db_path=db_path,
    )

    # company empty string
    with pytest.raises(m.BadRequestError) as e1:
        m.ApplicationService.update_application(created["id"], {"company": "   "}, db_path=db_path)
    assert str(e1.value) == "400: company must be a non-empty string"

    # role empty string
    with pytest.raises(m.BadRequestError) as e2:
        m.ApplicationService.update_application(created["id"], {"role": ""}, db_path=db_path)
    assert str(e2.value) == "400: role must be a non-empty string"

    # invalid status
    with pytest.raises(m.BadRequestError) as e3:
        m.ApplicationService.update_application(created["id"], {"status": "bad"}, db_path=db_path)
    assert str(e3.value) == "400: invalid status"

    # invalid applied_date string
    with pytest.raises(m.BadRequestError) as e4:
        m.ApplicationService.update_application(created["id"], {"applied_date": "bad"}, db_path=db_path)
    assert str(e4.value) == "400: applied_date must be in YYYY-MM-DD format"

    # applied_date None explicitly present -> error
    with pytest.raises(m.BadRequestError) as e5:
        m.ApplicationService.update_application(created["id"], {"applied_date": None}, db_path=db_path)
    assert str(e5.value) == "400: applied_date must be in YYYY-MM-DD format"

    # invalid id format
    with pytest.raises(m.BadRequestError) as e6:
        m.ApplicationService.update_application("not-a-uuid", {"company": "X"}, db_path=db_path)
    assert str(e6.value) == "400: invalid id"

    # non-existent but valid UUID -> NotFound
    missing_id = str(uuid.uuid4())
    with pytest.raises(m.NotFoundError) as e7:
        m.ApplicationService.update_application(missing_id, {"company": "X"}, db_path=db_path)
    assert str(e7.value) == "404: application not found"


def test_update_application_empty_payload_noop_triggers_update_call(monkeypatch, db_path):
    created = m.ApplicationService.create_application(
        {"company": "Acme", "role": "Engineer", "applied_date": "2023-01-01"},
        db_path=db_path,
    )
    existing = m.ApplicationRepository.get_by_id(created["id"], db_path=db_path)

    call_count = {"n": 0}
    original_update = m.ApplicationRepository.update

    def wrapper(*args, **kwargs):
        call_count["n"] += 1
        return original_update(*args, **kwargs)

    monkeypatch.setattr(m.ApplicationRepository, "update", staticmethod(wrapper))

    result = m.ApplicationService.update_application(created["id"], {}, db_path=db_path)
    assert call_count["n"] == 1
    assert result == existing

    # Extra irrelevant keys also cause update (covers review warning)
    result2 = m.ApplicationService.update_application(created["id"], {"foo": "bar"}, db_path=db_path)
    assert call_count["n"] == 2
    assert result2 == existing


def test_delete_application_happy_and_errors(db_path):
    created = m.ApplicationService.create_application(
        {"company": "Acme", "role": "Engineer", "applied_date": "2023-01-01"},
        db_path=db_path,
    )

    # Happy path via controller
    code, body = m.delete_application(created["id"], db_path=db_path)
    assert code == 204
    assert body is None
    # Ensure removed
    assert m.ApplicationRepository.get_by_id(created["id"], db_path=db_path) is None

    # Non-existent valid uuid
    missing_id = str(uuid.uuid4())
    code2, body2 = m.delete_application(missing_id, db_path=db_path)
    assert code2 == 404
    assert body2 == {"message": "application not found"}

    # Invalid id
    code3, body3 = m.delete_application("not-a-uuid", db_path=db_path)
    assert code3 == 400
    assert body3 == {"message": "invalid id"}


def test_controller_internal_error_mapping(monkeypatch, db_path):
    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(m.ApplicationService, "create_application", staticmethod(boom))
    code, body = m.post_applications({"company": "x", "role": "y"}, db_path=db_path)
    assert code == 500
    assert body == {"message": "internal server error"}