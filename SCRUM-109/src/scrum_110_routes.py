from typing import Any, Dict, Optional
from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_110 import (
    create_application,
    list_applications,
    get_application,
    update_application,
    delete_application,
    ValidationError,
    NotFoundError,
)

bp = Blueprint("scrum_110", __name__)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code


@bp.get("/applications")
def applications_list():
    """List all applications, optionally filtered by status via ?status=."""
    try:
        status: Optional[str] = request.args.get("status")
        records = list_applications(status=status, db_path=DB_PATH)
        return jsonify(records), 200
    except ValidationError as e:
        return _error(str(e), e.status_code)
    except Exception:
        return _error("internal server error", 500)


@bp.get("/applications/<int:app_id>")
def applications_get(app_id: int):
    """Retrieve a single application by id."""
    try:
        record = get_application(app_id, db_path=DB_PATH)
        return jsonify(record), 200
    except NotFoundError as e:
        return _error(str(e), e.status_code)
    except ValidationError as e:
        return _error(str(e), e.status_code)
    except Exception:
        return _error("internal server error", 500)


@bp.post("/applications")
def applications_create():
    """Create a new application with defaults and validation."""
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("request body must be a JSON object", 400)
        created = create_application(payload, db_path=DB_PATH)
        return jsonify(created), 201
    except ValidationError as e:
        return _error(str(e), e.status_code)
    except Exception:
        return _error("internal server error", 500)


@bp.put("/applications/<int:app_id>")
def applications_update(app_id: int):
    """Update fields of an existing application."""
    try:
        patch = request.get_json(silent=True)
        if not isinstance(patch, dict):
            return _error("request body must be a JSON object", 400)
        updated = update_application(app_id, patch, db_path=DB_PATH)
        return jsonify(updated), 200
    except NotFoundError as e:
        return _error(str(e), e.status_code)
    except ValidationError as e:
        return _error(str(e), e.status_code)
    except Exception:
        return _error("internal server error", 500)


@bp.delete("/applications/<int:app_id>")
def applications_delete(app_id: int):
    """Delete an application by id."""
    try:
        delete_application(app_id, db_path=DB_PATH)
        return "", 204
    except NotFoundError as e:
        return _error(str(e), e.status_code)
    except ValidationError as e:
        return _error(str(e), e.status_code)
    except Exception:
        return _error("internal server error", 500)