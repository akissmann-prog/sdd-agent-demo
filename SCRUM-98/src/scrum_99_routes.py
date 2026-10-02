from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_99 import (
    create_application,
    list_applications,
    get_application,
    update_application,
    delete_application,
    ApiError,
    init_db,
)

bp = Blueprint('scrum_99', __name__)


@bp.before_app_first_request
def _ensure_db():
    """
    Ensure the database is initialized before handling the first request.
    """
    try:
        init_db(DB_PATH)
    except Exception:
        # Initialization errors will surface during route handling as needed.
        pass


@bp.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    """
    Convert business-layer ApiError exceptions to JSON HTTP responses.
    """
    return jsonify(err.to_error_response()), err.status_code


@bp.errorhandler(Exception)
def handle_unexpected_error(err: Exception):
    """
    Fallback error handler for unexpected exceptions.
    """
    return jsonify({"message": "Internal server error."}), 500


@bp.route("/applications", methods=["GET"])
def list_applications_route():
    """
    List all job applications, optionally filtered by status query parameter.
    """
    status = request.args.get("status")
    apps = list_applications(status=status, db_path=DB_PATH)
    return jsonify(apps), 200


@bp.route("/applications/<int:app_id>", methods=["GET"])
def get_application_route(app_id: int):
    """
    Retrieve a single job application by its ID.
    """
    record = get_application(app_id, db_path=DB_PATH)
    return jsonify(record), 200


@bp.route("/applications", methods=["POST"])
def create_application_route():
    """
    Create a new job application from a JSON request body.
    """
    if not request.is_json:
        return jsonify({"message": "Request body must be JSON."}), 400
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"message": "Invalid JSON payload."}), 400
    record = create_application(payload, db_path=DB_PATH)
    return jsonify(record), 201


@bp.route("/applications/<int:app_id>", methods=["PUT"])
def update_application_route(app_id: int):
    """
    Update an existing job application with partial or full fields from a JSON body.
    """
    if not request.is_json:
        return jsonify({"message": "Request body must be JSON."}), 400
    updates = request.get_json(silent=True)
    if updates is None:
        return jsonify({"message": "Invalid JSON payload."}), 400
    record = update_application(app_id, updates, db_path=DB_PATH)
    return jsonify(record), 200


@bp.route("/applications/<int:app_id>", methods=["DELETE"])
def delete_application_route(app_id: int):
    """
    Delete a job application by its ID.
    """
    delete_application(app_id, db_path=DB_PATH)
    return "", 204