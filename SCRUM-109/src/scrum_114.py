"""
Business logic module for managing job applications with SQLite persistence.

This module implements CRUD operations and status grouping for applications,
including server-side validation and sensible defaults:

- Applications have fields: id, company, role, status, applied_date, notes.
- Status is one of: applied, interviewing, offer, rejected.
- Create defaults: status="applied", applied_date=today (YYYY-MM-DD) when omitted.
- Update supports partial updates with field validation.
- Data is stored in SQLite; tables are created on first use.

All functions that access the database accept a db_path parameter to specify the
SQLite database file, defaulting to "demo.db".

No external dependencies.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


ALLOWED_STATUSES: Tuple[str, ...] = ("applied", "interviewing", "offer", "rejected")
DEFAULT_DB_PATH = "demo.db"

# Field constraints
MAX_COMPANY_LEN = 255
MAX_ROLE_LEN = 255
MAX_NOTES_LEN = 2000


class ValidationError(Exception):
    """Raised when input fails validation with per-field error messages."""

    def __init__(self, message: str, field_errors: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_errors: Dict[str, str] = field_errors or {}


class NotFoundError(Exception):
    """Raised when an entity is not found by the provided identifier."""
    pass


@dataclass(frozen=True)
class Application:
    """Immutable representation of an application record."""
    id: int
    company: str
    role: str
    status: str
    applied_date: str  # YYYY-MM-DD
    notes: Optional[str]
    created_at: str  # ISO 8601 datetime
    updated_at: str  # ISO 8601 datetime


def get_allowed_statuses() -> Tuple[str, ...]:
    """Return the tuple of allowed statuses."""
    return ALLOWED_STATUSES


def get_applications(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Return all applications as a list of dicts, ordered by applied_date DESC then id DESC.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT id, company, role, status, applied_date, notes, created_at, updated_at
            FROM applications
            ORDER BY applied_date DESC, id DESC
            """
        )
        rows = cur.fetchall()
    return [_row_to_dict(row) for row in rows]


