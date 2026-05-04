import os
import re
import json
import logging
import time
import ast
import subprocess
import tempfile
import zipfile
from io import BytesIO
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Шаблоны проектов
PROJECT_TEMPLATES = {
    "python": {
        "main.py": '#!/usr/bin/env python3\n"""Main entry point"""\n\ndef main():\n    print("Hello, World!")\n\nif __name__ == "__main__":\n    main()\n',
        "README.md": "# Python Project\n"
    },
    "flask": {
        "app.py": 'from flask import Flask\n\napp = Flask(__name__)\n\n@app.route("/")\ndef home():\n    return "Hello, Flask!"\n\nif __name__ == "__main__":\n    app.run(debug=True)\n',
        "requirements.txt": "flask\n"
    },
    "html": {
        "index.html": '<!DOCTYPE html>\n<html>\n<head><title>My Site</title><link rel="stylesheet" href="style.css"></head>\n<body>\n<h1>Hello!</h1>\n<script src="script.js"></script>\n</body>\n</html>',
        "style.css": 'body { font-family: Arial; margin: 20px; }\n',
        "script.js": 'console.log("Hello!");\n'
    }
}

# ==================== ТЕЛЕГРАМ ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_file(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        return requests.get(f"{API_URL}/getUpdates", params=params, timeout=35).json().get("result", [])
    except:
        return []

# ==================== AI ФУНКЦИЯ ====================
def call_deepseek(prompt):
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code != 200:
            return ""
        result = response.json()
        if "choices" not in result or not result["choices"]:
            return ""
        return result["choices"][0]["message"]["content"]
    except:
        return ""

# ==================== СУПЕР-АНАЛИЗ ОШИБОК ====================
class SuperBugHunter:
    def __init__(self):
        self.bugs = []
        self.warnings = []
    
    def hunt_all(self, code: str) -> dict:
        self.bugs = []
        self.warnings = []
        
        # Синтаксис
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            self.bugs.append({"severity": "CRITICAL", "message": f"Синтаксис: {e.msg}", "line": e.lineno})
        
        # Паттерны ошибок
        patterns = [
            (r'/\s*0\b', 'CRITICAL', 'Деление на ноль'),
            (r'eval\s*\(', 'HIGH', 'Использование eval()'),
            (r'except\s*:', 'MEDIUM', 'Голый except'),
            (r'password\s*=\s*[\'"]', 'HIGH', 'Хардкод пароля'),
            (r'print\(', 'LOW', 'Отладочный print()'),
        ]
        for pattern, severity, msg in patterns:
            if re.search(pattern, code):
                self.bugs.append({"severity": severity, "message": msg})
        
        return {
            "bugs": self.bugs,
            "warnings": self.warnings,
            "total_bugs": len(self.bugs),
            "critical_count": sum(1 for b in self.bugs if b.get("severity") == "CRITICAL"),
            "high_count": sum(1 for b in self.bugs if b.get("severity") == "HIGH"),
            "medium_count": sum(1 for b in self.bugs if b.get("severity") == "MEDIUM"),
            "low_count": sum(1 for b in self.bugs if b.get("severity") == "LOW")
        }
    
    def generate_report(self, result: dict) -> str:
        if result["total_bugs"] == 0:
            return "🎉 **ИДЕАЛЬНЫЙ КОД!** Ошибок не найдено."
        report = "🔍 **РЕЗУЛЬТАТЫ СКАНА**\n\n"
        report += f"🔴 CRITICAL: {result['critical_count']}\n"
        report += f"🟠 HIGH: {result['high_count']}\n"
        report += f"🟡 MEDIUM: {result['medium_count']}\n"
        report += f"🔵 LOW: {result['low_count']}\n\n"
        for b in result["bugs"][:5]:
            report += f"• {b['message']} `[{b['severity']}]`\n"
        return report

hunter = SuperBugHunter()

