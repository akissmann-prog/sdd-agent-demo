import uuid
import pytest

import scrum_147 as mod


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except Exception:
        return False


def test_post_application_success_defaults_and_status_normalization(monkeypatch, db_path):
    monkeypatch.setattr(mod, "_today_utc_ymd", lambda: "2020-01-02")

    payload = {"company": " Acme Corp ", "role": " Engineer "}
    code, body = mod.post_applications(payload, db_path=db_path)
    assert code == 201
    assert isinstance(body, dict)
    assert is_valid_uuid(body["id"])
    assert body["company"] == "Acme Corp"
    assert body["role"] == "Engineer"
    assert body["status"] == "applied"
    assert body["applied_date"] == "2020-01-02"

    # verify persistence via GET by id
    code2, body2 = mod.get_application_by_id(body["id"], db_path=db_path)
    assert code2 == 200
    assert body2 == body


def test_post_application_with_status_mixed_case_and_explicit_date(db_path):
    payload = {
        "company": "Example Inc",
        "role": "Developer",
        "status": "  InTeRvIeWiNg ",
        "applied_date": "2021-12-31",
    }
    code, body = mod.post_applications(payload, db_path=db_path)
    assert code == 201
    assert body["status"] == "interviewing"
    assert body["applied_date"] == "2021-12-31"


@pytest.mark.parametrize(
    "payload, expected_message",
    [
        ({"role": "Engineer"}, "company is required"),
        ({"company": "   ", "role": "Engineer"}, "company is required"),
        ({"company": "Acme"}, "role is required"),
        ({"company": "Acme", "role": "   "}, "role is required"),
    ],
)
def test_post_application_missing_or_empty_company_role(db_path, payload, expected_message):
    code, body = mod.post_applications(payload, db_path=db_path)
    assert code == 400
    assert body["message"] == expected_message


def test_post_application_invalid_status(db_path):
    payload = {"company": "Acme", "role": "Engineer", "status": "pending"}
    code, body = mod.post_applications(payload, db_path=db_path)
    assert code == 400
    assert body["message"] == "invalid status"


def test_post_application_invalid_applied_date(db_path):
    payload = {"company": "Acme", "role": "Engineer", "applied_date": "2021-13-01"}
    code, body = mod.post_applications(payload, db_path=db_path)
    assert code == 400
    assert body["message"] == "applied_date must be in YYYY-MM-DD format"


def test_get_applications_list_and_ordering(monkeypatch, db_path):
    # Create three records with two identical dates to test secondary id ordering
    monkeypatch.setattr(mod, "_today_utc_ymd", lambda: "2022-01-01")
    c1 = {"company": "A", "role": "R"}  # default date 2022-01-01
    code, b1 = mod.post_applications(c1, db_path=db_path)
    assert code == 201

    c2 = {"company": "B", "role": "R", "status": "offer", "applied_date": "2023-12-31"}
    code, b2 = mod.post_applications(c2, db_path=db_path)
    assert code == 201

    c3 = {"company": "C", "role": "R", "status": "offer", "applied_date": "2023-12-31"}
    code, b3 = mod.post_applications(c3, db_path=db_path)
    assert code == 201

    code_list, body = mod.get_applications(db_path=db_path)
    assert code_list == 200
    items = body["items"]
    assert len(items) == 3

    # Order: applied_date DESC, then id ASC
    assert items[0]["applied_date"] == "2023-12-31"
    assert items[1]["applied_date"] == "2023-12-31"
    assert items[2]["applied_date"] == "2022-01-01"

    # First two sorted by id asc
    first_two_sorted = sorted(items[:2], key=lambda x: x["id"])
    assert items[:2] == first_two_sorted


def test_get_applications_filter_status_and_invalid(db_path):
    # Create sample data
    mod.post_applications({"company": "A", "role": "R", "status": "offer", "applied_date": "2023-01-01"}, db_path=db_path)
    mod.post_applications({"company": "B", "role": "R", "status": "offer", "applied_date": "2023-01-02"}, db_path=db_path)
    mod.post_applications({"company": "C", "role": "R", "status": "rejected", "applied_date": "2023-01-03"}, db_path=db_path)

    code_ok, body_ok = mod.get_applications(status="  OfFer  ", db_path=db_path)
    assert code_ok == 200
    items = body_ok["items"]
    assert all(it["status"] == "offer" for it in items)
    assert len(items) == 2

    code_bad, body_bad = mod.get_applications(status="invalid", db_path=db_path)
    assert code_bad == 400
    assert body_bad["message"] == "invalid status"

    code_empty, body_empty = mod.get_applications(status="", db_path=db_path)
    assert code_empty == 400
    assert body_empty["message"] == "invalid status"


