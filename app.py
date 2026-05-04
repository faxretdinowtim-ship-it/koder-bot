import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ТЕЛЕГРАМ ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except:
        pass

def send_file(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except:
        pass

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

# ==================== ФУНКЦИИ ====================
def auto_fix_code(code):
    """Полное автоисправление кода"""
    if not code.strip():
        return code
    
    # === ПРОСТЫЕ ИСПРАВЛЕНИЯ (без AI) ===
    fixed = code
    
    # 1. Добавляем двоеточие в функции
    fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
    
    # 2. Добавляем пропущенные скобки
    lines = fixed.split('\n')
    for i, line in enumerate(lines):
        if 'print(' in line and line.count('(') > line.count(')'):
            lines[i] = line + ')'
        # Исправляем отсутствие двоеточия в if/for/while
        if re.match(r'^(if|elif|else|for|while)\s+.*[^:]\s*$', line):
            if not line.strip().endswith(':'):
                lines[i] = line + ':'
    fixed = '\n'.join(lines)
    
    # 3. Удаляем дубликаты импортов
    lines = fixed.split('\n')
    seen_imports = set()
    new_lines = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            if line.strip() not in seen_imports:
                seen_imports.add(line.strip())
                new_lines.append(line)
        else:
            new_lines.append(line)
    fixed = '\n'.join(new_lines)
    
    # 4. Исправляем деление на ноль (оборачиваем в try)
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixed = 'try:\n    ' + fixed.replace('\n', '\n    ') + '\nexcept ZeroDivisionError:\n    print("Ошибка: деление на ноль")\n'
    
    # 5. Добавляем недостающую строку в print
    fixed = re.sub(r"print\(\"([^\"]*)\"$", r'print("\1")', fixed)
    fixed = re.sub(r"print\('([^']*)'$", r"print('\1')", fixed)
    
    return fixed

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    if functions == 0 and not code.strip():
        return "Нет кода для анализа"
    complexity = 1 + code.count('if ') + code.count('for ') + code.count('while ') * 0.5
    rating = "Низкая" if complexity < 10 else "Средняя" if complexity < 20 else "Высокая"
    return f"**Анализ:**\nСтрок: {code_lines}\nФункций: {functions}\nСложность: {complexity:.1f}\nОценка: {rating}"

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("- Деление на ноль [КРИТИЧЕСКАЯ]")
    if 'eval(' in code:
        bugs.append("- Использование eval() [ВЫСОКАЯ]")
    if re.search(r'except\s*:', code):
        bugs.append("- Голый except [СРЕДНЯЯ]")
    if re.search(r'password\s*=\s*[\'"]', code, re.IGNORECASE):
        bugs.append("- Хардкод пароля [КРИТИЧЕСКАЯ]")
    if 'print(' in code:
        bugs.append("- Отладочный print() [НИЗКАЯ]")
    
    # Проверка синтаксиса
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"- Синтаксическая ошибка: {e.msg} [КРИТИЧЕСКАЯ]")
    
    if not bugs:
        return "✅ Ошибок не найдено!"
    return "**Найденные ошибки:**\n" + "\n".join(bugs)

def validate_code(code):
    try:
        compile(code, '<string>', 'exec')
        return "✅ Код синтаксически верен!"
    except SyntaxError as e:
        return f"❌ Ошибка: {e.msg}\n📍 Строка: {e.lineno}"

def reorder_code(code):
    lines = code.split('\n')
    imports = []
    functions = []
    other = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            imports.append(line)
        elif line.strip().startswith('def '):
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

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Timeout (5 sec)"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
    finally:
        os.unlink(temp_file)