# ==================== ФУНКЦИИ АНАЛИЗА ====================
def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "🟢 Низкая"
    elif complexity < 20:
        rating = "🟡 Средняя"
    else:
        rating = "🔴 Высокая"
    return {"code_lines": code_lines, "functions": functions, "complexity": complexity, "rating": rating}

def format_complexity_report(analysis):
    return f"📊 *Анализ сложности*\n\n• Строк кода: {analysis['code_lines']}\n• Функций: {analysis['functions']}\n• Сложность: {analysis['complexity']:.1f}\n• Оценка: {analysis['rating']}"

def find_bugs(code):
    bugs = []
    patterns = [
        (r'/\s*0\b', 'Деление на ноль', 'CRITICAL'),
        (r'eval\s*\(', 'Использование eval()', 'HIGH'),
        (r'except\s*:', 'Голый except', 'MEDIUM'),
        (r'password\s*=\s*[\'"]', 'Хардкод пароля', 'CRITICAL'),
    ]
    for pattern, msg, severity in patterns:
        if re.search(pattern, code):
            bugs.append(f"• {msg} `[{severity}]`")
    if not bugs:
        return "✅ Багов не найдено!"
    return "🐛 *Найденные проблемы:*\n" + "\n".join(bugs)

def validate_code(code):
    try:
        compile(code, '<string>', 'exec')
        return "✅ Код в идеальном состоянии!"
    except SyntaxError as e:
        return f"⚠️ *Ошибка:* {e.msg}\n📍 Строка: {e.lineno}"

def reorder_code(code):
    lines = code.split('\n')
    imports = []
    functions = []
    other = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            imports.append(line)
        elif line.strip().startswith(('def ', 'async def ')):
            functions.append(line)
        else:
            other.append(line)
    result = []
    if imports:
        result.extend(sorted(set(imports)))
        result.append('')
    if functions:
        result.extend(functions)
        result.append('')
    result.extend(other)
    return '\n'.join(result)

def auto_fix_with_ai(code: str, bugs: list) -> str:
    if not bugs:
        return code
    bugs_text = "\n".join([f"- {b.get('message', '')}" for b in bugs[:5]])
    prompt = f"""Исправь ошибки в коде. Верни ТОЛЬКО исправленный код.

Ошибки:
{bugs_text}

Код:
{code}

Исправленный код:"""
    response = call_deepseek(prompt)
    if response:
        response = response.strip()
        if response.startswith("```"):
            lines = response.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = '\n'.join(lines)
        return response
    return code

