from flask import Blueprint, request, jsonify
from config import DB_PATH
from scrum_81 import (
    create_task as logic_create_task,
    get_task as logic_get_task,
    update_task as logic_update_task,
    delete_task as logic_delete_task,
    list_tasks as logic_list_tasks,
    ValidationError,
    NotFoundError,
)

bp = Blueprint('scrum_81', __name__)
bp_scrum_81 = bp


def _task_to_dict(t):
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "created_date": t.created_date,
    }


@bp.route("/tasks", methods=["GET"])
def list_tasks():
    """List tasks, optionally filtered by status query parameter."""
    status = request.args.get("status")
    try:
        tasks = logic_list_tasks(status=status, db_path=DB_PATH)
        return jsonify([_task_to_dict(t) for t in tasks]), 200
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id: int):
    """Retrieve a single task by id."""
    try:
        task = logic_get_task(task_id, db_path=DB_PATH)
        return jsonify(_task_to_dict(task)), 200
    except NotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/tasks", methods=["POST"])
def create_task():
    """Create a new task with required title and optional status."""
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body must be an object"}), 400

    title = data.get("title")
    status = data.get("status")

    if title is None:
        return jsonify({"error": "Field 'title' is required"}), 400

    try:
        task = logic_create_task(title=title, status=status, db_path=DB_PATH)
        return jsonify(_task_to_dict(task)), 201
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id: int):
    """Update an existing task's title and/or status."""
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body must be an object"}), 400

    title = data.get("title")
    status = data.get("status")

    try:
        task = logic_update_task(task_id=task_id, title=title, status=status, db_path=DB_PATH)
        return jsonify(_task_to_dict(task)), 200
    except NotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id: int):
    """Delete a task by id."""
    try:
        logic_delete_task(task_id=task_id, db_path=DB_PATH)
        return "", 204
    except NotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        return jsonify({"error": "Internal server error"}), 500