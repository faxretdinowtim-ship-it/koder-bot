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

# ==================== HTML СТРАНИЦА (ВЕБ-РЕДАКТОР) ====================
WEB_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Editor - Твой код</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; }
        .header { background: #2d2d2d; padding: 12px 20px; text-align: center; border-bottom: 1px solid #444; }
        .logo { font-size: 20px; font-weight: bold; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        #editor { height: 70vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 6px; }
        button:hover { background: #1177bb; }
        button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        .output { background: #1e1e1e; color: #d4d4d4; padding: 15px; height: 20vh; overflow: auto; font-family: monospace; white-space: pre-wrap; border-top: 1px solid #333; }
        .status { background: #1e1e1e; color: #888; padding: 5px 15px; font-size: 12px; text-align: center; }
        .success { color: #6a9955; }
        .error { color: #f48771; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="header">
    <div class="logo">🤖 AI Code Editor</div>
</div>
<div class="toolbar">
    <button class="primary" onclick="syncFromBot()">📥 Загрузить код из бота</button>
    <button class="primary" onclick="syncToBot()">💾 Сохранить код в бота</button>
    <button onclick="runCode()">▶️ Запустить</button>
    <button onclick="analyzeCode()">📊 Анализ</button>
    <button onclick="findBugs()">🐛 Ошибки</button>
    <button onclick="fixCode()">🔧 Исправить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
</div>
<div id="editor"></div>
<div class="output" id="output">⚡ Готов к работе. Нажми "Загрузить код из бота"</div>
<div class="status" id="status">⚡ Готов</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor;
const USER_ID = window.location.pathname.split('/')[2];
const API_URL = window.location.origin;

function setOutput(text, type = 'info') {
    const out = document.getElementById('output');
    const cls = type === 'error' ? 'error' : (type === 'success' ? 'success' : 'info');
    out.innerHTML = `<span class="${cls}">${escapeHtml(text)}</span>`;
}

function escapeHtml(t) { return t.replace(/[&<>]/g, function(m) { return {'&':'&amp;','<':'&lt;','>':'&gt;'}[m]; }).replace(/\n/g, '<br>'); }

require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '# Нажми "Загрузить код из бота"',
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true },
        automaticLayout: true
    });
});

async function syncFromBot() {
    setOutput('⏳ Загрузка...');
    try {
        const res = await fetch(API_URL + '/api/load?user_id=' + USER_ID);
        const data = await res.json();
        if (data.code && data.code !== '# Пусто') {
            editor.setValue(data.code);
            setOutput('✅ Код загружен из Telegram бота!', 'success');
        } else {
            setOutput('📭 В боте нет кода. Отправь код в Telegram.', 'error');
        }
    } catch(e) { setOutput('❌ Ошибка загрузки', 'error'); }
}

async function syncToBot() {
    const code = editor.getValue();
    if (!code.trim()) { setOutput('❌ Нет кода', 'error'); return; }
    setOutput('⏳ Сохранение...');
    await fetch(API_URL + '/api/save', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, code: code})
    });
    setOutput('✅ Сохранено в бота!', 'success');
}

async function runCode() {
    const code = editor.getValue();
    if (!code.trim()) { setOutput('❌ Нет кода', 'error'); return; }
    setOutput('⏳ Выполнение...');
    const res = await fetch(API_URL + '/api/run', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    if (data.success) {
        setOutput(data.output || '✅ Выполнено!', 'success');
    } else {
        setOutput('❌ ' + (data.error || 'Ошибка'), 'error');
    }
}

async function analyzeCode() {
    const code = editor.getValue();
    const res = await fetch(API_URL + '/api/analyze', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    setOutput('📊 ' + data.report, 'info');
}

async function findBugs() {
    const code = editor.getValue();
    const res = await fetch(API_URL + '/api/bugs', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    setOutput('🐛 ' + data.report, data.report.includes('✅') ? 'success' : 'error');
}

async function fixCode() {
    const code = editor.getValue();
    setOutput('🔧 Исправление...');
    const res = await fetch(API_URL + '/api/fix', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    editor.setValue(data.code);
    setOutput(data.report, 'success');
}

function downloadCode() {
    const code = editor.getValue();
    const blob = new Blob([code], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'code.py';
    a.click();
}
</script>
</body>
</html>'''

# ==================== ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except:
        pass

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except:
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
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код готов")

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ eval()")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ {e.msg}")
    return bugs if bugs else ["✅ Ошибок нет"]

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    return f"Строк кода: {code_lines} | Функций: {code.count('def ')}"

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except:
        return {"success": False, "output": "", "error": "Timeout"}
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
def get_keyboard():
    return {
        "keyboard": [
            ["🌐 Открыть сайт", "📝 Показать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "🗑 Очистить всё"]
        ],
        "resize_keyboard": True
    }

def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": ""}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    if text == "/start":
        send_message(chat_id, "🤖 AI Code Bot\n\nПришли код - я сохраню!\n\n🌐 /site - открыть сайт с кодом\n🔧 /fix - исправить", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/site" or text == "🌐 Открыть сайт":
        send_message(chat_id, f"🌐 *Твой код уже на сайте!*\n\nОткрывай в браузере:\n{bot_url}/web/{uid}\n\n📝 Твой код автоматически подгрузится в редактор.", parse_mode="Markdown")
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[uid]["code"]
        send_message(chat_id, f"```python\n{code[:3000] if code else '# Пусто'}\n```", parse_mode="Markdown")
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "Код готов")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        bugs = find_bugs(user_sessions[uid]["code"])
        send_message(chat_id, "\n".join(bugs))
    
    elif text == "🏃 Запустить" or text == "/run":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:1000]}\n```", parse_mode="Markdown")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid] = {"code": ""}
        send_message(chat_id, "Очищено!")
    
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["🌐", "📝", "🔧", "🐛", "🏃", "🗑"]):
        current = user_sessions[uid]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        send_message(chat_id, f"✅ Сохранено! {len(new_code)} символов\n\n🌐 /site - открыть сайт с кодом")

# ==================== ЗАПУСК ====================
def run_bot():
    logger.info("Telegram бот запущен!")
    last_id = 0
    while True:
        try:
            updates = get_updates(offset=last_id + 1 if last_id else None)
            for upd in updates:
                if upd["update_id"] in processed_ids:
                    continue
                processed_ids.add(upd["update_id"])
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                if "message" in upd:
                    process_message(upd["message"])
                last_id = upd["update_id"]
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"Веб-сервер на порту {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
