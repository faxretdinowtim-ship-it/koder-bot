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

# ==================== ФУНКЦИИ АНАЛИЗА ====================
def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "[GREEN] Low"
    elif complexity < 20:
        rating = "[YELLOW] Medium"
    else:
        rating = "[RED] High"
    return f"**Analysis:**\n\nCode lines: {code_lines}\nFunctions: {functions}\nComplexity: {complexity:.1f}\nRating: {rating}"

def find_bugs(code):
    bugs = []
    patterns = [
        (r'/\s*0\b', 'Division by zero', 'CRITICAL'),
        (r'eval\s*\(', 'Using eval()', 'HIGH'),
        (r'except\s*:', 'Bare except', 'MEDIUM'),
        (r'password\s*=\s*[\'"]', 'Hardcoded password', 'CRITICAL'),
    ]
    for pattern, msg, severity in patterns:
        if re.search(pattern, code):
            bugs.append(f"- {msg} [{severity}]")
    if not bugs:
        return "No bugs found!"
    return "**Found bugs:**\n" + "\n".join(bugs)

def validate_code(code):
    try:
        compile(code, '<string>', 'exec')
        return "Code is valid!"
    except SyntaxError as e:
        return f"Syntax error: {e.msg}\nLine: {e.lineno}"

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
        return {"success": False, "output": "", "error": "Timeout (5 sec)"}
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
            "AI Code Assembler Bot\n\n"
            "Hello! I assemble code from parts using DeepSeek AI.\n\n"
            f"Web editor: {bot_url}/web/{user_id}\n\n"
            "Commands:\n"
            "/show - show code\n/done - download file\n/reset - clear\n"
            "/order - reorder functions\n/complexity - analyze complexity\n/bugs - find bugs\n"
            "/validate - validate code\n/run - run code\n/web - web editor\n/help - help", parse_mode="Markdown")
    
    elif text == "/help":
        send_message(chat_id, "Commands: /start, /show, /done, /reset, /order, /complexity, /bugs, /validate, /run, /web", parse_mode="Markdown")
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        send_message(chat_id, f"```python\n{code if code else '# Code is empty'}\n```", parse_mode="Markdown")
    
    elif text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "No code to save")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w") as f:
            f.write(code)
        send_file(chat_id, filename, f"Code ready! {len(code)} chars")
        os.remove(filename)
    
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        send_message(chat_id, "Code cleared!")
    
    elif text == "/order":
        user_sessions[user_id]["code"] = reorder_code(user_sessions[user_id]["code"])
        send_message(chat_id, "Code reordered!")
    
    elif text == "/complexity":
        send_message(chat_id, analyze_complexity(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "/bugs":
        send_message(chat_id, find_bugs(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "/validate":
        send_message(chat_id, validate_code(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "/run":
        result = run_code_safe(user_sessions[user_id]["code"])
        if result["success"]:
            send_message(chat_id, f"Success!\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"Error:\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
    
    elif text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"Web editor: {bot_url}/web/{user_id}", parse_mode="Markdown")
    
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "AI analyzing code...")
        
        if current:
            prompt = f"""Combine the code. Return ONLY the final code, no explanations.

Current code:
{current}

New part:
{text}

Final code:"""
        else:
            prompt = f"""Return ONLY this code, no comments:
{text}"""
        
        ai_response = call_deepseek(prompt)
        new_code = ai_response if ai_response else (current + "\n\n" + text if current else text)
        user_sessions[user_id]["code"] = new_code
        send_message(chat_id, f"Code updated! {len(new_code)} chars\n/show to view", parse_mode="Markdown")

# ==================== TELEGRAM БОТ ====================
def run_telegram_bot():
    logger.info("Telegram bot started!")
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
            logger.error(f"Error: {e}")
            time.sleep(5)

# ==================== ВЕБ-СЕРВЕР ====================
WEB_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Code Editor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; }
        #editor { height: 85vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; flex-wrap: wrap; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #1177bb; }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="toolbar">
    <button onclick="saveCode()">Save</button>
    <button onclick="runCode()">Run</button>
    <button onclick="analyzeCode()">Analyze</button>
    <button onclick="downloadCode()">Download</button>
</div>
<div id="editor"></div>
<div class="status" id="status">Ready</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor;
const USER_ID = window.location.pathname.split('/')[2];
const API_URL = window.location.origin;

require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '',
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true },
        automaticLayout: true
    });
    loadCode();
});

async function loadCode() {
    const res = await fetch(`${API_URL}/api/get_code?user_id=${USER_ID}`);
    const data = await res.json();
    editor.setValue(data.code || '# Code is empty');
}

async function saveCode() {
    const code = editor.getValue();
    await fetch(`${API_URL}/api/save_code`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, code: code})
    });
    document.getElementById('status').innerText = 'Saved!';
    setTimeout(() => document.getElementById('status').innerText = 'Ready', 2000);
}

async function runCode() {
    const code = editor.getValue();
    const res = await fetch(`${API_URL}/api/run_code`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert(data.success ? (data.output || 'Success!') : 'Error: ' + data.error);
}

async function analyzeCode() {
    const code = editor.getValue();
    const res = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert(data.report);
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
</script>
</body>
</html>'''

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/web/'):
            user_id = parsed.path.split('/')[2]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(WEB_HTML.encode())
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
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_web_server():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"Web server started on port {PORT}")
    server.serve_forever()

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    run_web_server()
