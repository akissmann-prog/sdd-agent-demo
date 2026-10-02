"""
Business logic for managing job applications, including CRUD operations,
validation, and SQLite persistence. Intended for use by a REST layer or UI.

Data model (DTO):
- Application:
    id: int
    company: str
    role: str
    status: 'applied' | 'interviewing' | 'offer' | 'rejected'
    applied_date: ISO date string (YYYY-MM-DD)
    notes: Optional[str]

All functions that access the database accept a db_path parameter (default "demo.db").
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Iterable, List, Optional, Dict, Any, Tuple


# Status constants
STATUS_APPLIED = "applied"
STATUS_INTERVIEWING = "interviewing"
STATUS_OFFER = "offer"
STATUS_REJECTED = "rejected"
VALID_STATUSES = {STATUS_APPLIED, STATUS_INTERVIEWING, STATUS_OFFER, STATUS_REJECTED}


# Exceptions
class AppError(Exception):
    """Base exception for application module."""


class ValidationError(AppError):
    """Raised when validation fails."""


class NotFoundError(AppError):
    """Raised when a record is not found."""


@dataclass(frozen=True)
class Application:
    """Data Transfer Object for an application."""
    id: int
    company: str
    role: str
    status: str
    applied_date: str  # ISO date (YYYY-MM-DD)
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Utilities
def today_iso() -> str:
    """Return today's date in ISO format YYYY-MM-DD."""
    return date.today().isoformat()


def _is_valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Trim whitespace; return None if empty or None."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def validate_status(status: str) -> str:
    """
    Normalize and validate a status value.
    Accepts case-insensitive values; returns normalized lowercase status.
    """
    if status is None:
        raise ValidationError("Status is required.")
    normalized = status.strip().lower()
    if normalized not in VALID_STATUSES:
        raise ValidationError(f"Invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}")
    return normalized


def validate_application_fields(
    company: Optional[str],
    role: Optional[str],
    status: Optional[str],
    applied_date: Optional[str],
    for_update: bool = False,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Validate application fields. For creation, company and role required. For update, fields
    may be None to indicate 'no change'. Returns sanitized (company, role, status, applied_date).
    Raises ValidationError on invalid input.
    """
    s_company = sanitize_text(company) if company is not None or not for_update else None
    s_role = sanitize_text(role) if role is not None or not for_update else None

    if not for_update:
        if s_company is None:
            raise ValidationError("Company is required.")
        if s_role is None:
            raise ValidationError("Role is required.")
    else:
        if company is not None and s_company is None:
            raise ValidationError("Company cannot be empty.")
        if role is not None and s_role is None:
            raise ValidationError("Role cannot be empty.")

    s_status = None
    if status is not None:
        s_status = validate_status(status)

    s_applied_date = None
    if applied_date is not None:
        if not _is_valid_iso_date(applied_date):
            raise ValidationError("applied_date must be in YYYY-MM-DD format.")
        s_applied_date = applied_date

    return s_company, s_role, s_status, s_applied_date


# Database helpers
def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Create tables on first use. Includes a constraint on status and ISO date stored as TEXT.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('applied','interviewing','offer','rejected')),
            applied_date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);")
    conn.commit()


def _row_to_application(row: sqlite3.Row) -> Application:
    return Application(
        id=int(row["id"]),
        company=row["company"],
        role=row["role"],
        status=row["status"],
        applied_date=row["applied_date"],
        notes=row["notes"],
    )


# CRUD operations
def list_applications(
    db_path: str = "demo.db",
    order_by: str = "applied_date",
    descending: bool = True,
) -> List[Application]:
    """
    Return all applications, ordered by the specified column (default applied_date desc).
    Allowed order_by values: id, company, role, status, applied_date, created_at, updated_at.
    """
    allowed = {"id", "company", "role", "status", "applied_date", "created_at", "updated_at"}
    ob = order_by if order_by in allowed else "applied_date"
    direction = "DESC" if descending else "ASC"

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT id, company, role, status, applied_date, notes FROM applications ORDER BY {ob} {direction}, id DESC"
        ).fetchall()
    return [_row_to_application(r) for r in rows]


def get_application(app_id: int, db_path: str = "demo.db") -> Application:
    """Fetch a single application by id."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    if row is None:
        raise NotFoundError(f"Application id {app_id} not found.")
    return _row_to_application(row)


def add_application(
    company: str,
    role: str,
    status: Optional[str] = None,
    applied_date: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: str = "demo.db",
) -> Application:
    """
    Create a new application. Company and role are required.
    Status defaults to 'applied' when omitted.
    applied_date defaults to today's date (YYYY-MM-DD) when omitted.
    """
    s_company, s_role, s_status, s_applied_date = validate_application_fields(
        company=company, role=role, status=status, applied_date=applied_date, for_update=False
    )

    normalized_status = s_status if s_status is not None else STATUS_APPLIED
    normalized_date = s_applied_date if s_applied_date is not None else today_iso()
    if not _is_valid_iso_date(normalized_date):
        # Should not happen due to defaults, but double-check
        raise ValidationError("applied_date must be in YYYY-MM-DD format.")

    s_notes = sanitize_text(notes)

    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO applications (company, role, status, applied_date, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (s_company, s_role, normalized_status, normalized_date, s_notes),
        )
        new_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (new_id,),
        ).fetchone()
    return _row_to_application(row)


