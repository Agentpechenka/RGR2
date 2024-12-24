import subprocess, os, time, logging, copy, shutil
import pandas as pd
from uuid import uuid4
from flask import Flask, jsonify, request
from flask_cors import CORS
from threading import Thread, Lock
import re

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("pipeline.log", mode='w'),  # Запись логов в файл
        logging.StreamHandler()  # Вывод логов в консоль
    ]
)
app = Flask(__name__)
CORS(app)
pipeline_history = []  # Список для хранения истории запусков

def save_user_code(user_code, user_id):
    try:
        filename = f"user_code_{user_id}.py"
        filepath = os.path.join("temp", filename)

        # Проверяем, существует ли директория "temp", если нет — создаём
        if not os.path.exists("temp"):
            os.makedirs("temp")
            logging.info("Directory 'temp' created.")

        # Сохраняем код в файл
        with open(filepath, "w") as f:
            f.write(user_code)
            logging.info(f"File saved: {filepath}")

        return filepath
    except Exception as e:
        logging.error(f"Error saving user code: {e}")
        return None

def install_missing_packages(code):
    try:
        # Ищем все модули, которые импортируются в коде
        imports = re.findall(r'^\s*import (\w+)|^\s*from (\w+) import', code, re.MULTILINE)
        modules = {match[0] or match[1] for match in imports}

        for module in modules:
            try:
                __import__(module)
            except ImportError:
                logging.info(f"Module '{module}' is not installed. Installing...")
                subprocess.check_call(["pip", "install", module])
    except Exception as e:
        logging.error(f"Error during package installation: {e}")

# Функция для деплоя
def deploy():
    source_dir = "temp"
    destination_dir = "deployed"
    if not os.path.exists(source_dir):
        logging.error(f"Source directory not found: {source_dir}")
        return "Deploy failed: Source directory not found"

    if not os.path.exists(destination_dir):
        os.makedirs(destination_dir)
        logging.info(f"Created destination directory: {destination_dir}")

    try:
        for filename in os.listdir(source_dir):
            source_path = os.path.join(source_dir, filename)
            destination_path = os.path.join(destination_dir, filename)

            if os.path.isfile(source_path):
                shutil.copy(source_path, destination_path)
                logging.info(f"Copied file: {source_path} -> {destination_path}")
            else:
                logging.warning(f"Skipping non-file item: {source_path}")

        return "Deploy successful"
    except Exception as e:
        logging.error(f"Error during deployment: {e}")
        return f"Deploy failed: {e}"

# Данные о pipeline
pipeline_data = {
    "stages": [
        {"name": "Build", "status": "pending", "duration": 0},
        {"name": "Test", "status": "pending", "duration": 0},
        {"name": "Deploy", "status": "pending", "duration": 0}
    ],
    "output": ""  # Поле для хранения результата выполнения кода
}
# Статистика по пайплайну
pipeline_stats = {
    "success_count": 0,
    "failure_count": 0
}


pipeline_lock = Lock()  # Создаём блокировку

def run_python_script(code, user_id):
    global pipeline_stats, pipeline_history

    try:
        install_missing_packages(code)  # Установка недостающих модулей
        filepath = save_user_code(code, user_id)
        with pipeline_lock:  # Безопасное обновление данных
            pipeline_data["stages"][0]["status"] = "running"
        start_time = time.time()

        # Stage 1: Build
        result = subprocess.run(
            ["python", "-u", filepath],
            check=True,
            capture_output=True,
            text=True
        )
        logging.info(f"Getting result of subprocess: {result.stdout}")
        duration = time.time() - start_time
        with pipeline_lock:  # Обновляем pipeline_data безопасно
            pipeline_data["stages"][0]["status"] = "success"
            pipeline_data["stages"][0]["duration"] = round(duration, 2)
            pipeline_data["output"] = result.stdout.strip()

    except subprocess.CalledProcessError as e:
        with pipeline_lock:
            pipeline_data["stages"][0]["status"] = "failure"
            pipeline_data["output"] = e.stdout.strip() + "\n" + e.stderr.strip()
            pipeline_stats["failure_count"] += 1
        return
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route('/pipeline', methods=['GET'])
def get_pipeline():
    return jsonify({**pipeline_data, "stats": pipeline_stats})

@app.route('/history', methods=['GET'])
def get_pipeline_history():
    return jsonify(pipeline_history)

@app.route('/start_compile', methods=['POST'])
def start_compile():
    data = request.get_json()  # Получаем JSON из тела запроса

    if not data or 'code' not in data:
        return jsonify({"status": "error", "message": "No code provided"}), 400

    code = data['code']
    logging.info(f"Received code: {repr(code)}")  # Логируем код для отладки

    user_id = str(uuid4())
    thread = Thread(target=run_python_script, args=(code, user_id))
    thread.start()

    return jsonify({"status": "Compilation started", "user_id": user_id})

if __name__ == "__main__":
    app.run(debug=True, port=3000)
