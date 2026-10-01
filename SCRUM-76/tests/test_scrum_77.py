import re
import pytest

from scrum_77 import (
    create_task,
    get_task,
    list_tasks,
    update_task,
    delete_task,
    validate_status,
    get_dashboard_html,
)


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "tasks.sqlite3")


def test_validate_status_valid_values():
    for s in ["todo", "doing", "done"]:
        validate_status(s)  # should not raise


def test_validate_status_invalid_value():
    with pytest.raises(ValueError) as exc:
        validate_status("invalid")
    msg = str(exc.value)
    assert "Invalid status" in msg
    assert "'invalid'" in msg
    # allowed list should be present and sorted
    assert "['doing', 'done', 'todo']" in msg


def test_create_task_happy_path_defaults(db_file):
    task = create_task("  My Task  ", db_path=db_file)
    assert isinstance(task["id"], int)
    assert task["title"] == "My Task"
    assert task["description"] is None
    assert task["status"] == "todo"
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", task["created_date"])


def test_create_task_title_validation(db_file):
    with pytest.raises(ValueError) as exc1:
        create_task("", db_path=db_file)
    assert "Title is required" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        create_task("   ", db_path=db_file)
    assert "Title is required" in str(exc2.value)

    with pytest.raises(ValueError) as exc3:
        create_task(None, db_path=db_file)  # type: ignore[arg-type]
    assert "Title is required" in str(exc3.value)


def test_create_task_status_handling(db_file):
    task_default_status = create_task("t1", status=None, db_path=db_file)
    assert task_default_status["status"] == "todo"

    with pytest.raises(ValueError):
        create_task("t2", status="bogus", db_path=db_file)

    with pytest.raises(ValueError):
        create_task("t3", status="TODO", db_path=db_file)

    with pytest.raises(ValueError):
        create_task("t4", status=" done ", db_path=db_file)


def test_get_task_not_found_and_found(db_file):
    assert get_task(9999, db_path=db_file) is None
    t = create_task("Find me", description="desc", status="doing", db_path=db_file)
    fetched = get_task(t["id"], db_path=db_file)
    assert fetched is not None
    assert fetched["id"] == t["id"]
    assert fetched["title"] == "Find me"
    assert fetched["description"] == "desc"
    assert fetched["status"] == "doing"


def test_list_tasks_empty_and_ordering_and_filtering(db_file):
    assert list_tasks(db_path=db_file) == []

    t1 = create_task("A", status="todo", db_path=db_file)
    t2 = create_task("B", status="doing", db_path=db_file)
    t3 = create_task("C", status="done", db_path=db_file)

    all_tasks = list_tasks(db_path=db_file)
    assert [t["id"] for t in all_tasks] == [t1["id"], t2["id"], t3["id"]]

    doing_tasks = list_tasks(status="doing", db_path=db_file)
    assert len(doing_tasks) == 1
    assert doing_tasks[0]["id"] == t2["id"]
    assert doing_tasks[0]["status"] == "doing"

    with pytest.raises(ValueError):
        list_tasks(status="nope", db_path=db_file)

    # Cover code review note: empty string status currently raises ValueError
    with pytest.raises(ValueError):
        list_tasks(status="", db_path=db_file)  # strict validation today


def test_update_task_failures(db_file):
    t = create_task("Original", description="D", status="todo", db_path=db_file)

    with pytest.raises(ValueError) as exc:
        update_task(t["id"], db_path=db_file)
    assert "At least one field" in str(exc.value)

    with pytest.raises(KeyError) as exc2:
        update_task(99999, title="x", db_path=db_file)
    assert "not found" in str(exc2.value)

    with pytest.raises(ValueError) as exc3:
        update_task(t["id"], title="   ", db_path=db_file)
    assert "Title cannot be empty" in str(exc3.value)

    with pytest.raises(ValueError):
        update_task(t["id"], status="BAD", db_path=db_file)

    # Case-insensitive not supported currently; 'Doing' should raise
    with pytest.raises(ValueError):
        update_task(t["id"], status="Doing", db_path=db_file)


def test_update_task_success_single_and_multiple_fields(db_file):
    t = create_task("Task", description=None, status="todo", db_path=db_file)

    updated_title = update_task(t["id"], title="  New Title  ", db_path=db_file)
    assert updated_title["title"] == "New Title"
    assert updated_title["description"] is None
    assert updated_title["status"] == "todo"

    updated_desc = update_task(t["id"], description="", db_path=db_file)
    assert updated_desc["title"] == "New Title"
    assert updated_desc["description"] == ""
    assert updated_desc["status"] == "todo"

    updated_status = update_task(t["id"], status="doing", db_path=db_file)
    assert updated_status["status"] == "doing"

    updated_all = update_task(
        t["id"], title="Final", description="Final desc", status="done", db_path=db_file
    )
    assert updated_all["title"] == "Final"
    assert updated_all["description"] == "Final desc"
    assert updated_all["status"] == "done"


def test_delete_task_existing_and_nonexisting(db_file):
    t = create_task("Delete me", db_path=db_file)
    assert get_task(t["id"], db_path=db_file) is not None

    ok = delete_task(t["id"], db_path=db_file)
    assert ok is True
    assert get_task(t["id"], db_path=db_file) is None

    ok2 = delete_task(t["id"], db_path=db_file)
    assert ok2 is False


def test_non_string_description_is_coerced_on_read(db_file):
    t = create_task("Num desc", description=123, status="todo", db_path=db_file)  # type: ignore[arg-type]
    fetched = get_task(t["id"], db_path=db_file)
    assert fetched is not None
    assert fetched["description"] == "123"


def test_dashboard_html_contains_expected_endpoints_and_statuses():
    html = get_dashboard_html()
    assert "<!doctype html>" in html.lower()
    assert "<title>Tasks Dashboard</title>" in html
    assert "/tasks" in html
    assert "fetch('/tasks'" in html
    assert "fetch('/tasks/" in html  # for update/delete paths
    assert "for (const s of ['todo', 'doing', 'done'])" in html
    # ensure dashboard has expected containers
    assert 'id="todoList"' in html
    assert 'id="doingList"' in html
    assert 'id="doneList"' in html