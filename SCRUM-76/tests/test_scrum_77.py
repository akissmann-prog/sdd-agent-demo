import re
import pytest

import scrum_77 as mod


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_tasks.db")


def test_create_task_minimal_success(db_path):
    task = mod.create_task("Test task", db_path=db_path)
    assert isinstance(task, dict)
    assert task["id"] >= 1
    assert task["title"] == "Test task"
    assert task["description"] is None
    assert task["status"] == "todo"
    assert isinstance(task["created_date"], str)
    assert re.match(r"^\d{4}-\d{2}-\d{2} ", task["created_date"])


def test_create_task_trims_title_and_handles_description(db_path):
    task = mod.create_task("  Title with spaces  ", description="desc", status="doing", db_path=db_path)
    assert task["title"] == "Title with spaces"
    assert task["description"] == "desc"
    assert task["status"] == "doing"


def test_create_task_empty_title_raises(db_path):
    with pytest.raises(ValueError):
        mod.create_task("   ", db_path=db_path)
    with pytest.raises(ValueError):
        mod.create_task(None, db_path=db_path)  # type: ignore[arg-type]


def test_create_task_invalid_status_raises(db_path):
    with pytest.raises(ValueError) as ei:
        mod.create_task("X", status="invalid", db_path=db_path)
    msg = str(ei.value)
    assert "Invalid status" in msg
    for s in ("todo", "doing", "done"):
        assert s in msg


def test_create_task_status_none_defaults_todo(db_path):
    task = mod.create_task("Default status", status=None, db_path=db_path)  # type: ignore[arg-type]
    assert task["status"] == "todo"


def test_list_tasks_empty(db_path):
    tasks = mod.list_tasks(db_path=db_path)
    assert tasks == []


def test_list_tasks_ordering_and_filtering(db_path):
    t1 = mod.create_task("a1", status="todo", db_path=db_path)
    t2 = mod.create_task("b1", status="doing", db_path=db_path)
    t3 = mod.create_task("c1", status="done", db_path=db_path)
    all_tasks = mod.list_tasks(db_path=db_path)
    assert [t["id"] for t in all_tasks] == [t1["id"], t2["id"], t3["id"]]

    doing_tasks = mod.list_tasks(status="doing", db_path=db_path)
    assert len(doing_tasks) == 1
    assert doing_tasks[0]["id"] == t2["id"]
    assert doing_tasks[0]["status"] == "doing"


def test_list_tasks_invalid_status_raises(db_path):
    with pytest.raises(ValueError):
        mod.list_tasks(status="invalid", db_path=db_path)


def test_get_task_existing_and_missing(db_path):
    created = mod.create_task("Get me", description="", db_path=db_path)
    fetched = mod.get_task(created["id"], db_path=db_path)
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Get me"
    # empty string description remains empty string (not None)
    assert fetched["description"] == ""

    # missing
    assert mod.get_task(99999, db_path=db_path) is None


def test_update_task_happy_path(db_path):
    created = mod.create_task("Original", description="desc", status="todo", db_path=db_path)
    updated = mod.update_task(
        created["id"],
        title="  New Title  ",
        description="",
        status="doing",
        db_path=db_path,
    )
    assert updated["id"] == created["id"]
    assert updated["title"] == "New Title"
    assert updated["description"] == ""
    assert updated["status"] == "doing"


def test_update_task_invalid_status_raises(db_path):
    created = mod.create_task("Title", db_path=db_path)
    with pytest.raises(ValueError):
        mod.update_task(created["id"], status="nope", db_path=db_path)


def test_update_task_empty_title_raises(db_path):
    created = mod.create_task("Title", db_path=db_path)
    with pytest.raises(ValueError):
        mod.update_task(created["id"], title="   ", db_path=db_path)


def test_update_task_no_fields_raises(db_path):
    created = mod.create_task("Title", db_path=db_path)
    with pytest.raises(ValueError):
        mod.update_task(created["id"], db_path=db_path)


def test_update_task_nonexistent_raises_keyerror(db_path):
    with pytest.raises(KeyError):
        mod.update_task(12345, title="X", db_path=db_path)


def test_delete_task_behaviour(db_path):
    created = mod.create_task("To delete", db_path=db_path)
    assert mod.get_task(created["id"], db_path=db_path) is not None
    assert mod.delete_task(created["id"], db_path=db_path) is True
    assert mod.get_task(created["id"], db_path=db_path) is None
    # second time
    assert mod.delete_task(created["id"], db_path=db_path) is False


def test_multiple_schema_initializations_and_operations(db_path):
    # Ensure calling operations multiple times (which call _ensure_schema) does not error
    assert mod.list_tasks(db_path=db_path) == []
    t = mod.create_task("A", db_path=db_path)
    assert mod.list_tasks(db_path=db_path)[0]["id"] == t["id"]
    assert mod.list_tasks(status="todo", db_path=db_path)[0]["id"] == t["id"]


@pytest.mark.parametrize("status", ["todo", "doing", "done"])
def test_validate_status_allows_allowed(status):
    # Should not raise
    mod.validate_status(status)


def test_validate_status_rejects_invalid():
    with pytest.raises(ValueError):
        mod.validate_status("bananas")


def test_dashboard_html_contains_expected_endpoints_and_headers():
    html = mod.get_dashboard_html()
    assert isinstance(html, str)
    # Structure elements
    assert "<!doctype html>" in html.lower()
    assert 'id="todoList"' in html
    assert 'id="doingList"' in html
    assert 'id="doneList"' in html
    # API endpoints usage
    assert "fetch('/tasks'" in html or 'fetch("/tasks"' in html
    assert "fetch('/tasks?status='" in html or 'fetch("/tasks?status="' in html
    assert "fetch('/tasks/' + encodeURIComponent(id)" in html or 'fetch("/tasks/" + encodeURIComponent(id)' in html
    # Methods and headers
    assert "'Content-Type': 'application/json'" in html  # for POST/PUT
    assert "'Accept': 'application/json'" in html
    assert "{ method: 'DELETE' }" in html or '{ method: "DELETE" }' in html
    # Rendering groups
    assert "grouped = { todo: [], doing: [], done: [] }" in html or "grouped = { todo: [], doing: [], done: [] }" in html
    # Title/description displayed with textContent
    assert ".textContent" in html