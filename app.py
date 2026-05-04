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
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== HTML СТРАНИЦА ====================
WEB_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>🤖 AI Code Editor</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #1e1e1e; font-family: monospace; }
#editor { height: 70vh; }
.toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; flex-wrap: wrap; }
button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; }
button:hover { background: #1177bb; }
button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
.output { background: #1e1e1e; color: #d4d4d4; padding: 10px; height: 25vh; overflow: auto; font-family: monospace; white-space: pre-wrap; border-top: 1px solid #333; }
.status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; display: flex; justify-content: space-between; }
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="toolbar">
    <button class="primary" onclick="syncFromBot()">📥 Загрузить из бота</button>
    <button class="primary" onclick="syncToBot()">💾 Сохранить в бота</button>
    <button onclick="runCode()">▶️ Запустить</button>
    <button onclick="analyzeCode()">📊 Анализ</button>
    <button onclick="findBugs()">🐛 Ошибки</button>
    <button onclick="fixCode()">🔧 Исправить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
</div>
<div id="editor"></div>
<div class="output" id="output">⚡ Готов к работе</div>
<div class="status"><span id="status">⚡ Готов</span><span id="stats">📝 0</span></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor;
const USER_ID = window.location.pathname.split('/')[2];
const API_URL = window.location.origin;

require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '# Нажми "Загрузить из бота"',
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true },
        automaticLayout: true
    });
    editor.onDidChangeModelContent(() => {
        document.getElementById('stats').innerHTML = `📝 ${editor.getValue().length}`;
    });
});

async function syncFromBot() {
    const res = await fetch(API_URL + '/api/load?user_id=' + USER_ID);
    const data = await res.json();
    if (data.code && data.code !== '# Пусто') {
        editor.setValue(data.code);
        document.getElementById('output').innerHTML = '<span style="color:#6a9955">✅ Загружено!</span>';
    } else {
        document.getElementById('output').innerHTML = '<span style="color:#f48771">❌ Нет кода</span>';
    }
}

async function syncToBot() {
    const code = editor.getValue();
    await fetch(API_URL + '/api/save', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, code: code})
    });
    document.getElementById('output').innerHTML = '<span style="color:#6a9955">✅ Сохранено!</span>';
}

