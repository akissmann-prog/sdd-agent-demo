"""
Business logic module for managing job applications with SQLite storage.

This module provides pure functions to perform CRUD operations on an "applications"
dataset intended to back a single-page dashboard UI. It includes validation,
schema management, and typed return structures, without any HTTP framework.

Key characteristics:
- SQLite storage via stdlib sqlite3
- Schema creation on first use
- Strict validation for create and update operations
- All dates stored as YYYY-MM-DD
- Status is constrained to a known set of values
- IDs are UUID4 strings explicitly inserted to satisfy schema/insert consistency

All functions that interact with the database accept a db_path parameter.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict


# ----- Constants and Types -----

STATUSES: Tuple[str, ...] = ("applied", "interviewing", "offer", "rejected")


class Application(TypedDict):
    id: str
    company: str
    role: str
    status: str
    applied_date: str
    notes: str


# ----- Exceptions -----

class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code: int = status_code
        self.message: str = message


class ValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=422)


class NotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


# ----- Internal Utilities -----

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    # Construct CHECK constraint for statuses
    statuses_quoted = ", ".join(f"'{s}'" for s in STATUSES)
    sql = f"""
    CREATE TABLE IF NOT EXISTS applications (
        id TEXT PRIMARY KEY,
        company TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ({statuses_quoted})),
        applied_date TEXT NOT NULL,
        notes TEXT NOT NULL
    )
    """
    conn.execute(sql)


def _row_to_application(row: sqlite3.Row) -> Application:
    return Application(
        id=row["id"],
        company=row["company"],
        role=row["role"],
        status=row["status"],
        applied_date=row["applied_date"],
        notes=row["notes"],
    )


def _today_yyyy_mm_dd() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _validate_date_str(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        raise ValidationError("applied_date must be in YYYY-MM-DD format")
    # Normalize to YYYY-MM-DD (zero-padded)
    return dt.strftime("%Y-%m-%d")


def _normalize_status(status: str) -> str:
    s = status.strip().lower()
    if s not in STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(STATUSES)}")
    return s


def _require_non_empty(value: Any, field_name: str) -> str:
    if value is None:
        raise ValidationError(f"{field_name} is required")
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    v = value.strip()
    if not v:
        raise ValidationError(f"{field_name} cannot be empty")
    return v


def _sanitize_notes(value: Optional[Any]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("notes must be a string")
    return value


def _fetch_application(conn: sqlite3.Connection, app_id: str) -> Application:
    cur = conn.execute(
        "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
        (app_id,),
    )
    row = cur.fetchone()
    if not row:
        raise NotFoundError("Application not found")
    return _row_to_application(row)


# ----- Public API -----

def get_statuses() -> Tuple[str, ...]:
    """
    Return the list of valid application statuses.
    """
    return STATUSES


def list_applications(db_path: str = "demo.db") -> List[Application]:
    """
    Retrieve all applications as a flat list.
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            "SELECT id, company, role, status, applied_date, notes "
            "FROM applications "
            "ORDER BY applied_date DESC, company ASC, role ASC"
        )
        return [_row_to_application(row) for row in cur.fetchall()]


def group_applications_by_status(db_path: str = "demo.db") -> Dict[str, List[Application]]:
    """
    Retrieve all applications grouped by status.
    Returns a dict mapping status -> list of applications.
    """
    grouped: Dict[str, List[Application]] = {s: [] for s in STATUSES}
    apps = list_applications(db_path)
    for app in apps:
        grouped[app["status"]].append(app)
    return grouped