def update_application(
    app_id: int,
    company: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    applied_date: Optional[str] = None,
    notes: Optional[Optional[str]] = None,
    db_path: str = "demo.db",
) -> Application:
    """
    Update fields of an application. Provide only the fields to change.
    To clear notes, pass notes="" (will store NULL).
    """
    if all(v is None for v in (company, role, status, applied_date, notes)):
        raise ValidationError("No fields provided for update.")

    s_company, s_role, s_status, s_applied_date = validate_application_fields(
        company=company, role=role, status=status, applied_date=applied_date, for_update=True
    )

    set_parts: List[str] = []
    params: List[Any] = []

    if company is not None:
        set_parts.append("company = ?")
        params.append(s_company)
    if role is not None:
        set_parts.append("role = ?")
        params.append(s_role)
    if status is not None:
        set_parts.append("status = ?")
        params.append(s_status)
    if applied_date is not None:
        if s_applied_date is None or not _is_valid_iso_date(s_applied_date):
            raise ValidationError("applied_date must be in YYYY-MM-DD format.")
        set_parts.append("applied_date = ?")
        params.append(s_applied_date)
    if notes is not None:
        # Allow clearing notes by passing empty string -> becomes NULL
        set_parts.append("notes = ?")
        params.append(sanitize_text(notes))

    set_parts.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')")

    sql = f"UPDATE applications SET {', '.join(set_parts)} WHERE id = ?"
    params.append(app_id)

    with _connect(db_path) as conn:
        cur = conn.execute(sql, tuple(params))
        if cur.rowcount == 0:
            raise NotFoundError(f"Application id {app_id} not found.")
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    return _row_to_application(row)


def set_application_status(app_id: int, status: str, db_path: str = "demo.db") -> Application:
    """Update only the status of an application."""
    normalized_status = validate_status(status)
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE applications
            SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE id = ?
            """,
            (normalized_status, app_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"Application id {app_id} not found.")
        row = conn.execute(
            "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    return _row_to_application(row)


def delete_application(app_id: int, db_path: str = "demo.db") -> None:
    """Delete an application by id."""
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"Application id {app_id} not found.")


# Grouping helpers for UI use
def group_applications_by_status(applications: Iterable[Application]) -> Dict[str, List[Application]]:
    """
    Group applications by status, ensuring keys for all known statuses exist.
    Unknown statuses (should not occur) are grouped under 'other'.
    """
    groups: Dict[str, List[Application]] = {
        STATUS_APPLIED: [],
        STATUS_INTERVIEWING: [],
        STATUS_OFFER: [],
        STATUS_REJECTED: [],
    }
    other: List[Application] = []
    for app in applications:
        if app.status in groups:
            groups[app.status].append(app)
        else:
            other.append(app)
    if other:
        groups["other"] = other
    return groups


# Convenience: bulk set from list of dicts (e.g., for tests or seeding)
def bulk_insert_applications(
    items: Iterable[Dict[str, Any]],
    db_path: str = "demo.db",
) -> List[Application]:
    """
    Insert multiple applications. Each item may include company, role, status, applied_date, notes.
    Missing status defaults to 'applied'; missing applied_date defaults to today.
    Returns the created Application objects.
    """
    created: List[Application] = []
    with _connect(db_path) as conn:
        for item in items:
            company = item.get("company")
            role = item.get("role")
            status = item.get("status")
            applied_date = item.get("applied_date")
            notes = item.get("notes")

            s_company, s_role, s_status, s_applied_date = validate_application_fields(
                company=company, role=role, status=status, applied_date=applied_date, for_update=False
            )
            normalized_status = s_status if s_status is not None else STATUS_APPLIED
            normalized_date = s_applied_date if s_applied_date is not None else today_iso()
            s_notes = sanitize_text(notes)

            cur = conn.execute(
                """
                INSERT INTO applications (company, role, status, applied_date, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (s_company, s_role, normalized_status, normalized_date, s_notes),
            )
            new_id = cur.lastrowid
            row = conn.execute(
                "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
                (new_id,),
            ).fetchone()
            created.append(_row_to_application(row))
    return created


# Error mapping helper for UI consumers
def error_to_message(err: Exception) -> str:
    """Map exceptions to user-friendly messages."""
    if isinstance(err, ValidationError):
        return str(err)
    if isinstance(err, NotFoundError):
        return str(err)
    if isinstance(err, sqlite3.IntegrityError):
        # Likely status constraint or NOT NULL violation
        return "Data integrity error. Please check your inputs."
    return "An unexpected error occurred."