import os
import re
import json
import logging
import time
import ast
import tempfile
import subprocess
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
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

# ==================== ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
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
        response = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return response.json().get("result", [])
    except:
        return []

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
        content = result["choices"][0]["message"]["content"]
        if content.startswith("```"):
            lines = content.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = '\n'.join(lines)
        return content.strip()
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        return ""

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

def run_code_safe(code: str) -> dict:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Превышено время выполнения (5 сек)"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
    finally:
        os.unlink(temp_file)

# ==================== ОБРАБОТКА TELEGRAM ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    if text == "/start":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\nПривет! Я собираю код из частей.\n\n"
            f"🌐 *Веб-редактор:* {bot_url}/web/{user_id}\n\n"
            "*Команды:*\n/show — показать код\n/done — скачать\n/reset — очистить\n"
            "/order — переставить\n/complexity — сложность\n/bugs — баги\n"
            "/validate — проверка\n/run — запустить\n/web — веб-редактор\n/help — справка", parse_mode="Markdown")
    
    elif text == "/help":
        send_message(chat_id, "📚 Команды: /start, /show, /done, /reset, /order, /complexity, /bugs, /validate, /run, /web", parse_mode="Markdown")
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        send_message(chat_id, f"```python\n{code if code else '# Код пуст'}\n```", parse_mode="Markdown")
    
    elif text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w") as f:
            f.write(code)
        send_file(chat_id, filename, f"✅ Код! {len(code)} символов")
        os.remove(filename)
    
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        send_message(chat_id, "🧹 Код очищен!")
    
    elif text == "/order":
        user_sessions[user_id]["code"] = reorder_code(user_sessions[user_id]["code"])
        send_message(chat_id, "🔄 Код переставлен!")
    
    elif text == "/complexity":
        analysis = analyze_complexity(user_sessions[user_id]["code"])
        send_message(chat_id, f"📊 Строк: {analysis['code_lines']}\nФункций: {analysis['functions']}\nСложность: {analysis['complexity']:.1f}\n{analysis['rating']}", parse_mode="Markdown")
    
    elif text == "/bugs":
        send_message(chat_id, find_bugs(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "/validate":
        send_message(chat_id, validate_code(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "/run":
        result = run_code_safe(user_sessions[user_id]["code"])
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
    
    elif text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 Веб-редактор: {bot_url}/web/{user_id}", parse_mode="Markdown")
    
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует...")
        
        if current:
            prompt = f"Объедини код. Верни ТОЛЬКО итоговый код.\n\nТекущий код:\n{current}\n\nНовая часть:\n{text}\n\nИтоговый код:"
        else:
            prompt = f"Верни ТОЛЬКО этот код:\n{text}"
        
        ai_response = call_deepseek(prompt)
        new_code = ai_response if ai_response else (current + "\n\n" + text if current else text)
        user_sessions[user_id]["code"] = new_code
        send_message(chat_id, f"✅ Код обновлён! {len(new_code)} символов\n/show — посмотреть", parse_mode="Markdown")

# ==================== TELEGRAM ПОЛЛИНГ ====================
def run_telegram_bot():
    logger.info("🤖 Бот запущен!")
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
WEB_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>🤖 AI Code Editor</title>
    <style>
        body { margin: 0; padding: 0; background: #1e1e1e; }
        #editor { height: 85vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #1177bb; }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="toolbar">
    <button onclick="saveCode()">💾 Сохранить</button>
    <button onclick="runCode()">▶️ Запустить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
</div>
<div id="editor"></div>
<div class="status" id="status">Готов</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor; const USER_ID = {{ user_id }}; const API_URL = window.location.origin;
require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: {{ code | tojson }},
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        automaticLayout: true
    });
});
async function saveCode() {
    await fetch(API_URL + '/api/save_code', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, code: editor.getValue()})
    });
    document.getElementById('status').innerText = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов', 2000);
}
async function runCode() {
    const res = await fetch(API_URL + '/api/run_code', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.success ? (data.output || '✅ Успешно') : '❌ ' + data.error);
}
function downloadCode() {
    const blob = new Blob([editor.getValue()], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'code.py';
    a.click();
    URL.revokeObjectURL(a.href);
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
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/run_code', methods=['POST'])
def api_run_code():
    return jsonify(run_code_safe(request.json.get('code', '')))

@app.route('/')
def health():
    return "🤖 Bot is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    Thread(target=run_telegram_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
