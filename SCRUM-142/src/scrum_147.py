"""
Business logic module for managing job applications with validation, defaults,
and SQLite persistence. Provides pure functions that can be used by an HTTP layer.

Key behaviors:
- Enforces required fields (company, role), validates status enum, applies defaults on create.
- Normalizes status to lowercase and trimmed before persistence.
- Uses SQLite via sqlite3; all functions accept a db_path parameter.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid


ALLOWED_STATUSES = ("applied", "interviewing", "offer", "rejected")


# Error types and handler

@dataclass
class DomainError(Exception):
    status_code: int
    message: str

    def __str__(self) -> str:
        return f"{self.status_code}: {self.message}"


class BadRequestError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(400, message)


class NotFoundError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(404, message)


class InternalServerError(DomainError):
    def __init__(self, message: str = "internal server error") -> None:
        super().__init__(500, message)


def _error_response(ex: Exception) -> Tuple[int, Dict[str, str]]:
    if isinstance(ex, DomainError):
        return ex.status_code, {"message": ex.message}
    return 500, {"message": "internal server error"}


# Utilities

def _today_utc_ymd() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_status(value: str) -> str:
    return value.lower().strip()


def _trim_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


def _validate_ymd(date_str: str) -> None:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        raise BadRequestError("applied_date must be in YYYY-MM-DD format")


# Repository

class ApplicationRepository:
    @staticmethod
    def _ensure_schema(db_path: str) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('applied','interviewing','offer','rejected')),
                    applied_date TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "company": row["company"],
            "role": row["role"],
            "status": row["status"],
            "applied_date": row["applied_date"],
        }

    @staticmethod
    def create(record: Dict[str, Any], db_path: str = "demo.db") -> Dict[str, Any]:
        ApplicationRepository._ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO applications (id, company, role, status, applied_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["company"],
                    record["role"],
                    record["status"],
                    record["applied_date"],
                ),
            )
            cur = conn.execute(
                "SELECT id, company, role, status, applied_date FROM applications WHERE id = ?",
                (record["id"],),
            )
            row = cur.fetchone()
            assert row is not None
            return ApplicationRepository._row_to_dict(row)

    @staticmethod
    def get_by_id(app_id: str, db_path: str = "demo.db") -> Optional[Dict[str, Any]]:
        ApplicationRepository._ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, company, role, status, applied_date FROM applications WHERE id = ?",
                (app_id,),
            )
            row = cur.fetchone()
            return ApplicationRepository._row_to_dict(row) if row else None

    @staticmethod
    def update(
        app_id: str,
        merged_record: Dict[str, Any],
        db_path: str = "demo.db",
    ) -> Dict[str, Any]:
        ApplicationRepository._ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE applications
                SET company = ?, role = ?, status = ?, applied_date = ?
                WHERE id = ?
                """,
                (
                    merged_record["company"],
                    merged_record["role"],
                    merged_record["status"],
                    merged_record["applied_date"],
                    app_id,
                ),
            )
            cur = conn.execute(
                "SELECT id, company, role, status, applied_date FROM applications WHERE id = ?",
                (app_id,),
            )
            row = cur.fetchone()
            if not row:
                raise NotFoundError("application not found")
            return ApplicationRepository._row_to_dict(row)

    @staticmethod
    def delete(app_id: str, db_path: str = "demo.db") -> bool:
        ApplicationRepository._ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            return cur.rowcount > 0

    @staticmethod
    def list_all(db_path: str = "demo.db") -> List[Dict[str, Any]]:
        ApplicationRepository._ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, company, role, status, applied_date FROM applications ORDER BY applied_date DESC, id ASC"
            )
            rows = cur.fetchall()
            return [ApplicationRepository._row_to_dict(r) for r in rows]

    @staticmethod
    def list_by_status(status: str, db_path: str = "demo.db") -> List[Dict[str, Any]]:
        ApplicationRepository._ensure_schema(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT id, company, role, status, applied_date
                FROM applications
                WHERE status = ?
                ORDER BY applied_date DESC, id ASC
                """,
                (status,),
            )
            rows = cur.fetchall()
            return [ApplicationRepository._row_to_dict(r) for r in rows]


# Service

class ApplicationService:
    @staticmethod
    def _validate_required_company_role(company: Optional[str], role: Optional[str]) -> Tuple[str, str]:
        company_trimmed = _trim_string(company) or ""
        role_trimmed = _trim_string(role) or ""
        if not company_trimmed:
            raise BadRequestError("company is required")
        if not role_trimmed:
            raise BadRequestError("role is required")
        return company_trimmed, role_trimmed

    @staticmethod
    def _validate_optional_company_role(payload: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if "company" in payload:
            company_trimmed = _trim_string(payload.get("company"))
            if not company_trimmed:
                raise BadRequestError("company must be a non-empty string")
            out["company"] = company_trimmed
        if "role" in payload:
            role_trimmed = _trim_string(payload.get("role"))
            if not role_trimmed:
                raise BadRequestError("role must be a non-empty string")
            out["role"] = role_trimmed
        return out

    @staticmethod
    def _validate_status_optional(status: Optional[str]) -> Optional[str]:
        if status is None:
            return None
        normalized = _normalize_status(status)
        if normalized not in ALLOWED_STATUSES:
            raise BadRequestError("invalid status")
        return normalized

    @staticmethod
    def _validate_status_required(status: str) -> str:
        normalized = _normalize_status(status)
        if normalized not in ALLOWED_STATUSES:
            raise BadRequestError("invalid status")
        return normalized

    @staticmethod
    def _validate_applied_date_optional(applied_date: Optional[str]) -> Optional[str]:
        if applied_date is None:
            return None
        applied_date_trimmed = _trim_string(applied_date)
        if not applied_date_trimmed:
            raise BadRequestError("applied_date must be in YYYY-MM-DD format")
        _validate_ymd(applied_date_trimmed)
        return applied_date_trimmed

    @staticmethod
    def _apply_create_defaults(payload: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(payload)
        if "status" not in out or out["status"] is None:
            out["status"] = "applied"
        if "applied_date" not in out or out["applied_date"] is None:
            out["applied_date"] = _today_utc_ymd()
        return out

    @staticmethod
    def create_application(payload: Dict[str, Any], db_path: str = "demo.db") -> Dict[str, Any]:
        # Trim incoming strings for known keys
        company = payload.get("company")
        role = payload.get("role")
        status = payload.get("status")
        applied_date = payload.get("applied_date")

        company_trimmed, role_trimmed = ApplicationService._validate_required_company_role(company, role)
        status_validated = None
        if status is not None:
            status_validated = ApplicationService._validate_status_required(str(status))
        applied_date_validated = ApplicationService._validate_applied_date_optional(
            str(applied_date) if applied_date is not None else None
        )

        # Apply defaults
        enriched = ApplicationService._apply_create_defaults(
            {
                "company": company_trimmed,
                "role": role_trimmed,
                "status": status_validated,
                "applied_date": applied_date_validated,
            }
        )

        # Ensure normalized and validated
        enriched["status"] = ApplicationService._validate_status_required(enriched["status"])
        enriched["applied_date"] = (
            enriched["applied_date"] if enriched["applied_date"] is not None else _today_utc_ymd()
        )
        _validate_ymd(enriched["applied_date"])

        record = {
            "id": str(uuid.uuid4()),
            "company": enriched["company"],
            "role": enriched["role"],
            "status": enriched["status"],
            "applied_date": enriched["applied_date"],
        }
        return ApplicationRepository.create(record, db_path=db_path)

    @staticmethod
    def list_applications(status: Optional[str], db_path: str = "demo.db") -> List[Dict[str, Any]]:
        if status is None:
            return ApplicationRepository.list_all(db_path=db_path)
        normalized = ApplicationService._validate_status_required(str(status))
        return ApplicationRepository.list_by_status(normalized, db_path=db_path)

    @staticmethod
    def get_application(app_id: str, db_path: str = "demo.db") -> Dict[str, Any]:
        if not app_id or not isinstance(app_id, str) or not _is_valid_uuid(app_id):
            raise BadRequestError("invalid id")
        found = ApplicationRepository.get_by_id(app_id, db_path=db_path)
        if not found:
            raise NotFoundError("application not found")
        return found

    @staticmethod
    def update_application(app_id: str, payload: Dict[str, Any], db_path: str = "demo.db") -> Dict[str, Any]:
        if not app_id or not isinstance(app_id, str) or not _is_valid_uuid(app_id):
            raise BadRequestError("invalid id")
        existing = ApplicationRepository.get_by_id(app_id, db_path=db_path)
        if not existing:
            raise NotFoundError("application not found")

        # Validate optional fields present in payload
        updates: Dict[str, Any] = {}
        updates.update(ApplicationService._validate_optional_company_role(payload))
        if "status" in payload:
            updates["status"] = ApplicationService._validate_status_required(str(payload.get("status")))
        if "applied_date" in payload:
            updates["applied_date"] = ApplicationService._validate_applied_date_optional(
                str(payload.get("applied_date")) if payload.get("applied_date") is not None else None
            )
            if updates["applied_date"] is None:
                raise BadRequestError("applied_date must be in YYYY-MM-DD format")

        # Merge into existing
        merged = {
            "id": existing["id"],
            "company": updates.get("company", existing["company"]),
            "role": updates.get("role", existing["role"]),
            "status": updates.get("status", existing["status"]),
            "applied_date": updates.get("applied_date", existing["applied_date"]),
        }
        # Normalize just in case
        merged["company"] = _trim_string(merged["company"]) or ""
        merged["role"] = _trim_string(merged["role"]) or ""
        merged["status"] = ApplicationService._validate_status_required(merged["status"])
        _validate_ymd(merged["applied_date"])

        return ApplicationRepository.update(app_id, merged, db_path=db_path)

    @staticmethod
    def delete_application(app_id: str, db_path: str = "demo.db") -> None:
        if not app_id or not isinstance(app_id, str) or not _is_valid_uuid(app_id):
            raise BadRequestError("invalid id")
        deleted = ApplicationRepository.delete(app_id, db_path=db_path)
        if not deleted:
            raise NotFoundError("application not found")


# Controller-like functions (pure, return status code and JSON payload)

def post_applications(payload: Dict[str, Any], db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    try:
        created = ApplicationService.create_application(payload, db_path=db_path)
        return 201, created
    except Exception as ex:
        return _error_response(ex)


def get_applications(status: Optional[str] = None, db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    try:
        items = ApplicationService.list_applications(status, db_path=db_path)
        return 200, {"items": items}
    except Exception as ex:
        return _error_response(ex)


def get_application_by_id(app_id: str, db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    try:
        item = ApplicationService.get_application(app_id, db_path=db_path)
        return 200, item
    except Exception as ex:
        return _error_response(ex)


def put_application(app_id: str, payload: Dict[str, Any], db_path: str = "demo.db") -> Tuple[int, Dict[str, Any]]:
    try:
        updated = ApplicationService.update_application(app_id, payload, db_path=db_path)
        return 200, updated
    except Exception as ex:
        return _error_response(ex)


def delete_application(app_id: str, db_path: str = "demo.db") -> Tuple[int, Optional[Dict[str, Any]]]:
    try:
        ApplicationService.delete_application(app_id, db_path=db_path)
        return 204, None
    except Exception as ex:
        code, body = _error_response(ex)
        return code, body