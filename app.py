import os
import re
import json
import logging
import time
import zipfile
from io import BytesIO
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
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
        "requirements.txt": "flask\n",
        "README.md": "# Flask App\n"
    },
    "html": {
        "index.html": '<!DOCTYPE html>\n<html>\n<head><title>My Site</title><link rel="stylesheet" href="style.css"></head>\n<body>\n<h1>Hello!</h1>\n<script src="script.js"></script>\n</body>\n</html>',
        "style.css": 'body { font-family: Arial; margin: 20px; background: #f0f0f0; }\n',
        "script.js": 'console.log("Hello from JS!");\n',
        "README.md": "# Static Website\n"
    }
}

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
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
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-coder", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 2000},
            timeout=30
        )
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        return ""

# ==================== ПЕРЕСТАНОВКА КОДА ====================
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

# ==================== АНАЛИЗ СЛОЖНОСТИ ====================
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

# ==================== ПОИСК БАГОВ ====================
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
            bugs.append({"message": msg, "severity": severity})
    return bugs

# ==================== ВАЛИДАЦИЯ ====================
def validate_code(code):
    errors = []
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        errors.append(f"Синтаксическая ошибка: {e.msg}")
    return errors

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "project_files": {}, "current_file": "main.py", "history": []}
    
    # /start
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\n"
            "Привет! Я собираю код из частей с помощью AI.\n\n"
            "*Команды:*\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить\n"
            "/new_project — создать проект\n"
            "/files — список файлов\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск багов\n"
            "/validate — проверка кода\n"
            "/order — переставить функции\n"
            "/export — экспорт всех файлов\n"
            "/web — веб-редактор\n\n"
            "📝 Просто отправь мне часть кода!", parse_mode="Markdown")
    
    # /show
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
    
    # /done
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
    
    # /reset
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        user_sessions[user_id]["history"] = []
        send_message(chat_id, "🧹 Код очищен!")
    
    # /order
    elif text == "/order":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            user_sessions[user_id]["code"] = reorder_code(code)
            send_message(chat_id, "🔄 Код переставлен! Импорты и функции в правильном порядке.")
    
    # /complexity
    elif text == "/complexity":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            analysis = analyze_complexity(code)
            report = f"📊 *Анализ сложности*\n\n• Строк кода: {analysis['code_lines']}\n• Функций: {analysis['functions']}\n• Цикломатическая: {analysis['complexity']:.1f}\n• Оценка: {analysis['rating']}"
            send_message(chat_id, report, parse_mode="Markdown")
    
    # /bugs
    elif text == "/bugs":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            bugs = find_bugs(code)
            if not bugs:
                send_message(chat_id, "✅ Багов не найдено!")
            else:
                report = "🐛 *Найденные проблемы:*\n"
                for b in bugs:
                    report += f"\n• {b['message']} `[{b['severity']}]`"
                send_message(chat_id, report, parse_mode="Markdown")
    
    # /validate
    elif text == "/validate":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            errors = validate_code(code)
            if not errors:
                send_message(chat_id, "✅ Код в идеальном состоянии!")
            else:
                send_message(chat_id, f"⚠️ *Ошибки:*\n" + "\n".join(errors), parse_mode="Markdown")
    
    # /new_project
    elif text.startswith("/new_project"):
        parts = text.split()
        project_type = parts[1] if len(parts) > 1 else "python"
        if project_type in PROJECT_TEMPLATES:
            user_sessions[user_id]["project_files"] = PROJECT_TEMPLATES[project_type].copy()
            user_sessions[user_id]["current_file"] = list(PROJECT_TEMPLATES[project_type].keys())[0]
            user_sessions[user_id]["code"] = list(PROJECT_TEMPLATES[project_type].values())[0]
            files_list = "\n".join([f"• `{f}`" for f in PROJECT_TEMPLATES[project_type].keys()])
            send_message(chat_id, f"✅ Проект '{project_type}' создан!\n\n📁 Файлы:\n{files_list}\n\n/switches\n\nswitch_file <имя> — переключиться", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Неизвестный тип. Доступны: python, flask, html")
    
    # /files
    elif text == "/files":
        files = user_sessions[user_id].get("project_files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов. Используй /new_project")
        else:
            current = user_sessions[user_id].get("current_file", "")
            file_list = []
            for name in files:
                marker = " ✅" if name == current else ""
                file_list.append(f"• `{name}`{marker}")
            send_message(chat_id, f"📁 *Файлы проекта:*\n\n" + "\n".join(file_list) + "\n\n/switch_file <имя>", parse_mode="Markdown")
    
    # /switch_file
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
    
    # /export
    elif text == "/export":
        files = user_sessions[user_id].get("project_files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов для экспорта")
            return
        
        send_message(chat_id, "📦 Создаю ZIP архив...")
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        zip_buffer.seek(0)
        
        with open(f"project_{user_id}.zip", "wb") as f:
            f.write(zip_buffer.getvalue())
        send_file(chat_id, f"project_{user_id}.zip", "📦 Архив проекта")
        os.remove(f"project_{user_id}.zip")
    
    # /web
    elif text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web_editor/{user_id}\n\nТам уже будет твой код!", parse_mode="Markdown")
    
    # /help
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
            "/new_project — создать проект\n"
            "/files — список файлов\n"
            "/switch_file — переключить файл\n"
            "/export — экспорт ZIP\n"
            "/web — веб-редактор\n"
            "/help — это сообщение", parse_mode="Markdown")
    
    # Обработка кода (не команда)
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует и объединяет код...")
        
        if current:
            prompt = f"""Объедини текущий код с новой частью. Верни ТОЛЬКО итоговый код, без объяснений.

Текущий код:
{current}

Новая часть:
{text}

Итоговый код:"""
        else:
            prompt = f"""Верни ТОЛЬКО этот код, без комментариев:
{text}"""
        
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
            user_sessions[user_id]["code"] = ai_response
        else:
            new_code = current + "\n\n" + text if current else text
            user_sessions[user_id]["code"] = new_code
        
        # Обновляем файл в проекте
        current_file = user_sessions[user_id].get("current_file", "main.py")
        if "project_files" in user_sessions[user_id]:
            user_sessions[user_id]["project_files"][current_file] = user_sessions[user_id]["code"]
        
        user_sessions[user_id]["history"].append({"time": str(datetime.now()), "part": text[:100]})
        send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {len(user_sessions[user_id]['code'])} символов\n📁 Файл: `{current_file}`\n\n/show — посмотреть\n/done — скачать", parse_mode="Markdown")

