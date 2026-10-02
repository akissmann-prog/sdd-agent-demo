"""
Business logic for managing job applications with SQLite persistence.

This module provides pure functions to create, read, update, delete, and filter job
applications stored in a SQLite database. It performs input validation, applies defaults,
and uses parameterized SQL queries. All functions that interact with the database accept
a db_path parameter to specify the SQLite file.

No web framework or HTTP handling is included; exceptions are provided to allow a web
layer to translate them into appropriate HTTP responses.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, TypedDict, Literal


ALLOWED_STATUSES: List[str] = ["applied", "interviewing", "offer", "rejected"]


class ApplicationRecord(TypedDict):
    id: int
    company: str
    role: str
    status: Literal["applied", "interviewing", "offer", "rejected"]
    applied_date: str
    notes: Optional[str]


class ErrorDetail(TypedDict):
    field: str
    error: str


class ErrorResponse(TypedDict, total=False):
    message: str
    details: List[ErrorDetail]


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, details: Optional[List[ErrorDetail]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.details = details or []

    def to_error_response(self) -> ErrorResponse:
        payload: ErrorResponse = {"message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class BadRequestError(ApiError):
    def __init__(self, message: str, details: Optional[List[ErrorDetail]] = None) -> None:
        super().__init__(400, message, details)


class NotFoundError(ApiError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(404, message, [])


def init_db(db_path: str = "demo.db") -> None:
    """
    Initialize the SQLite database, creating the applications table and index if they do not exist.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
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


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _row_to_application(row: sqlite3.Row) -> ApplicationRecord:
    return ApplicationRecord(
        id=int(row["id"]),
        company=str(row["company"]),
        role=str(row["role"]),
        status=str(row["status"]),  # constrained in DB/validation
        applied_date=str(row["applied_date"]),
        notes=row["notes"] if row["notes"] is not None else None,
    )


def _validate_non_empty_string(value: Any, field: str, required: bool, errors: List[ErrorDetail]) -> Optional[str]:
    if value is None:
        if required:
            errors.append({"field": field, "error": "This field is required."})
        return None
    if not isinstance(value, str):
        errors.append({"field": field, "error": "Must be a string."})
        return None
    trimmed = value.strip()
    if trimmed == "":
        errors.append({"field": field, "error": "Must be a non-empty string."})
        return None
    return trimmed


def _validate_status(value: Any, field: str, required: bool, errors: List[ErrorDetail]) -> Optional[str]:
    if value is None:
        if required:
            errors.append({"field": field, "error": "This field is required."})
        return None
    if not isinstance(value, str):
        errors.append({"field": field, "error": "Must be a string."})
        return None
    normalized = value.strip().lower()
    if normalized not in ALLOWED_STATUSES:
        errors.append({"field": field, "error": f"Must be one of {', '.join(ALLOWED_STATUSES)}."})
        return None
    return normalized


def _validate_date_yyyy_mm_dd(value: Any, field: str, required: bool, errors: List[ErrorDetail]) -> Optional[str]:
    if value is None:
        if required:
            errors.append({"field": field, "error": "This field is required."})
        return None
    if not isinstance(value, str):
        errors.append({"field": field, "error": "Must be a string in YYYY-MM-DD format."})
        return None
    try:
        # Allow only date portion; date.fromisoformat enforces valid calendar date
        parsed = date.fromisoformat(value)
        return parsed.isoformat()
    except Exception:
        errors.append({"field": field, "error": "Must be a valid date in YYYY-MM-DD format."})
        return None


