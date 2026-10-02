"""
Persistence and validation module for tracking job applications.

This module provides:
- SQLite schema management with constraints and defaults.
- Validation for create and update operations.
- Repository functions for CRUD operations with parameterized SQL.
- Controller-like functions that return (status_code, json_body) tuples.

All dates are stored as ISO-8601 YYYY-MM-DD strings.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ALLOWED_STATUSES = ("applied", "interviewing", "offer", "rejected")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


class SchemaManager:
    @staticmethod
    def ensure_schema(db_path: str = "demo.db") -> None:
        with _connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL CHECK(trim(company) <> ''),
                    role TEXT NOT NULL CHECK(trim(role) <> ''),
                    status TEXT NOT NULL DEFAULT 'applied' CHECK(status IN ('applied','interviewing','offer','rejected')),
                    applied_date TEXT NOT NULL DEFAULT CURRENT_DATE CHECK(applied_date GLOB '____-__-__'),
                    notes TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)"
            )
            conn.commit()


class DateUtil:
    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    @staticmethod
    def is_valid_date_yyyy_mm_dd(value: str) -> bool:
        if not isinstance(value, str):
            return False
        if not DateUtil.DATE_RE.match(value):
            return False
        try:
            # Validate actual calendar date
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False


class ApplicationValidator:
    ALLOWED_FIELDS = {"company", "role", "status", "applied_date", "notes"}

    @staticmethod
    def _validate_common(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        errors: Dict[str, Any] = {}
        sanitized: Dict[str, Any] = {}
        unknown_fields: List[str] = []

        # Unknown fields
        for key in data.keys():
            if key not in ApplicationValidator.ALLOWED_FIELDS:
                unknown_fields.append(key)

        # company (optional here; required in create)
        if "company" in data:
            v = data.get("company")
            if not isinstance(v, str):
                errors["company"] = "must be a string"
            else:
                v2 = v.strip()
                if v2 == "":
                    errors["company"] = "must be a non-empty string"
                else:
                    sanitized["company"] = v2

        # role (optional here; required in create)
        if "role" in data:
            v = data.get("role")
            if not isinstance(v, str):
                errors["role"] = "must be a string"
            else:
                v2 = v.strip()
                if v2 == "":
                    errors["role"] = "must be a non-empty string"
                else:
                    sanitized["role"] = v2

        # status
        if "status" in data:
            v = data.get("status")
            if not isinstance(v, str):
                errors["status"] = "must be a string"
            else:
                v2 = v.strip().lower()
                if v2 not in ALLOWED_STATUSES:
                    errors["status"] = f"must be one of {ALLOWED_STATUSES}"
                else:
                    sanitized["status"] = v2

        # applied_date
        if "applied_date" in data:
            v = data.get("applied_date")
            if not isinstance(v, str):
                errors["applied_date"] = "must be a string in YYYY-MM-DD format"
            else:
                if not DateUtil.is_valid_date_yyyy_mm_dd(v):
                    errors["applied_date"] = "must be a valid date in YYYY-MM-DD format"
                else:
                    sanitized["applied_date"] = v

        # notes (nullable)
        if "notes" in data:
            v = data.get("notes")
            if v is None:
                sanitized["notes"] = None
            elif isinstance(v, str):
                sanitized["notes"] = v
            else:
                errors["notes"] = "must be a string or null"

        return sanitized, errors, unknown_fields

    @staticmethod
    def validate_create(data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        sanitized, errors, unknown = ApplicationValidator._validate_common(data)

        # Required fields: company, role
        if "company" not in sanitized and "company" not in errors:
            errors["company"] = "is required"
        if "role" not in sanitized and "role" not in errors:
            errors["role"] = "is required"

        if unknown:
            errors["unknown"] = sorted(unknown)

        if errors:
            return None, errors
        return sanitized, {}

    @staticmethod
    def validate_update(data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        sanitized, errors, unknown = ApplicationValidator._validate_common(data)

        if unknown:
            errors["unknown"] = sorted(unknown)

        if not sanitized and not errors:
            errors["non_field"] = "no updatable fields provided"

        if errors:
            return None, errors
        return sanitized, {}

    @staticmethod
    def validate_status_filter(status: Optional[str]) -> Tuple[Optional[str], Dict[str, Any]]:
        if status is None:
            return None, {}
        if not isinstance(status, str):
            return None, {"status": "must be a string"}
        s = status.strip().lower()
        if s not in ALLOWED_STATUSES:
            return None, {"status": f"must be one of {ALLOWED_STATUSES}"}
        return s, {}


class ApplicationRepo:
    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "company": row["company"],
            "role": row["role"],
            "status": row["status"],
            "applied_date": row["applied_date"],
            "notes": row["notes"],
        }

    @staticmethod
    def create(data: Dict[str, Any], db_path: str = "demo.db") -> Dict[str, Any]:
        SchemaManager.ensure_schema(db_path)
        with _connect(db_path) as conn:
            cur = conn.cursor()

            # Build dynamic INSERT specifying only provided columns
            columns: List[str] = ["company", "role"]
            params: List[Any] = [data["company"], data["role"]]

            if "status" in data:
                columns.append("status")
                params.append(data["status"])
            if "applied_date" in data:
                columns.append("applied_date")
                params.append(data["applied_date"])
            if "notes" in data:
                columns.append("notes")
                params.append(data["notes"])

            placeholders = ", ".join(["?"] * len(columns))
            sql = f"INSERT INTO applications ({', '.join(columns)}) VALUES ({placeholders})"
            cur.execute(sql, tuple(params))
            new_id = cur.lastrowid

            # Fetch created row
            cur.execute(
                "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
                (new_id,),
            )
            row = cur.fetchone()
            if not row:
                raise sqlite3.DatabaseError("Failed to retrieve created application")
            conn.commit()
            return ApplicationRepo._row_to_dict(row)

    @staticmethod
    def list_all(filter_status: Optional[str] = None, db_path: str = "demo.db") -> List[Dict[str, Any]]:
        SchemaManager.ensure_schema(db_path)
        with _connect(db_path) as conn:
            cur = conn.cursor()
            if filter_status is None:
                cur.execute(
                    "SELECT id, company, role, status, applied_date, notes FROM applications ORDER BY id ASC"
                )
                rows = cur.fetchall()
            else:
                cur.execute(
                    "SELECT id, company, role, status, applied_date, notes FROM applications WHERE status = ? ORDER BY id ASC",
                    (filter_status,),
                )
                rows = cur.fetchall()
            return [ApplicationRepo._row_to_dict(r) for r in rows]

    @staticmethod
    def get_by_id(app_id: int, db_path: str = "demo.db") -> Optional[Dict[str, Any]]:
        SchemaManager.ensure_schema(db_path)
        with _connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
                (app_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return ApplicationRepo._row_to_dict(row)

    @staticmethod
    def update(app_id: int, data: Dict[str, Any], db_path: str = "demo.db") -> Optional[Dict[str, Any]]:
        SchemaManager.ensure_schema(db_path)
        with _connect(db_path) as conn:
            cur = conn.cursor()
            sets: List[str] = []
            params: List[Any] = []

            for field in ("company", "role", "status", "applied_date", "notes"):
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            if not sets:
                return ApplicationRepo.get_by_id(app_id, db_path)  # No-op; should not happen due to validation

            params.append(app_id)
            sql = f"UPDATE applications SET {', '.join(sets)} WHERE id = ?"
            cur.execute(sql, tuple(params))
            if cur.rowcount == 0:
                return None

            cur.execute(
                "SELECT id, company, role, status, applied_date, notes FROM applications WHERE id = ?",
                (app_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            conn.commit()
            return ApplicationRepo._row_to_dict(row)

    @staticmethod
    def delete(app_id: int, db_path: str = "demo.db") -> bool:
        SchemaManager.ensure_schema(db_path)
        with _connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted


def _error_response(status_code: int, error: str, details: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    body: Dict[str, Any] = {"error": error}
    if details:
        body["details"] = details
    return status_code, body


def create_application(payload: Dict[str, Any], db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    data, errors = ApplicationValidator.validate_create(payload or {})
    if errors:
        return _error_response(400, "Bad Request", errors)
    try:
        entity = ApplicationRepo.create(data, db_path=db_path)
    except sqlite3.IntegrityError as e:
        return _error_response(400, "Bad Request", {"db": f"constraint violation: {str(e)}"})
    except sqlite3.DatabaseError as e:
        return _error_response(500, "Internal Server Error", {"db": str(e)})
    return 201, {"data": entity}


def list_applications(status: Optional[str] = None, db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    s, errors = ApplicationValidator.validate_status_filter(status)
    if errors:
        return _error_response(400, "Bad Request", errors)
    try:
        items = ApplicationRepo.list_all(filter_status=s, db_path=db_path)
    except sqlite3.DatabaseError as e:
        return _error_response(500, "Internal Server Error", {"db": str(e)})
    return 200, {"data": items}


def get_application(app_id: int, db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    try:
        entity = ApplicationRepo.get_by_id(app_id, db_path=db_path)
    except sqlite3.DatabaseError as e:
        return _error_response(500, "Internal Server Error", {"db": str(e)})
    if not entity:
        return _error_response(404, "Not Found")
    return 200, {"data": entity}


def update_application(app_id: int, payload: Dict[str, Any], db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    data, errors = ApplicationValidator.validate_update(payload or {})
    if errors:
        return _error_response(400, "Bad Request", errors)
    try:
        entity = ApplicationRepo.update(app_id, data or {}, db_path=db_path)
    except sqlite3.IntegrityError as e:
        return _error_response(400, "Bad Request", {"db": f"constraint violation: {str(e)}"})
    except sqlite3.DatabaseError as e:
        return _error_response(500, "Internal Server Error", {"db": str(e)})
    if not entity:
        return _error_response(404, "Not Found")
    return 200, {"data": entity}


def delete_application(app_id: int, db_path: str = "demo.db") -> Tuple[int, Optional[Dict[str, Any]]]:
    try:
        deleted = ApplicationRepo.delete(app_id, db_path=db_path)
    except sqlite3.DatabaseError as e:
        status, body = _error_response(500, "Internal Server Error", {"db": str(e)})
        return status, body
    if not deleted:
        status, body = _error_response(404, "Not Found")
        return status, body
    return 204, None