# ==================== ПОЛЛИНГ ====================
def run_bot():
    logger.info("🚀 Бот запущен!")
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

# ==================== ВЕБ-РЕДАКТОР ====================
WEB_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>🤖 AI Code Editor</title>
    <script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
    <style>
        body { margin: 0; padding: 0; background: #1e1e1e; font-family: monospace; }
        #editor { height: 85vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; flex-wrap: wrap; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #1177bb; }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; }
    </style>
</head>
<body>
<div class="toolbar">
    <button onclick="saveCode()">💾 Сохранить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
    <button onclick="analyzeComplexity()">📊 Сложность</button>
    <button onclick="findBugs()">🐛 Баги</button>
    <button onclick="reorder()">🔄 Порядок</button>
</div>
<div id="editor"></div>
<div class="status" id="status">Готов к работе</div>
<script>
let editor;
require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: {{ code | tojson }},
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true }
    });
});
async function saveCode() {
    const code = editor.getValue();
    await fetch('/api/save_code', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: {{ user_id }}, code: code})
    });
    document.getElementById('status').innerText = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов к работе', 2000);
}
function downloadCode() {
    const code = editor.getValue();
    const blob = new Blob([code], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'code.py';
    a.click();
    URL.revokeObjectURL(a.href);
}
async function analyzeComplexity() {
    const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function findBugs() {
    const res = await fetch('/api/bugs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function reorder() {
    const res = await fetch('/api/reorder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    editor.setValue(data.code);
    document.getElementById('status').innerText = '🔄 Код переставлен!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов к работе', 2000);
}
</script>
</body>
</html>
"""

@app.route('/web_editor/<int:user_id>')
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

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    code = request.json.get('code', '')
    analysis = analyze_complexity(code)
    report = f"📊 Строк кода: {analysis['code_lines']}, Функций: {analysis['functions']}, Сложность: {analysis['complexity']:.1f} ({analysis['rating']})"
    return jsonify({"report": report})

@app.route('/api/bugs', methods=['POST'])
def api_bugs():
    code = request.json.get('code', '')
    bugs = find_bugs(code)
    if not bugs:
        return jsonify({"report": "✅ Багов не найдено!"})
    report = "🐛 Баги:\n" + "\n".join([f"- {b['message']} [{b['severity']}]" for b in bugs])
    return jsonify({"report": report})

@app.route('/api/reorder', methods=['POST'])
def api_reorder():
    code = request.json.get('code', '')
    return jsonify({"code": reorder_code(code)})

@app.route('/')
def health():
    return "🤖 AI Code Assembler Bot is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT)