def group_applications_by_status(db_path: str = DEFAULT_DB_PATH) -> Dict[str, List[Dict[str, Any]]]:
    """
    Return applications grouped by status as a dict with all allowed statuses as keys.
    Each list is ordered by applied_date DESC then id DESC.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {s: [] for s in ALLOWED_STATUSES}
    for app in get_applications(db_path=db_path):
        status = app["status"]
        if status in grouped:
            grouped[status].append(app)
        else:
            # In case older data has unexpected statuses; place under 'applied' as fallback
            grouped.setdefault("applied", []).append(app)
    return grouped


def get_application_by_id(app_id: int, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Fetch a single application by id. Raises NotFoundError if not found.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT id, company, role, status, applied_date, notes, created_at, updated_at
            FROM applications
            WHERE id = ?
            """,
            (app_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise NotFoundError(f"Application with id={app_id} not found")
    return _row_to_dict(row)


def create_application(data: Mapping[str, Any], db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Create a new application and return it as a dict.

    Defaults:
    - If status is omitted or empty, defaults to 'applied'.
    - If applied_date is omitted or empty, defaults to today's date (YYYY-MM-DD).
    """
    valid = _validate_and_normalize_create(data)
    now = _now_iso()
    with _connect(db_path) as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO applications (company, role, status, applied_date, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    valid["company"],
                    valid["role"],
                    valid["status"],
                    valid["applied_date"],
                    valid.get("notes"),
                    now,
                    now,
                ),
            )
            app_id = cur.lastrowid
        except sqlite3.IntegrityError as e:
            # Fallback, though we validate beforehand
            raise ValidationError("Integrity error while creating application") from e

        # Fetch and return the inserted record
        cur = conn.execute(
            """
            SELECT id, company, role, status, applied_date, notes, created_at, updated_at
            FROM applications
            WHERE id = ?
            """,
            (app_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return _row_to_dict(row)


def update_application(app_id: int, data: Mapping[str, Any], db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Update an existing application with provided fields and return the updated record.

    Supports partial updates. Raises:
    - NotFoundError if the application does not exist.
    - ValidationError for invalid inputs or when no valid fields provided.
    """
    if not isinstance(app_id, int):
        raise ValidationError("Invalid id", {"id": "id must be an integer"})
    valid_updates = _validate_and_normalize_update(data)

    if not valid_updates:
        raise ValidationError("No valid fields to update")

    # Ensure the record exists before updating
    _ensure_exists(app_id, db_path=db_path)

    assignments: List[str] = []
    params: List[Any] = []
    for field in ("company", "role", "status", "applied_date", "notes"):
        if field in valid_updates:
            assignments.append(f"{field} = ?")
            params.append(valid_updates[field])

    assignments.append("updated_at = ?")
    params.append(_now_iso())

    params.append(app_id)

    with _connect(db_path) as conn:
        try:
            conn.execute(
                f"""
                UPDATE applications
                SET {", ".join(assignments)}
                WHERE id = ?
                """,
                params,
            )
        except sqlite3.IntegrityError as e:
            raise ValidationError("Integrity error while updating application") from e

        cur = conn.execute(
            """
            SELECT id, company, role, status, applied_date, notes, created_at, updated_at
            FROM applications
            WHERE id = ?
            """,
            (app_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return _row_to_dict(row)


def change_application_status(app_id: int, status: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Change the status of an application and return the updated record.
    """
    updates: Dict[str, Any] = {"status": status}
    return update_application(app_id, updates, db_path=db_path)


def delete_application(app_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Delete an application by id. Raises NotFoundError if not found.
    """
    if not isinstance(app_id, int):
        raise ValidationError("Invalid id", {"id": "id must be an integer"})

    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"Application with id={app_id} not found")


# Internal helpers


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    statuses_sql = ", ".join(f"'{s}'" for s in ALLOWED_STATUSES)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({statuses_sql})),
            applied_date TEXT NOT NULL, -- YYYY-MM-DD
            notes TEXT,
            created_at TEXT NOT NULL, -- ISO 8601 datetime
            updated_at TEXT NOT NULL  -- ISO 8601 datetime
        )
        """
    )
    # Useful indexes for common queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_applied_date ON applications(applied_date)")


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "company": row["company"],
        "role": row["role"],
        "status": row["status"],
        "applied_date": row["applied_date"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _ensure_exists(app_id: int, db_path: str) -> None:
    with _connect(db_path) as conn:
        cur = conn.execute("SELECT 1 FROM applications WHERE id = ?", (app_id,))
        if cur.fetchone() is None:
            raise NotFoundError(f"Application with id={app_id} not found")


def _now_iso() -> str:
    # UTC ISO 8601 format with 'Z'
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_and_validate_date(value: str, field_name: str, errors: Dict[str, str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    try:
        if not value:
            return None
        # Expect YYYY-MM-DD
        parsed = date.fromisoformat(value)
        return parsed.isoformat()
    except Exception:
        errors[field_name] = f"{field_name} must be in YYYY-MM-DD format"
        return None


def _normalize_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().lower()
    else:
        value = str(value).strip().lower()
    return value or None


def _validate_and_normalize_create(data: Mapping[str, Any]) -> Dict[str, Any]:
    errors: Dict[str, str] = {}
    normalized: Dict[str, Any] = {}

    # company
    company_raw = data.get("company")
    if company_raw is None:
        errors["company"] = "Company is required"
    else:
        company = str(company_raw).strip()
        if not company:
            errors["company"] = "Company is required"
        elif len(company) > MAX_COMPANY_LEN:
            errors["company"] = f"Company must be at most {MAX_COMPANY_LEN} characters"
        else:
            normalized["company"] = company

    # role
    role_raw = data.get("role")
    if role_raw is None:
        errors["role"] = "Role is required"
    else:
        role = str(role_raw).strip()
        if not role:
            errors["role"] = "Role is required"
        elif len(role) > MAX_ROLE_LEN:
            errors["role"] = f"Role must be at most {MAX_ROLE_LEN} characters"
        else:
            normalized["role"] = role

    # status (default to 'applied' if missing or empty)
    status = _normalize_status(data.get("status"))
    if status is None or status == "":
        status = "applied"
    if status not in ALLOWED_STATUSES:
        errors["status"] = f"Status must be one of: {', '.join(ALLOWED_STATUSES)}"
    else:
        normalized["status"] = status

    # applied_date (default to today if missing or empty)
    applied_date_raw = data.get("applied_date")
    if applied_date_raw is None or (isinstance(applied_date_raw, str) and applied_date_raw.strip() == ""):
        normalized["applied_date"] = date.today().isoformat()
    else:
        parsed_date = _parse_and_validate_date(str(applied_date_raw), "applied_date", errors)
        if parsed_date:
            normalized["applied_date"] = parsed_date

    # notes (optional)
    notes_raw = data.get("notes")
    if notes_raw is None:
        normalized["notes"] = None
    else:
        notes = str(notes_raw)
        if len(notes) > MAX_NOTES_LEN:
            errors["notes"] = f"Notes must be at most {MAX_NOTES_LEN} characters"
        else:
            normalized["notes"] = notes

    if errors:
        raise ValidationError("Invalid input", errors)
    return normalized


def _validate_and_normalize_update(data: Mapping[str, Any]) -> Dict[str, Any]:
    errors: Dict[str, str] = {}
    normalized: Dict[str, Any] = {}

    if "company" in data:
        company = str(data.get("company") if data.get("company") is not None else "").strip()
        if not company:
            errors["company"] = "Company is required"
        elif len(company) > MAX_COMPANY_LEN:
            errors["company"] = f"Company must be at most {MAX_COMPANY_LEN} characters"
        else:
            normalized["company"] = company

    if "role" in data:
        role = str(data.get("role") if data.get("role") is not None else "").strip()
        if not role:
            errors["role"] = "Role is required"
        elif len(role) > MAX_ROLE_LEN:
            errors["role"] = f"Role must be at most {MAX_ROLE_LEN} characters"
        else:
            normalized["role"] = role

    if "status" in data:
        status = _normalize_status(data.get("status"))
        if status is None or status == "":
            errors["status"] = "Status is required"
        elif status not in ALLOWED_STATUSES:
            errors["status"] = f"Status must be one of: {', '.join(ALLOWED_STATUSES)}"
        else:
            normalized["status"] = status

    if "applied_date" in data:
        applied_date_value = data.get("applied_date")
        if applied_date_value is None or (isinstance(applied_date_value, str) and applied_date_value.strip() == ""):
            errors["applied_date"] = "applied_date is required"
        else:
            parsed_date = _parse_and_validate_date(str(applied_date_value), "applied_date", errors)
            if parsed_date:
                normalized["applied_date"] = parsed_date

    if "notes" in data:
        notes_raw = data.get("notes")
        # Allow clearing notes to empty string
        if notes_raw is None:
            normalized["notes"] = None
        else:
            notes = str(notes_raw)
            if len(notes) > MAX_NOTES_LEN:
                errors["notes"] = f"Notes must be at most {MAX_NOTES_LEN} characters"
            else:
                normalized["notes"] = notes

    if errors:
        raise ValidationError("Invalid input", errors)
    return normalized