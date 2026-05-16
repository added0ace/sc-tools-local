from flask import Flask, render_template, request, send_file, jsonify
import os, threading, shutil, uuid, subprocess
from core.engine import Engine

app = Flask(__name__)
engine = Engine()
tasks = {}

def check_and_install_deps():
    if shutil.which("astcenc") is None:
        print("System dependency 'astcenc' not found. Installing via apt...")
        try:
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            subprocess.run(["sudo", "apt-get", "install", "-y", "astcenc"], check=True)
        except Exception as e:
            print("Please run: sudo apt-get install astcenc")

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
    return jsonify(tasks.get(task_id) or {"status": "error", "message": "Task not found"})

@app.route('/upload_decode', methods=['POST'])
def upload_decode():
    file = request.files['file']
    task_id = str(uuid.uuid4())
    os.makedirs(f"temp/{task_id}", exist_ok=True)
    save_path = f"temp/{task_id}/{file.filename}"
    file.save(save_path)
    tasks[task_id] = {"status": "idle", "message": "Очередь...", "percent": 0, "download_url": ""}
    threading.Thread(target=run_decode, args=(task_id, save_path, file.filename)).start()
    return jsonify({"status": "started", "task_id": task_id})

@app.route('/upload_encode', methods=['POST'])
def upload_encode():
    file = request.files['file']
    task_id = str(uuid.uuid4())
    os.makedirs(f"temp/{task_id}", exist_ok=True)
    save_path = f"temp/{task_id}/{file.filename}"
    file.save(save_path)
    tasks[task_id] = {"status": "idle", "message": "Очередь...", "percent": 0, "download_url": ""}
    threading.Thread(target=run_encode, args=(task_id, save_path)).start()
    return jsonify({"status": "started", "task_id": task_id})

@app.route('/download/<task_id>/<filename>')
def download(task_id, filename):
    return send_file(f"temp/{task_id}/{filename}", as_attachment=True)

if __name__ == '__main__':
    os.makedirs("temp", exist_ok=True)
    check_and_install_deps()
    app.run(host='0.0.0.0', port=5000)
