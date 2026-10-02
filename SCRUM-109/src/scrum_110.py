"""
Business logic module for managing job applications with SQLite persistence.

This module provides pure functions to create, list, retrieve, update, and delete
job applications. It enforces validation rules, applies sensible defaults, and
persists data to a SQLite database via the standard library sqlite3 module.

Each function that interacts with the database accepts a db_path parameter,
defaulting to "demo.db". The database schema is created on first use.

Intended to be used beneath an HTTP layer; errors are raised as exceptions with
HTTP-like status codes for easy mapping to API responses.

Also includes a basic unittest suite covering happy paths and validation failures.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
import tempfile
import unittest


ALLOWED_STATUSES: Tuple[str, ...] = ("applied", "interviewing", "offer", "rejected")


@dataclass
class ApiError(Exception):
    message: str
    status_code: int

    def __str__(self) -> str:
        return self.message


class ValidationError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=400)


class NotFoundError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=404)


def _open_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('applied','interviewing','offer','rejected')),
            applied_date TEXT NOT NULL,
            notes TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_applications_status
        ON applications (status);
        """
    )
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "company": row["company"],
        "role": row["role"],
        "status": row["status"],
        "applied_date": row["applied_date"],
        "notes": row["notes"],
    }


def today_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _validate_status(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("status must be a string")
    normalized = value.strip().lower()
    if normalized not in ALLOWED_STATUSES:
        raise ValidationError(f"status must be one of {list(ALLOWED_STATUSES)}")
    return normalized


def _validate_company(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("company must be a string")
    s = value.strip()
    if not s:
        raise ValidationError("company is required and cannot be empty")
    return s


def _validate_role(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("role must be a string")
    s = value.strip()
    if not s:
        raise ValidationError("role is required and cannot be empty")
    return s


def _validate_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("applied_date must be a string in YYYY-MM-DD format")
    s = value.strip()
    try:
        # Will raise ValueError if not valid ISO date
        datetime.fromisoformat(s)
    except Exception:
        raise ValidationError("applied_date must be a valid date in YYYY-MM-DD format")
    # Normalize to date part if datetime was passed
    if "T" in s:
        s = s.split("T", 1)[0]
    # Ensure strictly YYYY-MM-DD
    try:
        _ = datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        raise ValidationError("applied_date must be a valid date in YYYY-MM-DD format")
    return s


def _validate_notes(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("notes must be a string or null")
    return value


def _validate_id(app_id: Any) -> int:
    if not isinstance(app_id, int):
        raise ValidationError("id must be an integer")
    if app_id <= 0:
        raise ValidationError("id must be a positive integer")
    return app_id


def create_application(payload: Dict[str, Any], db_path: str = "demo.db") -> Dict[str, Any]:
    """
    Create a new application, applying defaults and validation.

    Required fields:
      - company: non-empty string
      - role: non-empty string

    Optional fields:
      - status: one of ALLOWED_STATUSES; defaults to "applied"
      - applied_date: YYYY-MM-DD; defaults to today in UTC
      - notes: string or None

    Returns the created application as a dict including its id.
    Raises ValidationError on invalid input.
    """
    company = _validate_company(payload.get("company"))
    role = _validate_role(payload.get("role"))
    status = payload.get("status", "applied")
    status = _validate_status(status)
    applied_date = payload.get("applied_date")
    if applied_date is None:
        applied_date = today_utc_date()
    else:
        applied_date = _validate_date(applied_date)
    notes = _validate_notes(payload.get("notes"))

    with _open_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO applications (company, role, status, applied_date, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (company, role, status, applied_date, notes),
        )
        app_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert row is not None
        return _row_to_dict(row)


def list_applications(status: Optional[str] = None, db_path: str = "demo.db") -> List[Dict[str, Any]]:
    """
    List applications. If status is provided, validate and filter by status.
    Raises ValidationError if status is invalid.
    """
    params: Tuple[Any, ...]
    sql: str
    if status is None:
        sql = "SELECT id, company, role, status, applied_date, notes FROM applications ORDER BY id ASC"
        params = ()
    else:
        status_norm = _validate_status(status)
        sql = "SELECT id, company, role, status, applied_date, notes FROM applications WHERE status = ? ORDER BY id ASC"
        params = (status_norm,)

    with _open_connection(db_path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_application(app_id: int, db_path: str = "demo.db") -> Dict[str, Any]:
    """
    Retrieve an application by id. Raises NotFoundError if not found.
    """
    app_id = _validate_id(app_id)
    with _open_connection(db_path) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("application not found")
        return _row_to_dict(row)


def update_application(app_id: int, patch: Dict[str, Any], db_path: str = "demo.db") -> Dict[str, Any]:
    """
    Partially update fields of an application.
    Allowed fields: company, role, status, applied_date, notes.

    Raises:
      - ValidationError: on invalid id, payload, or values; also when no valid fields are provided.
      - NotFoundError: if the application does not exist.
    """
    app_id = _validate_id(app_id)

    fields: Dict[str, Any] = {}
    if "company" in patch:
        fields["company"] = _validate_company(patch.get("company"))
    if "role" in patch:
        fields["role"] = _validate_role(patch.get("role"))
    if "status" in patch:
        fields["status"] = _validate_status(patch.get("status"))
    if "applied_date" in patch:
        fields["applied_date"] = _validate_date(patch.get("applied_date"))
    if "notes" in patch:
        fields["notes"] = _validate_notes(patch.get("notes"))

    if not fields:
        raise ValidationError("update payload must include at least one updatable field")

    set_clauses: List[str] = []
    values: List[Any] = []
    for key, val in fields.items():
        set_clauses.append(f"{key} = ?")
        values.append(val)
    values.append(app_id)

    with _open_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute("SELECT 1 FROM applications WHERE id = ?", (app_id,))
        exists = cur.fetchone() is not None
        if not exists:
            raise NotFoundError("application not found")
        conn.execute(f"UPDATE applications SET {', '.join(set_clauses)} WHERE id = ?", tuple(values))
        conn.commit()
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert row is not None
        return _row_to_dict(row)


def delete_application(app_id: int, db_path: str = "demo.db") -> None:
    """
    Delete an application by id. Raises NotFoundError if not found.
    """
    app_id = _validate_id(app_id)
    with _open_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("application not found")


# -------------------------
# Basic automated test suite
# -------------------------

class ApplicationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_create_success_defaults(self) -> None:
        rec = create_application({"company": "Acme Corp", "role": "Engineer"}, db_path=self.db_path)
        self.assertIsInstance(rec["id"], int)
        self.assertEqual(rec["company"], "Acme Corp")
        self.assertEqual(rec["role"], "Engineer")
        self.assertEqual(rec["status"], "applied")
        self.assertEqual(rec["applied_date"], today_utc_date())
        self.assertIsNone(rec["notes"])

    def test_create_validation_empty_company(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            create_application({"company": "   ", "role": "Engineer"}, db_path=self.db_path)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_create_invalid_status(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            create_application({"company": "Acme", "role": "Eng", "status": "pending"}, db_path=self.db_path)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_list_all_and_filter(self) -> None:
        create_application({"company": "A", "role": "R1", "status": "applied"}, db_path=self.db_path)
        create_application({"company": "B", "role": "R2", "status": "interviewing"}, db_path=self.db_path)
        create_application({"company": "C", "role": "R3", "status": "applied"}, db_path=self.db_path)

        all_recs = list_applications(db_path=self.db_path)
        self.assertEqual(len(all_recs), 3)

        applied_recs = list_applications(status="applied", db_path=self.db_path)
        self.assertEqual(len(applied_recs), 2)
        for r in applied_recs:
            self.assertEqual(r["status"], "applied")

        with self.assertRaises(ValidationError):
            list_applications(status="invalid", db_path=self.db_path)

    def test_get_by_id_found_and_notfound(self) -> None:
        rec = create_application({"company": "Acme", "role": "Dev"}, db_path=self.db_path)
        fetched = get_application(rec["id"], db_path=self.db_path)
        self.assertEqual(fetched["id"], rec["id"])
        self.assertEqual(fetched["company"], "Acme")

        with self.assertRaises(NotFoundError):
            get_application(9999, db_path=self.db_path)

    def test_update_partial_and_validation(self) -> None:
        rec = create_application({"company": "Acme", "role": "Dev"}, db_path=self.db_path)
        updated = update_application(
            rec["id"],
            {"status": "interviewing", "notes": "Phone screen passed"},
            db_path=self.db_path,
        )
        self.assertEqual(updated["status"], "interviewing")
        self.assertEqual(updated["notes"], "Phone screen passed")
        self.assertEqual(updated["company"], "Acme")  # unchanged

        with self.assertRaises(ValidationError):
            update_application(rec["id"], {"status": "wrong"}, db_path=self.db_path)

        with self.assertRaises(ValidationError):
            update_application(rec["id"], {}, db_path=self.db_path)

        with self.assertRaises(NotFoundError):
            update_application(9999, {"company": "X"}, db_path=self.db_path)

    def test_delete_success_and_notfound(self) -> None:
        rec = create_application({"company": "Acme", "role": "Dev"}, db_path=self.db_path)
        # Ensure it exists
        self.assertEqual(len(list_applications(db_path=self.db_path)), 1)
        # Delete
        delete_application(rec["id"], db_path=self.db_path)
        # Ensure it's gone
        self.assertEqual(len(list_applications(db_path=self.db_path)), 0)
        # Deleting again should fail
        with self.assertRaises(NotFoundError):
            delete_application(rec["id"], db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()