async function runCode() {
    const code = editor.getValue();
    const res = await fetch(API_URL + '/api/run', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    if (data.success) {
        document.getElementById('output').innerHTML = '<span style="color:#6a9955">✅ Выполнено!</span>\n\n' + (data.output || '(нет вывода)');
    } else {
        document.getElementById('output').innerHTML = '<span style="color:#f48771">❌ Ошибка:</span>\n\n' + data.error;
    }
}

async function analyzeCode() {
    const res = await fetch(API_URL + '/api/analyze', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    document.getElementById('output').innerHTML = '📊 ' + data.report;
}

async function findBugs() {
    const res = await fetch(API_URL + '/api/bugs', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    document.getElementById('output').innerHTML = '🐛 ' + data.report;
}

async function fixCode() {
    const res = await fetch(API_URL + '/api/fix', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    editor.setValue(data.code);
    document.getElementById('output').innerHTML = data.report;
}

function downloadCode() {
    const blob = new Blob([editor.getValue()], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'code.py';
    a.click();
}
</script>
</body>
</html>'''

# ==================== КЛАВИАТУРА ====================
def get_main_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "📊 Анализ"],
            ["🌐 Веб-редактор", "🗑 Очистить всё"],
            ["❓ Помощь"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

# ==================== ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
        logger.info(f"Сообщение отправлено в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_web_button(chat_id, user_id):
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    rm = {"inline_keyboard": [[{"text": "🌐 ОТКРЫТЬ РЕДАКТОР", "web_app": {"url": f"{bot_url}/web/{user_id}"}}]]}
    try:
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "🌐 Нажми на кнопку, чтобы открыть редактор!",
            "reply_markup": json.dumps(rm)
        }, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def get_updates():
    global last_update_id
    params = {"timeout": 30}
    if last_update_id:
        params["offset"] = last_update_id + 1
    try:
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        logger.error(f"Ошибка getUpdates: {e}")
        return []

def auto_fix_code(code):
    if not code.strip():
        return code, "Нет кода"
    fixed = code
    fixes = []
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes.append("двоеточия")
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes.append("деление на ноль")
    if re.search(r'print\(["\'][^"\']*["\']$', fixed, re.MULTILINE):
        fixed = re.sub(r'(print\(["\'][^"\']*["\'])$', r'\1)', fixed, flags=re.MULTILINE)
        fixes.append("print()")
    lines = fixed.split('\n')
    seen = set()
    new_lines = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            if line.strip() not in seen:
                seen.add(line.strip())
                new_lines.append(line)
        else:
            new_lines.append(line)
    if len(new_lines) != len(lines):
        fixes.append("дубликаты импортов")
    fixed = '\n'.join(new_lines)
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код готов")

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль [КРИТИЧЕСКАЯ]")
    if 'eval(' in code:
        bugs.append("❌ Использование eval() [ВЫСОКАЯ]")
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except [СРЕДНЯЯ]")
    if re.search(r'password\s*=\s*[\'"]', code, re.IGNORECASE):
        bugs.append("❌ Хардкод пароля [КРИТИЧЕСКАЯ]")
    if 'print(' in code:
        bugs.append("⚠️ Отладочный print() [НИЗКАЯ]")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg} [КРИТИЧЕСКАЯ]")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "Низкая (хорошо)"
    elif complexity < 20:
        rating = "Средняя (нормально)"
    else:
        rating = "Высокая (нужен рефакторинг)"
    return f"📊 Анализ сложности:\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Сложность: {complexity:.1f}\n• Оценка: {rating}"

def run_code_safe(code):
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

# ==================== HTTP СЕРВЕР ====================
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
        elif parsed.path.startswith('/api/load'):
            query = parse_qs(parsed.query)
            user_id = int(query.get('user_id', [0])[0])
            code = user_sessions.get(user_id, {}).get('code', '')
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
        data = json.loads(body) if body else {}
        
        if self.path == '/api/save':
            user_id = data.get('user_id')
            code = data.get('code', '')
            if user_id not in user_sessions:
                user_sessions[user_id] = {}
            user_sessions[user_id]['code'] = code
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
        elif self.path == '/api/run':
            result = run_code_safe(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        elif self.path == '/api/analyze':
            result = analyze_complexity(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"report": result}).encode())
        elif self.path == '/api/bugs':
            bugs = find_bugs(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"report": "\n".join(bugs)}).encode())
        elif self.path == '/api/fix':
            fixed, report = auto_fix_code(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"code": fixed, "report": report}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

# ==================== TELEGRAM БОТ ====================
def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": []}
    
    logger.info(f"Получено: {text[:50]} от {uid}")
    
    # Обработка команд
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю писать и исправлять код!\n\n"
            "*Основные команды:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "🌐 /web — веб-редактор\n"
            "🗑 /reset — очистить код\n"
            "❓ /help — помощь\n\n"
            "💡 *Совет:* Просто отправь мне часть кода!",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "/help" or text == "❓ Помощь":
        send_message(chat_id,
            "📚 *Команды бота:*\n\n"
            "📝 /show — показать текущий код\n"
            "💾 /done — скачать код файлом\n"
            "🔧 /fix — автоматически исправить ошибки\n"
            "🐛 /bugs — найти все ошибки\n"
            "🏃 /run — выполнить код в песочнице\n"
            "📊 /complexity — анализ сложности кода\n"
            "🔄 /order — переставить функции\n"
            "🌐 /web — открыть веб-редактор\n"
            "🗑 /reset — очистить весь код\n"
            "❓ /help — эта справка",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь мне часть кода!")
        else:
            send_message(chat_id, f"```python\n{code[:3500]}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для скачивания")
            return
        filename = f"code_{uid}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id}, files={"document": f})
        os.remove(filename)
        send_message(chat_id, "✅ Файл отправлен!")
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        send_message(chat_id, "🔧 Исправляю код...")
        fixed_code, report = auto_fix_code(code)
        if fixed_code != code:
            user_sessions[uid]["code"] = fixed_code
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для проверки")
            return
        bugs = find_bugs(code)
        send_message(chat_id, "🔍 *Результаты проверки:*\n\n" + "\n".join(bugs), parse_mode="Markdown")
    
    elif text == "📊 Анализ" or text == "/complexity":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для анализа")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, analysis, parse_mode="Markdown")
    
    elif text == "🏃 Запустить" or text == "/run":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для запуска")
            return
        send_message(chat_id, "🏃 Запускаю код...")
        result = run_code_safe(code)
        if result["success"]:
            output = result["output"][:3000] if result["output"] else "(нет вывода)"
            send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```", parse_mode="Markdown")
        else:
            error = result["error"][:2000] if result["error"] else "Неизвестная ошибка"
            send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```", parse_mode="Markdown")
    
    elif text == "🔄 Порядок" or text == "/order":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для перестановки")
            return
        # Простая перестановка: импорты → функции → остальное
        lines = code.split('\n')
        imports = [l for l in lines if l.strip().startswith(('import ', 'from '))]
        funcs = [l for l in lines if l.strip().startswith('def ')]
        other = [l for l in lines if l not in imports and l not in funcs]
        reordered = '\n'.join(imports + [''] + funcs + [''] + other)
        user_sessions[uid]["code"] = reordered
        send_message(chat_id, "🔄 Код переставлен! Импорты и функции в правильном порядке.")
    
    elif text == "🌐 Веб-редактор" or text == "/web":
        send_web_button(chat_id, uid)
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "🧹 Код полностью очищен!")
    
    # Обработка обычного кода (не команд)
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🏃", "🔄", "🌐", "🗑", "❓"]):
        current = user_sessions[uid]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        
        # Сохраняем историю
        if "history" not in user_sessions[uid]:
            user_sessions[uid]["history"] = []
        user_sessions[uid]["history"].append({"time": str(datetime.now()), "part": text[:100]})
        
        send_message(chat_id, f"✅ *Часть кода сохранена!*\n📊 Всего символов: {len(new_code)}\n📦 Частей: {len(user_sessions[uid]['history'])}\n\n📝 /show — посмотреть код\n🔧 /fix — исправить ошибки", parse_mode="Markdown")

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 Telegram бот запущен!")
    while True:
        try:
            updates = get_updates()
            for upd in updates:
                if upd["update_id"] in processed_ids:
                    continue
                processed_ids.add(upd["update_id"])
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                if "message" in upd:
                    process_message(upd["message"])
                last_update_id = upd["update_id"]
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка бота: {e}")
            time.sleep(5)

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