def _validate_notes(value: Any, field: str, errors: List[ErrorDetail]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append({"field": field, "error": "Must be a string or null."})
        return None
    # notes can be empty string
    return value


def create_application(payload: Mapping[str, Any], db_path: str = "demo.db") -> ApplicationRecord:
    """
    Create a new application record after validating input and applying defaults.

    Required fields:
      - company: non-empty string
      - role: non-empty string
    Optional fields:
      - status: one of applied|interviewing|offer|rejected (defaults to 'applied')
      - applied_date: YYYY-MM-DD (defaults to today's date)
      - notes: optional string or null

    Returns the created ApplicationRecord including its id.
    """
    init_db(db_path)

    if not isinstance(payload, Mapping):
        raise BadRequestError("Invalid input.", [{"field": "body", "error": "Must be a JSON object."}])

    errors: List[ErrorDetail] = []

    company = _validate_non_empty_string(payload.get("company"), "company", required=True, errors=errors)
    role = _validate_non_empty_string(payload.get("role"), "role", required=True, errors=errors)

    raw_status = payload.get("status", "applied")
    status = _validate_status(raw_status, "status", required=True, errors=errors)

    raw_date = payload.get("applied_date", date.today().isoformat())
    applied_date = _validate_date_yyyy_mm_dd(raw_date, "applied_date", required=True, errors=errors)

    notes = _validate_notes(payload.get("notes"), "notes", errors=errors)

    if errors:
        raise BadRequestError("Invalid input.", errors)

    with _get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO applications (company, role, status, applied_date, notes)
            VALUES (?, ?, ?, ?, ?);
            """,
            (company, role, status, applied_date, notes),
        )
        new_id = int(cur.lastrowid)
        cur2 = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?;",
            (new_id,),
        )
        row = cur2.fetchone()
        assert row is not None
        return _row_to_application(row)


def list_applications(status: Optional[str] = None, db_path: str = "demo.db") -> List[ApplicationRecord]:
    """
    List applications, optionally filtered by status.

    - If status is provided, it must be one of the allowed statuses (case-insensitive).
      Invalid status causes a BadRequestError.
    """
    init_db(db_path)

    query = "SELECT id, company, role, status, applied_date, notes FROM applications"
    params: List[Any] = []

    if status is not None:
        errors: List[ErrorDetail] = []
        normalized_status = _validate_status(status, "status", required=True, errors=errors)
        if errors or normalized_status is None:
            raise BadRequestError("Invalid status filter.", errors)
        query += " WHERE status = ?"
        params.append(normalized_status)

    query += " ORDER BY applied_date DESC, id DESC"

    with _get_connection(db_path) as conn:
        cur = conn.execute(query + ";", tuple(params))
        rows = cur.fetchall()
        return [_row_to_application(r) for r in rows]


def get_application(app_id: int, db_path: str = "demo.db") -> ApplicationRecord:
    """
    Retrieve a single application by id. Raises NotFoundError if not found.
    """
    init_db(db_path)

    with _get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?;",
            (app_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFoundError("Application not found.")
        return _row_to_application(row)


def update_application(app_id: int, updates: Mapping[str, Any], db_path: str = "demo.db") -> ApplicationRecord:
    """
    Update an application by id with partial or full fields.

    Allowed fields to update: company, role, status, applied_date, notes.
    - company/role: non-empty strings (if provided)
    - status: one of allowed statuses (if provided)
    - applied_date: valid YYYY-MM-DD (if provided)
    - notes: string or null (if provided)

    Returns the updated ApplicationRecord, or raises NotFoundError if the id does not exist.
    """
    init_db(db_path)

    # Ensure the record exists first
    with _get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?;",
            (app_id,),
        )
        existing = cur.fetchone()
        if existing is None:
            raise NotFoundError("Application not found.")

        if not isinstance(updates, Mapping):
            raise BadRequestError("Invalid input.", [{"field": "body", "error": "Must be a JSON object."}])

        errors: List[ErrorDetail] = []

        payload: Dict[str, Any] = {}

        if "company" in updates:
            company = _validate_non_empty_string(updates.get("company"), "company", required=True, errors=errors)
            if company is not None:
                payload["company"] = company

        if "role" in updates:
            role = _validate_non_empty_string(updates.get("role"), "role", required=True, errors=errors)
            if role is not None:
                payload["role"] = role

        if "status" in updates:
            status = _validate_status(updates.get("status"), "status", required=True, errors=errors)
            if status is not None:
                payload["status"] = status

        if "applied_date" in updates:
            applied_date = _validate_date_yyyy_mm_dd(updates.get("applied_date"), "applied_date", required=True, errors=errors)
            if applied_date is not None:
                payload["applied_date"] = applied_date

        if "notes" in updates:
            before = len(errors)
            notes = _validate_notes(updates.get("notes"), "notes", errors=errors)
            if len(errors) == before:
                payload["notes"] = notes

        # If no allowed fields provided, simply return the existing record
        if not payload and not errors:
            return _row_to_application(existing)

        if errors:
            raise BadRequestError("Invalid input.", errors)

        # Build dynamic update statement
        set_clauses = ", ".join(f"{col} = ?" for col in payload.keys())
        params: List[Any] = list(payload.values()) + [app_id]

        conn.execute(f"UPDATE applications SET {set_clauses} WHERE id = ?;", params)

        cur2 = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?;",
            (app_id,),
        )
        row = cur2.fetchone()
        assert row is not None
        return _row_to_application(row)


def delete_application(app_id: int, db_path: str = "demo.db") -> None:
    """
    Delete an application by id. Raises NotFoundError if the id does not exist.
    """
    init_db(db_path)

    with _get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM applications WHERE id = ?;", (app_id,))
        if cur.rowcount == 0:
            raise NotFoundError("Application not found.")