from flask import Blueprint, request, jsonify, Response
from config import DB_PATH
from scrum_77 import create_task, get_task, list_tasks, update_task, delete_task, get_dashboard_html

bp = Blueprint('scrum_77', __name__)


@bp.route('/tasks', methods=['GET'])
def list_tasks_route():
    """List all tasks, optionally filtered by status via ?status="""
    status = request.args.get('status')
    try:
        tasks = list_tasks(status=status, db_path=DB_PATH)
        return jsonify(tasks)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/tasks/<int:task_id>', methods=['GET'])
def get_task_route(task_id: int):
    """Retrieve a single task by ID"""
    try:
        task = get_task(task_id, db_path=DB_PATH)
        if task is None:
            return jsonify({"error": f"Task with id {task_id} not found"}), 404
        return jsonify(task)
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/tasks', methods=['POST'])
def create_task_route():
    """Create a new task"""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    title = data.get('title')
    description = data.get('description')
    status = data.get('status')

    try:
        task = create_task(title=title, description=description, status=status, db_path=DB_PATH)
        return jsonify(task), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/tasks/<int:task_id>', methods=['PUT'])
def update_task_route(task_id: int):
    """Update an existing task's fields"""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    # Only forward known fields; unspecified fields remain None to avoid updates
    title = data.get('title') if 'title' in data else None
    description = data.get('description') if 'description' in data else None
    status = data.get('status') if 'status' in data else None

    try:
        task = update_task(task_id=task_id, title=title, description=description, status=status, db_path=DB_PATH)
        return jsonify(task)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/tasks/<int:task_id>', methods=['DELETE'])
def delete_task_route(task_id: int):
    """Delete a task by ID"""
    try:
        deleted = delete_task(task_id, db_path=DB_PATH)
        if not deleted:
            return jsonify({"error": f"Task with id {task_id} not found"}), 404
        return jsonify({"deleted": True})
    except Exception:
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/dashboard', methods=['GET'])
def dashboard_route():
    """Serve the single-page tasks dashboard"""
    try:
        html = get_dashboard_html()
        return Response(html, mimetype='text/html')
    except Exception:
        return jsonify({"error": "Failed to load dashboard"}), 500