def get_application(app_id: str, db_path: str = "demo.db") -> Application:
    """
    Retrieve a single application by ID.
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        return _fetch_application(conn, app_id)


def create_application(payload: Dict[str, Any], db_path: str = "demo.db") -> Application:
    """
    Create a new application.
    Required fields: company (str), role (str)
    Optional fields: status (defaults to 'applied'), applied_date (defaults to today), notes (defaults to '')
    """
    company = _require_non_empty(payload.get("company"), "company")
    role = _require_non_empty(payload.get("role"), "role")
    status_raw = payload.get("status", "applied")
    if not isinstance(status_raw, str):
        raise ValidationError("status must be a string")
    status = _normalize_status(status_raw)
    applied_date_val = payload.get("applied_date", _today_yyyy_mm_dd())
    if not isinstance(applied_date_val, str):
        raise ValidationError("applied_date must be a string in YYYY-MM-DD format")
    applied_date = _validate_date_str(applied_date_val)
    notes = _sanitize_notes(payload.get("notes"))

    app_id = str(uuid.uuid4())

    with _connect(db_path) as conn:
        _ensure_schema(conn)
        try:
            conn.execute(
                "INSERT INTO applications (id, company, role, status, applied_date, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (app_id, company, role, status, applied_date, notes),
            )
        except sqlite3.IntegrityError as e:
            # Should not occur normally; capture CHECK constraint failures explicitly
            raise ValidationError(f"Integrity error: {e}")
        return _fetch_application(conn, app_id)


def update_application(app_id: str, patch: Dict[str, Any], db_path: str = "demo.db") -> Application:
    """
    Partially update an application by ID.

    Allowed fields in patch: company, role, status, applied_date, notes
    """
    if not isinstance(patch, dict):
        raise ValidationError("patch must be an object")
    if not patch:
        raise ValidationError("No fields to update")

    # Validate and sanitize fields
    to_update: Dict[str, Any] = {}
    for key in patch.keys():
        if key not in {"company", "role", "status", "applied_date", "notes"}:
            raise ValidationError(f"Unknown field in update: {key}")

    if "company" in patch:
        to_update["company"] = _require_non_empty(patch.get("company"), "company")

    if "role" in patch:
        to_update["role"] = _require_non_empty(patch.get("role"), "role")

    if "status" in patch:
        status_val = patch.get("status")
        if not isinstance(status_val, str):
            raise ValidationError("status must be a string")
        to_update["status"] = _normalize_status(status_val)

    if "applied_date" in patch:
        date_val = patch.get("applied_date")
        if not isinstance(date_val, str):
            raise ValidationError("applied_date must be a string in YYYY-MM-DD format")
        to_update["applied_date"] = _validate_date_str(date_val)

    if "notes" in patch:
        to_update["notes"] = _sanitize_notes(patch.get("notes"))

    if not to_update:
        raise ValidationError("No valid fields to update")

    with _connect(db_path) as conn:
        _ensure_schema(conn)
        # Ensure existence
        _ = _fetch_application(conn, app_id)

        # Build dynamic update statement
        columns = ", ".join(f"{k} = ?" for k in to_update.keys())
        values = list(to_update.values())
        values.append(app_id)

        try:
            cur = conn.execute(
                f"UPDATE applications SET {columns} WHERE id = ?",
                values,
            )
        except sqlite3.IntegrityError as e:
            raise ValidationError(f"Integrity error: {e}")

        if cur.rowcount == 0:
            # Should not happen since we fetched above, but safeguard
            raise NotFoundError("Application not found")

        return _fetch_application(conn, app_id)


def change_status(app_id: str, new_status: str, db_path: str = "demo.db") -> Application:
    """
    Convenience function to change the status of an application.
    """
    return update_application(app_id, {"status": new_status}, db_path=db_path)


def delete_application(app_id: str, db_path: str = "demo.db") -> None:
    """
    Delete an application by ID.
    """
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        if cur.rowcount == 0:
            raise NotFoundError("Application not found")
        # Nothing to return


def validate_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform validation for a create payload without hitting the database.
    Returns a sanitized copy of the payload with defaults applied.
    """
    company = _require_non_empty(payload.get("company"), "company")
    role = _require_non_empty(payload.get("role"), "role")

    status_in = payload.get("status", "applied")
    if not isinstance(status_in, str):
        raise ValidationError("status must be a string")
    status = _normalize_status(status_in)

    applied_date_in = payload.get("applied_date", _today_yyyy_mm_dd())
    if not isinstance(applied_date_in, str):
        raise ValidationError("applied_date must be a string in YYYY-MM-DD format")
    applied_date = _validate_date_str(applied_date_in)

    notes = _sanitize_notes(payload.get("notes"))

    return {
        "company": company,
        "role": role,
        "status": status,
        "applied_date": applied_date,
        "notes": notes,
    }


def validate_update(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform validation for an update patch without hitting the database.
    Returns a sanitized patch.
    """
    if not isinstance(patch, dict):
        raise ValidationError("patch must be an object")
    if not patch:
        raise ValidationError("No fields to update")

    sanitized: Dict[str, Any] = {}
    for key in patch.keys():
        if key not in {"company", "role", "status", "applied_date", "notes"}:
            raise ValidationError(f"Unknown field in update: {key}")

    if "company" in patch:
        sanitized["company"] = _require_non_empty(patch.get("company"), "company")

    if "role" in patch:
        sanitized["role"] = _require_non_empty(patch.get("role"), "role")

    if "status" in patch:
        status_val = patch.get("status")
        if not isinstance(status_val, str):
            raise ValidationError("status must be a string")
        sanitized["status"] = _normalize_status(status_val)

    if "applied_date" in patch:
        date_val = patch.get("applied_date")
        if not isinstance(date_val, str):
            raise ValidationError("applied_date must be a string in YYYY-MM-DD format")
        sanitized["applied_date"] = _validate_date_str(date_val)

    if "notes" in patch:
        sanitized["notes"] = _sanitize_notes(patch.get("notes"))

    if not sanitized:
        raise ValidationError("No valid fields to update")

    return sanitized