def test_get_application_by_id_success_and_errors(db_path):
    code_created, created = mod.post_applications({"company": "Acme", "role": "Eng"}, db_path=db_path)
    assert code_created == 201
    good_id = created["id"]

    code_bad, body_bad = mod.get_application_by_id("not-a-uuid", db_path=db_path)
    assert code_bad == 400
    assert body_bad["message"] == "invalid id"

    random_id = str(uuid.uuid4())
    code_nf, body_nf = mod.get_application_by_id(random_id, db_path=db_path)
    assert code_nf == 404
    assert body_nf["message"] == "application not found"

    code_ok, body_ok = mod.get_application_by_id(good_id, db_path=db_path)
    assert code_ok == 200
    assert body_ok["id"] == good_id


def test_put_application_success_update_and_normalization(db_path):
    code_created, created = mod.post_applications({"company": "Acme", "role": "Eng"}, db_path=db_path)
    assert code_created == 201
    app_id = created["id"]

    payload = {"company": "  New Co  ", "status": "  REJECTED ", "applied_date": "2021-01-02"}
    code_upd, body_upd = mod.put_application(app_id, payload, db_path=db_path)
    assert code_upd == 200
    assert body_upd["company"] == "New Co"
    assert body_upd["status"] == "rejected"
    assert body_upd["applied_date"] == "2021-01-02"

    code_get, body_get = mod.get_application_by_id(app_id, db_path=db_path)
    assert code_get == 200
    assert body_get == body_upd


def test_put_application_invalid_id_and_not_found(db_path):
    code_bad, body_bad = mod.put_application("not-a-uuid", {"company": "X"}, db_path=db_path)
    assert code_bad == 400
    assert body_bad["message"] == "invalid id"

    not_found_id = str(uuid.uuid4())
    code_nf, body_nf = mod.put_application(not_found_id, {"company": "X"}, db_path=db_path)
    assert code_nf == 404
    assert body_nf["message"] == "application not found"


def test_put_application_invalid_status_and_applied_date_and_fields(db_path):
    code_created, created = mod.post_applications({"company": "Acme", "role": "Eng"}, db_path=db_path)
    assert code_created == 201
    app_id = created["id"]

    # invalid status
    code1, body1 = mod.put_application(app_id, {"status": "pending"}, db_path=db_path)
    assert code1 == 400
    assert body1["message"] == "invalid status"

    # invalid date format
    code2, body2 = mod.put_application(app_id, {"applied_date": "2021-99-99"}, db_path=db_path)
    assert code2 == 400
    assert body2["message"] == "applied_date must be in YYYY-MM-DD format"

    # empty date
    code3, body3 = mod.put_application(app_id, {"applied_date": "   "}, db_path=db_path)
    assert code3 == 400
    assert body3["message"] == "applied_date must be in YYYY-MM-DD format"

    # None date explicitly provided
    code4, body4 = mod.put_application(app_id, {"applied_date": None}, db_path=db_path)
    assert code4 == 400
    assert body4["message"] == "applied_date must be in YYYY-MM-DD format"

    # empty company
    code5, body5 = mod.put_application(app_id, {"company": "   "}, db_path=db_path)
    assert code5 == 400
    assert body5["message"] == "company must be a non-empty string"

    # empty role
    code6, body6 = mod.put_application(app_id, {"role": ""}, db_path=db_path)
    assert code6 == 400
    assert body6["message"] == "role must be a non-empty string"


def test_delete_application_success_and_errors(db_path):
    code_created, created = mod.post_applications({"company": "Acme", "role": "Eng"}, db_path=db_path)
    assert code_created == 201
    app_id = created["id"]

    code_del, body_del = mod.delete_application(app_id, db_path=db_path)
    assert code_del == 204
    assert body_del is None

    # second delete should be 404
    code_del2, body_del2 = mod.delete_application(app_id, db_path=db_path)
    assert code_del2 == 404
    assert body_del2["message"] == "application not found"

    # invalid id
    code_bad, body_bad = mod.delete_application("abc", db_path=db_path)
    assert code_bad == 400
    assert body_bad["message"] == "invalid id"


def test_internal_error_translates_to_500(monkeypatch, db_path):
    def boom(*args, **kwargs):
        raise ValueError("boom")
    monkeypatch.setattr(mod.ApplicationService, "create_application", boom)
    code, body = mod.post_applications({"company": "Acme", "role": "Eng"}, db_path=db_path)
    assert code == 500
    assert body["message"] == "internal server error"