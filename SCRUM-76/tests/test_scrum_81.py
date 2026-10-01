import datetime
import os
import re
import sqlite3

import pytest

import scrum_81 as m


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def utc_today_iso():
    return datetime.datetime.utcnow().date().isoformat()


def test_list_empty_db_returns_empty(db_path):
    tasks = m.list_tasks(db_path=db_path)
    assert tasks == []


def test_create_task_applies_defaults_and_trims_title_and_dates_utc(db_path):
    t = m.create_task("  First Task  ", db_path=db_path)
    assert isinstance(t, m.Task)
    assert t.title == "First Task"
    assert t.status == "todo"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", t.created_date)
    assert t.created_date == utc_today_iso()

    # Ensure persisted in DB and id starts at 1
    fetched = m.get_task(t.id, db_path=db_path)
    assert fetched == t


def test_create_task_with_status_case_insensitive(db_path):
    t = m.create_task("My Task", status="DoINg", db_path=db_path)
    assert t.status == "doing"
    assert t.title == "My Task"


@pytest.mark.parametrize(
    "bad_title, expected_msg",
    [
        (None, "Title must be a string."),
        (123, "Title must be a string."),
        (b"bytes", "Title must be a string."),
        ("", "Title must be non-empty."),
        ("   ", "Title must be non-empty."),
    ],
)
def test_create_task_invalid_title_values(db_path, bad_title, expected_msg):
    with pytest.raises(m.ValidationError) as ei:
        m.create_task(bad_title, db_path=db_path)
    assert expected_msg in str(ei.value)


@pytest.mark.parametrize(
    "bad_status, expected_msg_substr",
    [
        (None, None),  # default allowed; sanity: should create fine
        (123, "Status must be a string."),
        ("blocked", "Status must be one of"),
    ],
)
def test_create_task_invalid_status_values(db_path, bad_status, expected_msg_substr):
    if bad_status is None:
        t = m.create_task("ok", status=None, db_path=db_path)
        assert t.status == "todo"
    else:
        with pytest.raises(m.ValidationError) as ei:
            m.create_task("ok", status=bad_status, db_path=db_path)
        assert expected_msg_substr in str(ei.value)


def test_get_task_existing_and_notfound(db_path):
    t1 = m.create_task("A", db_path=db_path)
    t2 = m.create_task("B", status="done", db_path=db_path)

    got1 = m.get_task(t1.id, db_path=db_path)
    got2 = m.get_task(t2.id, db_path=db_path)
    assert got1.title == "A"
    assert got1.status == "todo"
    assert got2.title == "B"
    assert got2.status == "done"

    with pytest.raises(m.NotFoundError):
        m.get_task(9999, db_path=db_path)


def test_update_task_requires_fields_validation_before_db(db_path):
    # Even if task doesn't exist, lacking fields should raise ValidationError first
    with pytest.raises(m.ValidationError) as ei:
        m.update_task(1, db_path=db_path)
    assert "No updates provided" in str(ei.value)


def test_update_task_not_found(db_path):
    with pytest.raises(m.NotFoundError):
        m.update_task(1234, title="whatever", db_path=db_path)


def test_update_task_title_and_status_and_preserves_created_date(db_path):
    t = m.create_task("Original", status="todo", db_path=db_path)
    original_created = t.created_date

    # Update title only with trimming
    t2 = m.update_task(t.id, title="  New Title  ", db_path=db_path)
    assert t2.title == "New Title"
    assert t2.status == "todo"
    assert t2.created_date == original_created

    # Update status only with case-insensitive input
    t3 = m.update_task(t.id, status="DoNE", db_path=db_path)
    assert t3.title == "New Title"
    assert t3.status == "done"
    assert t3.created_date == original_created

    # Update both
    t4 = m.update_task(t.id, title="Another", status="doing", db_path=db_path)
    assert t4.title == "Another"
    assert t4.status == "doing"
    assert t4.created_date == original_created

    # Verify persisted from DB
    t_check = m.get_task(t.id, db_path=db_path)
    assert t_check == t4


@pytest.mark.parametrize(
    "kwargs, expected_msg",
    [
        (dict(title="   "), "Title must be non-empty."),
        (dict(status="invalid"), "Status must be one of"),
        (dict(status=123), "Status must be a string."),
        (dict(title=123), "Title must be a string."),
    ],
)
def test_update_task_invalid_inputs(db_path, kwargs, expected_msg):
    t = m.create_task("Valid", db_path=db_path)
    with pytest.raises(m.ValidationError) as ei:
        m.update_task(t.id, db_path=db_path, **kwargs)
    assert expected_msg in str(ei.value)

    # Ensure task unchanged
    fresh = m.get_task(t.id, db_path=db_path)
    assert fresh.title == "Valid"
    assert fresh.status == "todo"


def test_delete_task_existing_and_notfound(db_path):
    t = m.create_task("To delete", db_path=db_path)

    # Delete successfully
    m.delete_task(t.id, db_path=db_path)

    # Ensure it's gone
    with pytest.raises(m.NotFoundError):
        m.get_task(t.id, db_path=db_path)

    # Deleting again should raise NotFoundError
    with pytest.raises(m.NotFoundError):
        m.delete_task(t.id, db_path=db_path)


def test_list_tasks_order_and_filtering_case_insensitive_and_invalid_filter(db_path):
    t1 = m.create_task("t1", status="todo", db_path=db_path)
    t2 = m.create_task("t2", status="doing", db_path=db_path)
    t3 = m.create_task("t3", status="done", db_path=db_path)
    t4 = m.create_task("t4", status="doing", db_path=db_path)

    all_tasks = m.list_tasks(db_path=db_path)
    assert [t.id for t in all_tasks] == [t1.id, t2.id, t3.id, t4.id]

    doing_tasks = m.list_tasks(status="doing", db_path=db_path)
    assert [t.id for t in doing_tasks] == [t2.id, t4.id]
    doing_tasks_ci = m.list_tasks(status="DOING", db_path=db_path)
    assert [t.id for t in doing_tasks_ci] == [t2.id, t4.id]

    with pytest.raises(m.ValidationError):
        m.list_tasks(status="blocked", db_path=db_path)


def test_persistence_across_calls_with_file_db(tmp_path):
    db = str(tmp_path / "persist.db")
    a = m.create_task("A", db_path=db)
    b = m.create_task("B", status="done", db_path=db)

    tasks = m.list_tasks(db_path=db)
    assert [t.id for t in tasks] == [a.id, b.id]
    assert [t.title for t in tasks] == ["A", "B"]


def test_created_date_matches_utc_today(db_path):
    t = m.create_task("Check date", db_path=db_path)
    assert t.created_date == utc_today_iso()
    # As a sanity check, ensure it's not localtime if local day differs from UTC at boundary
    # We cannot simulate timezone here, but at least ensure correct format
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", t.created_date)


def test_schema_created_implicitly_on_operations(db_path):
    # The database file should not exist initially
    assert not os.path.exists(db_path)

    # list_tasks should create schema implicitly and return empty
    tasks = m.list_tasks(db_path=db_path)
    assert tasks == []

    # Now file should exist after an operation that writes (create_task)
    t = m.create_task("Init", db_path=db_path)
    assert os.path.exists(db_path)
    got = m.get_task(t.id, db_path=db_path)
    assert got.title == "Init"