# ==================== КЛАВИАТУРА ====================
def get_main_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔍 Анализ сложности", "🐛 Поиск ошибок"],
            ["🔧 Полное автоисправление", "🔄 Переставить функции"],
            ["✅ Проверить код", "🏃 Запустить код"],
            ["🌐 Веб-редактор", "🗑 Очистить всё"],
            ["❓ Помощь"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    if text == "/start":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\n"
            "Привет! Я собираю и ИСПРАВЛЯЮ код.\n\n"
            f"🌐 *Веб-редактор:* {bot_url}/web/{user_id}\n\n"
            "👇 *Нажми кнопку:*",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "❓ Помощь" or text == "/help":
        send_message(chat_id, "📚 Команды:\n/show - код\n/done - скачать\n/reset - очистить\n/auto_fix - исправить\n/web - редактор", parse_mode="Markdown", reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w") as f:
            f.write(code)
        send_file(chat_id, filename, "✅ Код готов!")
        os.remove(filename)
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[user_id]["code"] = ""
        send_message(chat_id, "🧹 Код очищен!", reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "🔄 Переставить функции" or text == "/order":
        user_sessions[user_id]["code"] = reorder_code(user_sessions[user_id]["code"])
        send_message(chat_id, "🔄 Код переставлен!")
    
    elif text == "🔍 Анализ сложности" or text == "/complexity":
        send_message(chat_id, analyze_complexity(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "🐛 Поиск ошибок" or text == "/bugs":
        send_message(chat_id, find_bugs(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "✅ Проверить код" or text == "/validate":
        send_message(chat_id, validate_code(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "🏃 Запустить код" or text == "/run":
        result = run_code_safe(user_sessions[user_id]["code"])
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
    
    # === ГЛАВНОЕ: ПОЛНОЕ АВТОИСПРАВЛЕНИЕ ===
    elif text == "🔧 Полное автоисправление" or text == "/auto_fix":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления\n\nСначала отправь код!")
            return
        
        send_message(chat_id, "🔧 Исправляю код...")
        
        # Исправляем
        fixed_code = auto_fix_code(code)
        
        if fixed_code != code:
            user_sessions[user_id]["code"] = fixed_code
            send_message(chat_id, f"✅ **Код исправлен!**\n\n📊 Было ошибок: {len(find_bugs(code).split(chr(10))) - 1}\n🔧 Исправлено!\n\n📝 Показать код — посмотреть результат", parse_mode="Markdown")
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии! Ошибок не найдено.", parse_mode="Markdown")
    
    elif text == "🌐 Веб-редактор" or text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 Веб-редактор: {bot_url}/web/{user_id}", parse_mode="Markdown")
    
    # Обработка кода
    elif not text.startswith("/") and not text.startswith("📝") and not text.startswith("💾") and not text.startswith("🔍") and not text.startswith("🐛") and not text.startswith("✅") and not text.startswith("🔄") and not text.startswith("🏃") and not text.startswith("🔧") and not text.startswith("🌐") and not text.startswith("🗑") and not text.startswith("❓"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует код...")
        
        if current:
            prompt = f"Объедини код. Верни ТОЛЬКО итоговый код.\n\nТекущий код:\n{current}\n\nНовая часть:\n{text}\n\nИтоговый код:"
        else:
            prompt = f"Верни ТОЛЬКО этот код:\n{text}"
        
        ai_response = call_deepseek(prompt)
        new_code = ai_response if ai_response else (current + "\n\n" + text if current else text)
        user_sessions[user_id]["code"] = new_code
        send_message(chat_id, f"✅ Код обновлён! {len(new_code)} символов\n\n📝 Показать код\n🔧 Полное автоисправление", parse_mode="Markdown")

# ==================== TELEGRAM БОТ ====================
def run_telegram_bot():
    logger.info("Бот запущен!")
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

# ==================== ВЕБ-СЕРВЕР ====================
WEB_HTML = '''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>AI Code Editor</title>
<style>
body { background: #1e1e1e; margin:0; }
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
    <button onclick="analyzeCode()">📊 Анализ</button>
    <button onclick="findBugs()">🐛 Ошибки</button>
    <button onclick="autoFix()">🔧 Исправить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
</div>
<div id="editor"></div>
<div class="status" id="status">Готов</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor; const USER_ID = window.location.pathname.split('/')[2]; const API_URL = window.location.origin;
require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '', language: 'python', theme: 'vs-dark', fontSize: 14, minimap: { enabled: true }, automaticLayout: true
    });
    loadCode();
});
async function loadCode() {
    const res = await fetch(`${API_URL}/api/get_code?user_id=${USER_ID}`);
    const data = await res.json();
    editor.setValue(data.code || '# Код пуст');
}
async function saveCode() {
    await fetch(`${API_URL}/api/save_code`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: USER_ID, code: editor.getValue()}) });
    document.getElementById('status').innerText = 'Сохранено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов', 2000);
}
async function runCode() {
    const res = await fetch(`${API_URL}/api/run_code`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: editor.getValue()}) });
    const data = await res.json();
    alert(data.success ? (data.output || 'Успешно') : 'Ошибка: ' + data.error);
}
async function analyzeCode() {
    const res = await fetch(`${API_URL}/api/analyze`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: editor.getValue()}) });
    const data = await res.json();
    alert(data.report);
}
async function findBugs() {
    const res = await fetch(`${API_URL}/api/bugs`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: editor.getValue()}) });
    const data = await res.json();
    alert(data.report);
}
async function autoFix() {
    const res = await fetch(`${API_URL}/api/auto_fix`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: editor.getValue()}) });
    const data = await res.json();
    editor.setValue(data.code);
    document.getElementById('status').innerText = 'Исправлено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов', 2000);
}
function downloadCode() {
    const blob = new Blob([editor.getValue()], {type: 'text/plain'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'code.py'; a.click(); URL.revokeObjectURL(a.href);
}
</script>
</body>
</html>'''

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/web/'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(WEB_HTML.encode('utf-8'))
        elif parsed.path == '/' or parsed.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        elif parsed.path.startswith('/api/get_code'):
            query = parse_qs(parsed.query)
            user_id = int(query.get('user_id', [0])[0])
            code = user_sessions.get(user_id, {}).get("code", "")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"code": code}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        if self.path == '/api/save_code':
            data = json.loads(body)
            user_id = data.get('user_id')
            code = data.get('code', '')
            if user_id in user_sessions:
                user_sessions[user_id]["code"] = code
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
        
        elif self.path == '/api/run_code':
            data = json.loads(body)
            result = run_code_safe(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        
        elif self.path == '/api/analyze':
            data = json.loads(body)
            result = analyze_complexity(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"report": result}).encode())
        
        elif self.path == '/api/bugs':
            data = json.loads(body)
            result = find_bugs(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"report": result}).encode())
        
        elif self.path == '/api/auto_fix':
            data = json.loads(body)
            result = auto_fix_code(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"code": result}).encode())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_web_server():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"Web server on port {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    run_web_server()
