from flask import Flask, render_template, request, send_file, jsonify
import os
import threading
import uuid
from core.engine import Engine

app = Flask(__name__)
engine = Engine()
tasks = {}

def progress_updater(task_id, msg, pct):
    if task_id in tasks:
        tasks[task_id]["message"] = msg
        tasks[task_id]["percent"] = pct

def run_decode(task_id, file_path, filename):
    try:
        tasks[task_id]["status"] = "processing"
        zip_path = engine.decode_file(file_path, filename, progress_callback=lambda m, p: progress_updater(task_id, m, p))
        tasks[task_id]["download_url"] = f"/download/{task_id}/{os.path.basename(zip_path)}"
        tasks[task_id]["status"] = "done"
    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["message"] = str(e)

def run_encode(task_id, file_path):
    try:
        tasks[task_id]["status"] = "processing"
        out_path = engine.encode_file(file_path, progress_callback=lambda m, p: progress_updater(task_id, m, p))
        tasks[task_id]["download_url"] = f"/download/{task_id}/{os.path.basename(out_path)}"
        tasks[task_id]["status"] = "done"
    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["message"] = str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status/<task_id>')
def status(task_id):
    task = tasks.get(task_id)
    if not task: return jsonify({"status": "error", "message": "Task not found"}), 404
    return jsonify(task)

@app.route('/upload_decode', methods=['POST'])
def upload_decode():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    task_id = str(uuid.uuid4())
    task_dir = os.path.join("temp", task_id)
    os.makedirs(task_dir, exist_ok=True)
    save_path = os.path.join(task_dir, file.filename)
    file.save(save_path)
    
    tasks[task_id] = {"status": "idle", "message": "Очередь...", "percent": 0, "download_url": ""}
    threading.Thread(target=run_decode, args=(task_id, save_path, file.filename)).start()
    return jsonify({"status": "started", "task_id": task_id})

@app.route('/upload_encode', methods=['POST'])
def upload_encode():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    task_id = str(uuid.uuid4())
    task_dir = os.path.join("temp", task_id)
    os.makedirs(task_dir, exist_ok=True)
    save_path = os.path.join(task_dir, file.filename)
    file.save(save_path)
    
    tasks[task_id] = {"status": "idle", "message": "Очередь...", "percent": 0, "download_url": ""}
    threading.Thread(target=run_encode, args=(task_id, save_path)).start()
    return jsonify({"status": "started", "task_id": task_id})

@app.route('/download/<task_id>/<filename>')
def download(task_id, filename):
    file_path = os.path.join("temp", task_id, filename)
    if os.path.exists(file_path): return send_file(file_path, as_attachment=True)
    return "File not found", 404

if __name__ == '__main__':
    os.makedirs("temp", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