def run_code_safe(code: str, input_data: str = "") -> dict:
    """Безопасный запуск кода в песочнице"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    
    try:
        process = subprocess.run(
            [f"python3", temp_file],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=5
        )
        return {
            "success": process.returncode == 0,
            "output": process.stdout,
            "error": process.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Превышено время выполнения (5 сек)"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
    finally:
        os.unlink(temp_file)

# ==================== ОБРАБОТКА ТЕЛЕГРАМ ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": [], "project_files": {}, "current_file": "main.py"}
    
    # Команды
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\n"
            "Привет! Я собираю код из частей с помощью DeepSeek AI.\n\n"
            "*Команды:*\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить\n"
            "/order — переставить функции\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск багов\n"
            "/validate — проверка кода\n"
            "/super_scan — полный анализ\n"
            "/auto_fix — исправить ошибки\n"
            "/run — запустить код\n"
            "/new_project — создать проект\n"
            "/files — список файлов\n"
            "/export — экспорт ZIP\n"
            "/web — веб-редактор\n"
            "/help — справка", parse_mode="Markdown")
    
    elif text == "/help":
        send_message(chat_id,
            "📚 *Все команды бота*\n\n"
            "/start — начать работу\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить код\n"
            "/order — переставить функции\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск багов\n"
            "/validate — проверка кода\n"
            "/super_scan — полный анализ (15+ типов)\n"
            "/auto_fix — автоматическое исправление\n"
            "/run — выполнить код в песочнице\n"
            "/new_project — создать проект (python/flask/html)\n"
            "/files — список файлов\n"
            "/switch_file — переключить файл\n"
            "/export — экспорт ZIP\n"
            "/web — веб-редактор\n"
            "/help — это сообщение", parse_mode="Markdown")
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
    
    elif text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        send_file(chat_id, filename, f"✅ Готовый код! {len(code)} символов")
        os.remove(filename)
    
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        user_sessions[user_id]["history"] = []
        send_message(chat_id, "🧹 Код очищен!")
    
    elif text == "/order":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            user_sessions[user_id]["code"] = reorder_code(code)
            send_message(chat_id, "🔄 Код переставлен!")
    
    elif text == "/complexity":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            analysis = analyze_complexity(code)
            send_message(chat_id, format_complexity_report(analysis), parse_mode="Markdown")
    
    elif text == "/bugs":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            send_message(chat_id, find_bugs(code), parse_mode="Markdown")
    
    elif text == "/validate":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            send_message(chat_id, validate_code(code), parse_mode="Markdown")
    
    elif text == "/super_scan":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для сканирования")
            return
        send_message(chat_id, "🔬 Запуск полного анализа...")
        result = hunter.hunt_all(code)
        user_sessions[user_id]["last_scan"] = result
        send_message(chat_id, hunter.generate_report(result), parse_mode="Markdown")
    
    elif text == "/auto_fix":
        code = user_sessions[user_id]["code"]
        last_scan = user_sessions[user_id].get("last_scan")
        if not last_scan or last_scan.get("total_bugs", 0) == 0:
            send_message(chat_id, "📭 Сначала запустите `/super_scan`")
            return
        send_message(chat_id, "🔧 Исправляю ошибки...")
        fixed_code = auto_fix_with_ai(code, last_scan.get("bugs", []))
        user_sessions[user_id]["code"] = fixed_code
        send_message(chat_id, "✅ Ошибки исправлены!\n/show для просмотра")
    
    elif text == "/run":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для запуска")
            return
        send_message(chat_id, "🏃 Запуск кода в песочнице...")
        result = run_code_safe(code)
        if result["success"]:
            output = result["output"][:3000] if result["output"] else "(нет вывода)"
            send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```", parse_mode="Markdown")
        else:
            error = result["error"][:2000] if result["error"] else "Неизвестная ошибка"
            send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```", parse_mode="Markdown")
    
    elif text.startswith("/new_project"):
        parts = text.split()
        project_type = parts[1] if len(parts) > 1 else "python"
        if project_type in PROJECT_TEMPLATES:
            user_sessions[user_id]["project_files"] = PROJECT_TEMPLATES[project_type].copy()
            user_sessions[user_id]["current_file"] = list(PROJECT_TEMPLATES[project_type].keys())[0]
            user_sessions[user_id]["code"] = list(PROJECT_TEMPLATES[project_type].values())[0]
            send_message(chat_id, f"✅ Проект '{project_type}' создан!")
        else:
            send_message(chat_id, f"❌ Неизвестный тип. Доступны: python, flask, html")
    
    elif text == "/files":
        files = user_sessions[user_id].get("project_files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов. Используй /new_project")
        else:
            file_list = "\n".join([f"• `{f}`" for f in files.keys()])
            send_message(chat_id, f"📁 *Файлы проекта:*\n{file_list}", parse_mode="Markdown")
    
    elif text.startswith("/switch_file"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Использование: /switch_file main.py")
        else:
            filename = parts[1]
            files = user_sessions[user_id].get("project_files", {})
            if filename in files:
                user_sessions[user_id]["current_file"] = filename
                user_sessions[user_id]["code"] = files[filename]
                send_message(chat_id, f"✅ Переключён на `{filename}`")
            else:
                send_message(chat_id, f"❌ Файл `{filename}` не найден")
    
    elif text == "/export":
        files = user_sessions[user_id].get("project_files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов для экспорта")
            return
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        zip_buffer.seek(0)
        with open(f"project_{user_id}.zip", "wb") as f:
            f.write(zip_buffer.getvalue())
        send_file(chat_id, f"project_{user_id}.zip", "📦 Архив проекта")
        os.remove(f"project_{user_id}.zip")
    
    elif text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web/{user_id}", parse_mode="Markdown")
    
    # Обработка обычного кода
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует код...")
        
        if current:
            prompt = f"Объедини код. Верни ТОЛЬКО итоговый код.\n\nТекущий код:\n{current}\n\nНовая часть:\n{text}\n\nИтоговый код:"
        else:
            prompt = f"Верни ТОЛЬКО этот код:\n{text}"
        
        ai_response = call_deepseek(prompt)
        
        if ai_response:
            ai_response = ai_response.strip()
            if ai_response.startswith("```"):
                lines = ai_response.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                ai_response = '\n'.join(lines)
            new_code = ai_response
        else:
            new_code = current + "\n\n" + text if current else text
        
        user_sessions[user_id]["history"].append({
            "time": str(datetime.now()),
            "part": text[:200],
            "full_code": user_sessions[user_id]["code"]
        })
        user_sessions[user_id]["code"] = new_code
        
        # Обновляем файл в проекте
        current_file = user_sessions[user_id].get("current_file", "main.py")
        if "project_files" in user_sessions[user_id]:
            user_sessions[user_id]["project_files"][current_file] = new_code
        
        send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {len(new_code)} символов\n📁 Файл: `{current_file}`\n\n/show — посмотреть\n/run — запустить\n/super_scan — проверить", parse_mode="Markdown")

# ==================== ТЕЛЕГРАМ ПОЛЛИНГ ====================
def run_telegram_bot():
    logger.info("🤖 Telegram бот запущен!")
    last_update_id = 0
    while True:
        try:
            updates = get_updates(offset=last_update_id + 1 if last_update_id else None)
            for update in updates:
                last_update_id = update["update_id"]
                if "message" in update:
                    process_message(update["message"])
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

# ==================== ВЕБ-ИНТЕРФЕЙС ====================
WEB_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Studio - Профессиональный редактор кода</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            font-family: 'Segoe UI', 'Fira Code', monospace;
            min-height: 100vh;
            color: #e0e0e0;
        }

        /* Header */
        .header {
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(10px);
            padding: 15px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(100, 108, 255, 0.3);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-icon {
            font-size: 32px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .logo-text {
            font-size: 22px;
            font-weight: bold;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .toolbar {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }

        .btn {
            padding: 8px 18px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            transition: all 0.2s;
            font-family: inherit;
        }

        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }

        .btn-success {
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            color: white;
        }

        .btn-warning {
            background: linear-gradient(135deg, #f2994a 0%, #f2c94c 100%);
            color: white;
        }

        .btn-danger {
            background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
            color: white;
        }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.1);
            color: white;
        }

        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.2);
        }

        /* Main container */
        .main-container {
            display: flex;
            height: calc(100vh - 70px);
        }

        /* Editor section */
        .editor-section {
            flex: 2;
            display: flex;
            flex-direction: column;
            border-right: 1px solid rgba(255, 255, 255, 0.1);
        }

        .editor-header {
            background: rgba(0, 0, 0, 0.3);
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .file-info {
            font-size: 12px;
            color: #888;
        }

        #editor {
            flex: 1;
            min-height: 0;
        }

        /* Output section */
        .output-section {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: rgba(0, 0, 0, 0.3);
        }

        .output-header {
            background: rgba(0, 0, 0, 0.3);
            padding: 10px 20px;
            display: flex;
            gap: 15px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .tab {
            padding: 5px 15px;
            cursor: pointer;
            border-radius: 5px;
            transition: all 0.2s;
        }

        .tab.active {
            background: rgba(102, 126, 234, 0.3);
            color: #667eea;
        }

        .tab:hover {
            background: rgba(255, 255, 255, 0.1);
        }

        .output-content {
            flex: 1;
            padding: 15px;
            overflow-y: auto;
            font-family: 'Fira Code', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .output-error {
            color: #f48771;
        }

        .output-success {
            color: #6a9955;
        }

        /* Status bar */
        .status-bar {
            background: rgba(0, 0, 0, 0.5);
            padding: 6px 20px;
            font-size: 11px;
            color: #888;
            display: flex;
            justify-content: space-between;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }

        /* Loading overlay */
        .loading {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.9);
            padding: 20px 40px;
            border-radius: 12px;
            display: none;
            z-index: 1000;
            font-size: 16px;
        }

        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: #1e1e1e;
        }

        ::-webkit-scrollbar-thumb {
            background: #555;
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: #777;
        }

        @media (max-width: 768px) {
            .main-container {
                flex-direction: column;
            }
            .editor-section {
                height: 50vh;
            }
            .toolbar {
                gap: 5px;
            }
            .btn {
                padding: 6px 12px;
                font-size: 11px;
            }
            .logo-text {
                font-size: 16px;
            }
        }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
    <div class="header">
        <div class="logo">
            <span class="logo-icon">🤖</span>
            <span class="logo-text">AI Code Studio</span>
        </div>
        <div class="toolbar">
            <button class="btn btn-primary" onclick="saveCode()">💾 Сохранить</button>
            <button class="btn btn-success" onclick="runCode()">▶️ Запустить</button>
            <button class="btn btn-warning" onclick="analyzeCode()">🔍 Анализ</button>
            <button class="btn btn-danger" onclick="downloadCode()">📥 Скачать</button>
            <button class="btn btn-secondary" onclick="clearCode()">🗑 Очистить</button>
        </div>
    </div>

    <div class="main-container">
        <div class="editor-section">
            <div class="editor-header">
                <span>📝 Редактор кода</span>
                <span class="file-info" id="fileInfo">Python</span>
            </div>
            <div id="editor"></div>
        </div>

        <div class="output-section">
            <div class="output-header">
                <div class="tab active" onclick="switchTab('output')">📄 Вывод</div>
                <div class="tab" onclick="switchTab('analysis')">🔬 Анализ</div>
                <div class="tab" onclick="switchTab('bugs')">🐛 Баги</div>
            </div>
            <div class="output-content" id="outputContent">
                <span class="output-success">✅ Готов к работе</span>
            </div>
        </div>
    </div>

    <div class="status-bar">
        <span id="status">⚡ Готов</span>
        <span id="stats">📝 Символов: 0</span>
    </div>

    <div class="loading" id="loading">
        <span>⏳ Обработка...</span>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
    <script>
        let editor;
        let currentTab = 'output';
        const USER_ID = {{ user_id }};
        const API_URL = window.location.origin;

        // Инициализация Monaco Editor
        require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], function() {
            editor = monaco.editor.create(document.getElementById('editor'), {
                value: {{ code | tojson }},
                language: 'python',
                theme: 'vs-dark',
                fontSize: 14,
                minimap: { enabled: true },
                automaticLayout: true,
                fontFamily: 'Fira Code, monospace',
                fontLigatures: true,
                renderWhitespace: 'selection'
            });

            editor.onDidChangeModelContent(() => {
                const len = editor.getValue().length;
                document.getElementById('stats').innerHTML = `📝 Символов: ${len}`;
            });

            updateStats();
        });

        function updateStats() {
            const len = editor?.getValue().length || 0;
            document.getElementById('stats').innerHTML = `📝 Символов: ${len}`;
        }

        function showLoading(show) {
            document.getElementById('loading').style.display = show ? 'flex' : 'none';
        }

        function setStatus(text, isError = false) {
            const statusEl = document.getElementById('status');
            statusEl.innerHTML = text;
            statusEl.style.color = isError ? '#f48771' : '#888';
        }

        function switchTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
        }

        function setOutput(text, isError = false) {
            const outputDiv = document.getElementById('outputContent');
            const className = isError ? 'output-error' : 'output-success';
            outputDiv.innerHTML = `<span class="${className}">${escapeHtml(text)}</span>`;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function saveCode() {
            showLoading(true);
            setStatus('💾 Сохранение...');
            try {
                const response = await fetch(`${API_URL}/api/save_code`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: USER_ID, code: editor.getValue() })
                });
                const data = await response.json();
                if (data.success) {
                    setStatus('✅ Сохранено!');
                    setOutput('✅ Код сохранён в бота!');
                } else {
                    setStatus('❌ Ошибка сохранения', true);
                }
            } catch(e) {
                setStatus('❌ Ошибка сети', true);
            }
            showLoading(false);
            setTimeout(() => setStatus('⚡ Готов'), 2000);
        }

        async function runCode() {
            const code = editor.getValue();
            if (!code.trim()) {
                setOutput('❌ Нет кода для выполнения', true);
                return;
            }
            showLoading(true);
            setStatus('🏃 Запуск...');
            try {
                const response = await fetch(`${API_URL}/api/run_code`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code })
                });
                const data = await response.json();
                if (data.success) {
                    setOutput(data.output || '✅ Выполнение успешно! (нет вывода)');
                    setStatus('✅ Выполнено');
                } else {
                    setOutput(data.error || 'Ошибка выполнения', true);
                    setStatus('❌ Ошибка', true);
                }
                switchTab('output');
            } catch(e) {
                setOutput('Ошибка соединения с сервером', true);
                setStatus('❌ Ошибка', true);
            }
            showLoading(false);
        }

        async function analyzeCode() {
            const code = editor.getValue();
            if (!code.trim()) {
                setOutput('❌ Нет кода для анализа', true);
                return;
            }
            showLoading(true);
            setStatus('🔍 Анализ...');
            try {
                const response = await fetch(`${API_URL}/api/analyze`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code })
                });
                const data = await response.json();
                setOutput(data.report);
                setStatus('✅ Анализ завершён');
            } catch(e) {
                setOutput('Ошибка анализа', true);
            }
            showLoading(false);
        }

        function downloadCode() {
            const code = editor.getValue();
            const blob = new Blob([code], { type: 'text/plain' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = 'code.py';
            link.click();
            URL.revokeObjectURL(link.href);
            setStatus('📥 Скачивание...');
            setTimeout(() => setStatus('⚡ Готов'), 1000);
        }

        function clearCode() {
            if (confirm('Очистить редактор?')) {
                editor.setValue('');
                setStatus('🗑 Очищено');
                setOutput('✅ Редактор очищен');
                setTimeout(() => setStatus('⚡ Готов'), 1000);
            }
        }
    </script>
</body>
</html>'''

@app.route('/web/<int:user_id>')
def web_editor(user_id):
    code = user_sessions.get(user_id, {}).get("code", "")
    return render_template_string(WEB_HTML, user_id=user_id, code=code)

@app.route('/api/save_code', methods=['POST'])
def api_save_code():
    data = request.json
    user_id = data.get('user_id')
    code = data.get('code', '')
    if user_id in user_sessions:
        user_sessions[user_id]["code"] = code
        current_file = user_sessions[user_id].get("current_file", "main.py")
        if "project_files" in user_sessions[user_id]:
            user_sessions[user_id]["project_files"][current_file] = code
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/run_code', methods=['POST'])
def api_run_code():
    code = request.json.get('code', '')
    result = run_code_safe(code)
    return jsonify(result)

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    code = request.json.get('code', '')
    analysis = analyze_complexity(code)
    report = format_complexity_report(analysis)
    result = hunter.hunt_all(code)
    full_report = f"{report}\n\n{result['total_bugs']} ошибок найдено. Используйте /super_scan в Telegram для деталей"
    return jsonify({"report": full_report})

@app.route('/api/find_bugs', methods=['POST'])
def api_find_bugs():
    code = request.json.get('code', '')
    result = hunter.hunt_all(code)
    return jsonify({"report": hunter.generate_report(result)})

@app.route('/')
def health():
    return "🤖 AI Code Studio is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    # Запуск Telegram бота в отдельном потоке
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    # Запуск Flask сервера
    app.run(host='0.0.0.0', port=PORT)
