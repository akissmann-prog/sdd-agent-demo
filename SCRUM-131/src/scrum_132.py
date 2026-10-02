"""
Job Application Tracker business logic module.

This module provides pure business logic for managing job applications backed by a SQLite database.
It exposes functions that map closely to typical REST endpoints (create, list with optional status filter,
get by id, update, delete) and includes validation and defaulting logic.

All functions that touch the database accept a db_path parameter and ensure the schema exists on first use.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ----- Data structures and constants ----- #

ALLOWED_STATUSES: Tuple[str, ...] = ("applied", "interviewing", "offer", "rejected")


@dataclass(frozen=True)
class Application:
    id: int
    company: str
    role: str
    status: str
    applied_date: str  # YYYY-MM-DD
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "company": self.company,
            "role": self.role,
            "status": self.status,
            "applied_date": self.applied_date,
            "notes": self.notes,
        }


# ----- Exceptions for controller-layer mapping ----- #

class ValidationError(Exception):
    """Raised when input validation fails (maps to HTTP 400)."""


class NotFoundError(Exception):
    """Raised when a requested resource is not found (maps to HTTP 404)."""


# ----- Internal helpers ----- #

def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _validate_status(value: str) -> str:
    if value not in ALLOWED_STATUSES:
        raise ValidationError(f"Invalid status '{value}'. Allowed: {', '.join(ALLOWED_STATUSES)}")
    return value


def _validate_date(value: str) -> str:
    try:
        # Validate format YYYY-MM-DD and that date is valid
        datetime.strptime(value, "%Y-%m-%d")
    except Exception as e:
        raise ValidationError("Invalid date format for 'applied_date'. Expected YYYY-MM-DD.") from e
    return value


def _validate_non_empty_str(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string.")
    if value.strip() == "":
        raise ValidationError(f"Field '{field}' cannot be empty.")
    return value


def _row_to_application(row: sqlite3.Row) -> Application:
    return Application(
        id=row["id"],
        company=row["company"],
        role=row["role"],
        status=row["status"],
        applied_date=row["applied_date"],
        notes=row["notes"],
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    # Note: Include a CHECK constraint for status consistency.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('applied','interviewing','offer','rejected')),
            applied_date TEXT NOT NULL,
            notes TEXT
        )
        """
    )


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ----- Public API functions (business logic) ----- #

