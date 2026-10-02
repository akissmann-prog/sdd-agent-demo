import sqlite3
import pytest
import scrum_132


def test_ensure_initialized_creates_table(tmp_path):
    db_path = str(tmp_path / "app.db")
    scrum_132.ensure_initialized(db_path)
    # Call again to ensure idempotency
    scrum_132.ensure_initialized(db_path)

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='applications'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "applications"


def test_list_empty_on_new_db(tmp_path):
    db_path = str(tmp_path / "app.db")
    apps = scrum_132.list_applications(db_path=db_path)
    assert apps == []


def test_create_application_defaults(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    fixed_today = "2025-01-02"
    monkeypatch.setattr(scrum_132, "_utc_today_iso", lambda: fixed_today)

    result = scrum_132.create_application(
        {"company": "Acme Corp", "role": "Engineer"}, db_path=db_path
    )
    assert isinstance(result["id"], int)
    assert result["company"] == "Acme Corp"
    assert result["role"] == "Engineer"
    assert result["status"] == "applied"
    assert result["applied_date"] == fixed_today
    assert result["notes"] is None

    # Ensure persisted
    fetched = scrum_132.get_application_by_id(result["id"], db_path=db_path)
    assert fetched == result


def test_create_application_with_all_fields(tmp_path):
    db_path = str(tmp_path / "app.db")
    data = {
        "company": "Globex",
        "role": "Manager",
        "status": "interviewing",
        "applied_date": "2023-12-01",
        "notes": "Referred by Jane",
    }
    result = scrum_132.create_application(data, db_path=db_path)
    assert result["company"] == "Globex"
    assert result["role"] == "Manager"
    assert result["status"] == "interviewing"
    assert result["applied_date"] == "2023-12-01"
    assert result["notes"] == "Referred by Jane"


@pytest.mark.parametrize(
    "data,err_msg_part",
    [
        ({"role": "Engineer"}, "Field 'company' must be a string."),
        ({"company": "Acme", "role": ""}, "Field 'role' cannot be empty."),
        ({"company": "Acme", "role": "Eng", "status": 123}, "Field 'status' must be a string."),
        ({"company": "Acme", "role": "Eng", "status": "pending"}, "Invalid status 'pending'"),
        (
            {"company": "Acme", "role": "Eng", "applied_date": 20230101},
            "Field 'applied_date' must be a string in YYYY-MM-DD format.",
        ),
        (
            {"company": "Acme", "role": "Eng", "applied_date": "2023-02-30"},
            "Invalid date format for 'applied_date'. Expected YYYY-MM-DD.",
        ),
        ({"company": "Acme", "role": "Eng", "notes": 123}, "Field 'notes' must be a string or null."),
    ],
)
def test_create_application_validation_errors(tmp_path, data, err_msg_part):
    db_path = str(tmp_path / "app.db")
    with pytest.raises(scrum_132.ValidationError) as ei:
        scrum_132.create_application(data, db_path=db_path)
    assert err_msg_part in str(ei.value)


def test_list_applications_filtering_and_sorting(tmp_path):
    db_path = str(tmp_path / "app.db")
    # Create multiple entries with different dates and statuses
    a = scrum_132.create_application(
        {"company": "A", "role": "R", "status": "applied", "applied_date": "2023-01-01"},
        db_path=db_path,
    )
    b = scrum_132.create_application(
        {"company": "B", "role": "R", "status": "interviewing", "applied_date": "2023-01-02"},
        db_path=db_path,
    )
    c = scrum_132.create_application(
        {"company": "C", "role": "R", "status": "applied", "applied_date": "2023-01-02"},
        db_path=db_path,
    )
    d = scrum_132.create_application(
        {"company": "D", "role": "R", "status": "rejected", "applied_date": "2024-01-01"},
        db_path=db_path,
    )

    all_apps = scrum_132.list_applications(db_path=db_path)
    # Expected order: d (2024), then c and b (2023-01-02) by id desc, then a
    assert [x["id"] for x in all_apps] == [d["id"], c["id"], b["id"], a["id"]]

    applied_apps = scrum_132.list_applications(status="applied", db_path=db_path)
    assert [x["id"] for x in applied_apps] == [c["id"], a["id"]]

    with pytest.raises(scrum_132.ValidationError) as ei:
        scrum_132.list_applications(status=123, db_path=db_path)
    assert "Parameter 'status' must be a string." in str(ei.value)

    with pytest.raises(scrum_132.ValidationError) as ei2:
        scrum_132.list_applications(status="unknown", db_path=db_path)
    assert "Invalid status 'unknown'" in str(ei2.value)


def test_get_application_by_id_and_not_found(tmp_path):
    db_path = str(tmp_path / "app.db")
    created = scrum_132.create_application(
        {"company": "Acme", "role": "Dev"}, db_path=db_path
    )
    got = scrum_132.get_application_by_id(created["id"], db_path=db_path)
    assert got == created

    with pytest.raises(scrum_132.NotFoundError) as ei:
        scrum_132.get_application_by_id(created["id"] + 999, db_path=db_path)
    assert "not found" in str(ei.value)


def test_update_application_happy_and_validations(tmp_path):
    db_path = str(tmp_path / "app.db")
    created = scrum_132.create_application(
        {"company": "OrigCo", "role": "Jr Dev", "status": "applied", "applied_date": "2023-01-10"},
        db_path=db_path,
    )
    app_id = created["id"]

    with pytest.raises(scrum_132.ValidationError) as e1:
        scrum_132.update_application(app_id, {}, db_path=db_path)
    assert "No fields provided to update." in str(e1.value)

    with pytest.raises(scrum_132.ValidationError) as e2:
        scrum_132.update_application(app_id, {"foo": "bar"}, db_path=db_path)
    assert "Unknown fields in update: foo" in str(e2.value)

    with pytest.raises(scrum_132.ValidationError) as e3:
        scrum_132.update_application(app_id, {"status": 123}, db_path=db_path)
    assert "Field 'status' must be a string." in str(e3.value)

    with pytest.raises(scrum_132.ValidationError) as e4:
        scrum_132.update_application(app_id, {"status": "pending"}, db_path=db_path)
    assert "Invalid status 'pending'" in str(e4.value)

    with pytest.raises(scrum_132.ValidationError) as e5:
        scrum_132.update_application(app_id, {"applied_date": 20230101}, db_path=db_path)
    assert "Field 'applied_date' must be a string in YYYY-MM-DD format." in str(e5.value)

    with pytest.raises(scrum_132.ValidationError) as e6:
        scrum_132.update_application(app_id, {"applied_date": "2023-02-30"}, db_path=db_path)
    assert "Invalid date format for 'applied_date'" in str(e6.value)

    with pytest.raises(scrum_132.ValidationError) as e7:
        scrum_132.update_application(app_id, {"notes": 10.5}, db_path=db_path)
    assert "Field 'notes' must be a string or null." in str(e7.value)

    with pytest.raises(scrum_132.ValidationError) as e8:
        scrum_132.update_application(app_id, {"company": " "}, db_path=db_path)
    assert "Field 'company' cannot be empty." in str(e8.value)

    with pytest.raises(scrum_132.ValidationError) as e9:
        scrum_132.update_application(app_id, {"role": ""}, db_path=db_path)
    assert "Field 'role' cannot be empty." in str(e9.value)

    # Happy path: update multiple fields
    updated = scrum_132.update_application(
        app_id,
        {
            "company": "NewCo",
            "role": "Sr Dev",
            "status": "offer",
            "applied_date": "2023-03-10",
            "notes": "Updated",
        },
        db_path=db_path,
    )
    assert updated["company"] == "NewCo"
    assert updated["role"] == "Sr Dev"
    assert updated["status"] == "offer"
    assert updated["applied_date"] == "2023-03-10"
    assert updated["notes"] == "Updated"

    # Update notes to None
    updated2 = scrum_132.update_application(app_id, {"notes": None}, db_path=db_path)
    assert updated2["notes"] is None

    # Not found id
    with pytest.raises(scrum_132.NotFoundError):
        scrum_132.update_application(app_id + 999, {"company": "X"}, db_path=db_path)


def test_delete_application_success_and_not_found(tmp_path):
    db_path = str(tmp_path / "app.db")
    a = scrum_132.create_application({"company": "A", "role": "R"}, db_path=db_path)
    b = scrum_132.create_application({"company": "B", "role": "R"}, db_path=db_path)
    # Delete a
    assert scrum_132.delete_application(a["id"], db_path=db_path) is None
    # Ensure a is gone
    with pytest.raises(scrum_132.NotFoundError):
        scrum_132.get_application_by_id(a["id"], db_path=db_path)
    # Deleting again raises
    with pytest.raises(scrum_132.NotFoundError):
        scrum_132.delete_application(a["id"], db_path=db_path)
    # b remains
    got_b = scrum_132.get_application_by_id(b["id"], db_path=db_path)
    assert got_b["company"] == "B"


def test_group_applications_by_status_basic():
    apps = [
        {"id": 1, "status": "applied"},
        {"id": 2, "status": "offer"},
        {"id": 3, "status": "ghost"},
        {"id": 4},  # missing status
    ]
    grouped = scrum_132.group_applications_by_status(apps)
    # All keys exist
    for s in scrum_132.ALLOWED_STATUSES:
        assert s in grouped
    # Unknown and missing statuses grouped under 'applied'
    assert [a["id"] for a in grouped["applied"]] == [1, 3, 4]
    assert [a["id"] for a in grouped["offer"]] == [2]
    assert grouped["interviewing"] == []
    assert grouped["rejected"] == []


def test_create_application_assert_post_insert(monkeypatch):
    # Simulate post-insert SELECT returning None to trigger assert (as per code review warning)
    class FakeCursor:
        def __init__(self, lastrowid=1, rowcount=1, fetchone_ret=None, fetchall_ret=None):
            self.lastrowid = lastrowid
            self.rowcount = rowcount
            self._fetchone_ret = fetchone_ret
            self._fetchall_ret = fetchall_ret

        def fetchone(self):
            return self._fetchone_ret

        def fetchall(self):
            return self._fetchall_ret or []

    class FakeConn:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            s = " ".join(sql.split()).strip().upper()
            if s.startswith("CREATE TABLE"):
                return FakeCursor()
            if s.startswith("INSERT INTO APPLICATIONS"):
                return FakeCursor(lastrowid=42)
            if s.startswith("SELECT"):
                return FakeCursor(fetchone_ret=None)
            return FakeCursor()

    monkeypatch.setattr(scrum_132, "_get_connection", lambda db_path: FakeConn())
    with pytest.raises(AssertionError) as ei:
        scrum_132.create_application({"company": "Test", "role": "Role"})
    assert "Inserted row not found" in str(ei.value)


def test_update_application_assert_post_update(monkeypatch):
    # Simulate UPDATE rowcount > 0 but post-update SELECT returning None to trigger assert
    class FakeCursor:
        def __init__(self, lastrowid=1, rowcount=1, fetchone_ret=None, fetchall_ret=None):
            self.lastrowid = lastrowid
            self.rowcount = rowcount
            self._fetchone_ret = fetchone_ret
            self._fetchall_ret = fetchall_ret

        def fetchone(self):
            return self._fetchone_ret

        def fetchall(self):
            return self._fetchall_ret or []

    class FakeConn:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            s = " ".join(sql.split()).strip().upper()
            if s.startswith("CREATE TABLE"):
                return FakeCursor()
            if s.startswith("UPDATE APPLICATIONS SET"):
                # simulate successful update
                return FakeCursor(rowcount=1)
            if s.startswith("SELECT"):
                return FakeCursor(fetchone_ret=None)
            return FakeCursor()

    monkeypatch.setattr(scrum_132, "_get_connection", lambda db_path: FakeConn())
    with pytest.raises(AssertionError) as ei:
        scrum_132.update_application(1, {"company": "X"})
    assert "Updated row not found after update" in str(ei.value)