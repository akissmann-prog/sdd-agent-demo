from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_143 import (
    init_db,
    create_application,
    get_applications,
    get_application,
    update_application,
    delete_application,
    list_grouped_by_status,
)

bp = Blueprint("scrum_143", __name__)

@bp.record_once
def _init_db(setup_state):
    try:
        init_db(DB_PATH)
    except Exception:
        # Schema is ensured in each logic function; ignore init errors here.
        pass


@bp.route("/applications", methods=["GET"])
def list_applications():
    """
    List applications, optionally filtered by ?status=.
    """
    try:
        status_param = request.args.get("status")
        if status_param is not None:
            status_param = status_param.lower().strip()
            if status_param == "":
                status_param = None
        apps = get_applications(status=status_param, db_path=DB_PATH)
        return jsonify(apps), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "internal server error"}), 500


@bp.route("/applications/<app_id>", methods=["GET"])
def get_application_route(app_id: str):
    """
    Retrieve a single application by id.
    """
    try:
        app = get_application(app_id, db_path=DB_PATH)
        if not app:
            return jsonify({"error": "application not found"}), 404
        return jsonify(app), 200
    except Exception:
        return jsonify({"error": "internal server error"}), 500


@bp.route("/applications", methods=["POST"])
def create_application_route():
    """
    Create a new application. Body JSON: {company, role, notes?, applied_date?, status?}.
    """
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid or missing JSON body"}), 400

        company = data.get("company")
        role = data.get("role")
        notes = data.get("notes")
        applied_date = data.get("applied_date")
        status = data.get("status")

        # Normalize enum/status if provided
        if status is not None:
            status_norm = str(status).lower().strip()
            status = status_norm if status_norm != "" else None

        app = create_application(
            company=company,
            role=role,
            notes=notes,
            applied_date=applied_date,
            status=status,
            db_path=DB_PATH,
        )
        return jsonify(app), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "internal server error"}), 500


@bp.route("/applications/<app_id>", methods=["PUT"])
def update_application_route(app_id: str):
    """
    Update fields of an application. Body JSON may include: company, role, applied_date, status, notes.
    """
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid or missing JSON body"}), 400

        # Normalize enum/status if present
        if "status" in data:
            status_val = data.get("status")
            status_norm = str(status_val).lower().strip() if status_val is not None else None
            if status_norm == "" or status_norm is None:
                # Remove empty/None status to avoid violating constraints
                data.pop("status", None)
            else:
                data["status"] = status_norm

        updated = update_application(app_id, data, db_path=DB_PATH)
        if not updated:
            return jsonify({"error": "application not found"}), 404
        return jsonify(updated), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "internal server error"}), 500


@bp.route("/applications/<app_id>", methods=["DELETE"])
def delete_application_route(app_id: str):
    """
    Delete an application by id.
    """
    try:
        deleted = delete_application(app_id, db_path=DB_PATH)
        if not deleted:
            return jsonify({"error": "application not found"}), 404
        return jsonify({"deleted": True}), 200
    except Exception:
        return jsonify({"error": "internal server error"}), 500


@bp.route("/applications/grouped", methods=["GET"])
def grouped_by_status():
    """
    Return applications grouped by status, for efficient dashboard rendering.
    """
    try:
        groups = list_grouped_by_status(db_path=DB_PATH)
        return jsonify(groups), 200
    except Exception:
        return jsonify({"error": "internal server error"}), 500