def create_application(
    data: Dict[str, Any],
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    """
    Create a new application.

    Required fields: company (str), role (str)
    Optional fields: status (str, default 'applied'), applied_date (YYYY-MM-DD, default today UTC), notes (str or None)

    Returns the created record as a dict.
    Raises ValidationError on invalid input.
    """
    company = _validate_non_empty_str("company", data.get("company"))
    role = _validate_non_empty_str("role", data.get("role"))

    status = data.get("status", "applied")
    if not isinstance(status, str):
        raise ValidationError("Field 'status' must be a string.")
    status = _validate_status(status)

    applied_date = data.get("applied_date")
    if applied_date is None:
        applied_date = _utc_today_iso()
    else:
        if not isinstance(applied_date, str):
            raise ValidationError("Field 'applied_date' must be a string in YYYY-MM-DD format.")
        applied_date = _validate_date(applied_date)

    notes: Optional[str]
    if "notes" in data:
        n = data.get("notes")
        if n is None:
            notes = None
        elif isinstance(n, str):
            notes = n
        else:
            raise ValidationError("Field 'notes' must be a string or null.")
    else:
        notes = None

    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        # Schema consistency: include every column in INSERT, including id (set to NULL via None).
        cur = conn.execute(
            """
            INSERT INTO applications (id, company, role, status, applied_date, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (None, company, role, status, applied_date, notes),
        )
        new_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (new_id,),
        ).fetchone()
        assert row is not None, "Inserted row not found"
        return _row_to_application(row).to_dict()


def list_applications(
    status: Optional[str] = None,
    db_path: str = "demo.db",
) -> List[Dict[str, Any]]:
    """
    List applications. If status is provided, returns only matching records.

    Results are sorted by applied_date DESC then id DESC.
    Raises ValidationError if status is invalid.
    """
    params: Tuple[Any, ...] = ()
    where_clause = ""
    if status is not None:
        if not isinstance(status, str):
            raise ValidationError("Parameter 'status' must be a string.")
        status = _validate_status(status)
        where_clause = "WHERE status = ?"
        params = (status,)

    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT id, company, role, status, applied_date, notes
            FROM applications
            {where_clause}
            ORDER BY applied_date DESC, id DESC
            """,
            params,
        ).fetchall()
        return [_row_to_application(r).to_dict() for r in rows]


def get_application_by_id(
    app_id: int,
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    """
    Fetch a single application by its id.

    Returns the record dict.
    Raises NotFoundError if not found.
    """
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Application with id {app_id} not found.")
        return _row_to_application(row).to_dict()


def update_application(
    app_id: int,
    fields: Dict[str, Any],
    db_path: str = "demo.db",
) -> Dict[str, Any]:
    """
    Update an application with provided fields.

    Allowed fields: company (str), role (str), status (str), applied_date (YYYY-MM-DD), notes (str or None).
    At least one field must be provided, otherwise ValidationError.

    Returns the updated record dict.
    Raises NotFoundError if id not found.
    Raises ValidationError on invalid inputs.
    """
    if not isinstance(fields, dict) or len(fields) == 0:
        raise ValidationError("No fields provided to update.")

    allowed = {"company", "role", "status", "applied_date", "notes"}
    unknown = set(fields.keys()) - allowed
    if unknown:
        raise ValidationError(f"Unknown fields in update: {', '.join(sorted(unknown))}")

    updates: List[str] = []
    params: List[Any] = []

    if "company" in fields:
        company = _validate_non_empty_str("company", fields["company"])
        updates.append("company = ?")
        params.append(company)

    if "role" in fields:
        role = _validate_non_empty_str("role", fields["role"])
        updates.append("role = ?")
        params.append(role)

    if "status" in fields:
        status_val = fields["status"]
        if not isinstance(status_val, str):
            raise ValidationError("Field 'status' must be a string.")
        status_val = _validate_status(status_val)
        updates.append("status = ?")
        params.append(status_val)

    if "applied_date" in fields:
        date_val = fields["applied_date"]
        if not isinstance(date_val, str):
            raise ValidationError("Field 'applied_date' must be a string in YYYY-MM-DD format.")
        date_val = _validate_date(date_val)
        updates.append("applied_date = ?")
        params.append(date_val)

    if "notes" in fields:
        n = fields["notes"]
        if n is not None and not isinstance(n, str):
            raise ValidationError("Field 'notes' must be a string or null.")
        updates.append("notes = ?")
        params.append(n)

    if not updates:
        raise ValidationError("No valid fields provided to update.")

    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            f"UPDATE applications SET {', '.join(updates)} WHERE id = ?",
            (*params, app_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"Application with id {app_id} not found.")
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert row is not None, "Updated row not found after update"
        return _row_to_application(row).to_dict()


def delete_application(
    app_id: int,
    db_path: str = "demo.db",
) -> None:
    """
    Delete an application by id.

    Returns None on success.
    Raises NotFoundError if id not found.
    """
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"Application with id {app_id} not found.")


def group_applications_by_status(
    apps: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Utility to group applications by status for dashboard rendering.

    Returns a dict with keys: applied, interviewing, offer, rejected.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {s: [] for s in ALLOWED_STATUSES}
    for app in apps:
        s = app.get("status")
        if s in groups:
            groups[s].append(app)
        else:
            # Unknown statuses grouped under 'applied' by default, although normal validation prevents this.
            groups["applied"].append(app)
    return groups


def ensure_initialized(db_path: str = "demo.db") -> None:
    """
    Ensure the database and schema are initialized.

    This can be called at application startup to create the table if it does not exist.
    """
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)