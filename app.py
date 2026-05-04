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
        rating = "Низкая"
    elif complexity < 20:
        rating = "Средняя"
    else:
        rating = "Высокая"
    return f"**Анализ сложности:**\n\nСтрок кода: {code_lines}\nФункций: {functions}\nСложность: {complexity:.1f}\nОценка: {rating}"

def find_bugs(code):
    bugs = []
    patterns = [
        (r'/\s*0\b', 'Деление на ноль', 'КРИТИЧЕСКАЯ'),
        (r'eval\s*\(', 'Использование eval()', 'ВЫСОКАЯ'),
        (r'except\s*:', 'Голый except', 'СРЕДНЯЯ'),
        (r'password\s*=\s*[\'"]', 'Хардкод пароля', 'КРИТИЧЕСКАЯ'),
        (r'print\(', 'Отладочный print()', 'НИЗКАЯ'),
    ]
    for pattern, msg, severity in patterns:
        if re.search(pattern, code):
            bugs.append(f"- {msg} [{severity}]")
    if not bugs:
        return "Ошибок не найдено!"
    return "**Найденные ошибки:**\n" + "\n".join(bugs)

def validate_code(code):
    try:
        compile(code, '<string>', 'exec')
        return "Код синтаксически верен!"
    except SyntaxError as e:
        return f"Синтаксическая ошибка: {e.msg}\nСтрока: {e.lineno}"

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

# ==================== АВТОИСПРАВЛЕНИЕ ====================
def auto_fix_code(code: str) -> str:
    if not code.strip():
        return code
    
    bug_descriptions = []
    patterns = [
        (r'/\s*0\b', 'деление на ноль', 'добавьте проверку "if divisor != 0"'),
        (r'eval\s*\(', 'использование eval()', 'замените на ast.literal_eval()'),
        (r'except\s*:', 'голый except', 'используйте "except Exception as e:"'),
        (r'password\s*=\s*[\'"]', 'хардкод пароля', 'используйте os.getenv("PASSWORD")'),
    ]
    
    for pattern, msg, fix in patterns:
        if re.search(pattern, code):
            bug_descriptions.append(f"- {msg} (исправление: {fix})")
    
    if not bug_descriptions:
        return code
    
    prompt = f"""Исправь следующие ошибки в коде. Верни ТОЛЬКО исправленный код, без объяснений.

Найденные ошибки:
{chr(10).join(bug_descriptions)}

Исходный код:
{code}

Исправленный код:"""
    
    ai_response = call_deepseek(prompt)
    if ai_response:
        return ai_response
    return code

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
            "🤖 *AI Code Assembler Bot*\n\n"
            "Привет! Я собираю код из частей с помощью DeepSeek AI.\n\n"
            f"🌐 *Веб-редактор:* {bot_url}/web/{user_id}\n\n"
            "*Команды:*\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить\n"
            "/order — переставить функции\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск ошибок\n"
            "/validate — проверка синтаксиса\n"
            "/run — запустить код\n"
            "/auto_fix — автоисправление ошибок\n"
            "/web — веб-редактор\n"
            "/help — помощь", parse_mode="Markdown")
    
    elif text == "/help":
        send_message(chat_id, 
            "📚 *Команды бота:*\n\n"
            "/start — запустить бота\n"
            "/show — показать текущий код\n"
            "/done — скачать код файлом\n"
            "/reset — очистить весь код\n"
            "/order — переставить функции в правильном порядке\n"
            "/complexity — анализ сложности кода\n"
            "/bugs — поиск ошибок и уязвимостей\n"
            "/validate — проверка синтаксиса\n"
            "/run — выполнить код в песочнице\n"
            "/auto_fix — автоматически исправить ошибки\n"
            "/web — открыть веб-редактор\n"
            "/help — показать эту справку", parse_mode="Markdown")
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь мне часть кода!")
        else:
            send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
    
    elif text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для сохранения")
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
            send_message(chat_id, "🔄 Код переставлен! Импорты и функции в правильном порядке.")
    
    elif text == "/complexity":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода для анализа")
        else:
            send_message(chat_id, analyze_complexity(code), parse_mode="Markdown")
    
    elif text == "/bugs":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода для проверки")
        else:
            send_message(chat_id, find_bugs(code), parse_mode="Markdown")
    
    elif text == "/validate":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода для проверки")
        else:
            send_message(chat_id, validate_code(code), parse_mode="Markdown")
    
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
    
    elif text == "/auto_fix":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        
        send_message(chat_id, "🔧 AI исправляет ошибки...")
        fixed_code = auto_fix_code(code)
        
        if fixed_code != code:
            user_sessions[user_id]["code"] = fixed_code
            send_message(chat_id, "✅ *Код автоматически исправлен!*\n/show — посмотреть результат", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибок не найдено или AI не смог их исправить.\n/bugs — проверить вручную", parse_mode="Markdown")
    
    elif text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web/{user_id}", parse_mode="Markdown")
    
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует код...")
        
        if current:
            prompt = f"""Объедини код. Верни ТОЛЬКО итоговый код, без объяснений.

Текущий код:
{current}

Новая часть:
{text}

Итоговый код:"""
        else:
            prompt = f"""Верни ТОЛЬКО этот код, без комментариев:
{text}"""
        
        ai_response = call_deepseek(prompt)
        new_code = ai_response if ai_response else (current + "\n\n" + text if current else text)
        user_sessions[user_id]["code"] = new_code
        send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {len(new_code)} символов\n\n/show — посмотреть\n/run — запустить", parse_mode="Markdown")

# ==================== TELEGRAM БОТ ====================
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

# ==================== ВЕБ-СЕРВЕР ====================
WEB_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Editor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; }
        #editor { height: 85vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; flex-wrap: wrap; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; font-size: 14px; }
        button:hover { background: #1177bb; }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; }
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
<div class="status" id="status">Готов к работе</div>

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
    editor.setValue(data.code || '# Код пуст');
}

async function saveCode() {
    const code = editor.getValue();
    await fetch(`${API_URL}/api/save_code`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, code: code})
    });
    document.getElementById('status').innerText = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов к работе', 2000);
}

async function runCode() {
    const code = editor.getValue();
    const res = await fetch(`${API_URL}/api/run_code`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    if (data.success) {
        alert('✅ Выполнено!\n\n' + (data.output || '(нет вывода)'));
    } else {
        alert('❌ Ошибка:\n\n' + data.error);
    }
}

async function analyzeCode() {
    const code = editor.getValue();
    const res = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert('📊 Анализ сложности:\n\n' + data.report);
}

async function findBugs() {
    const code = editor.getValue();
    const res = await fetch(`${API_URL}/api/bugs`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert('🐛 Поиск ошибок:\n\n' + data.report);
}

async function autoFix() {
    const code = editor.getValue();
    const res = await fetch(`${API_URL}/api/auto_fix`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    editor.setValue(data.code);
    document.getElementById('status').innerText = '🔧 Код исправлен!';
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
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('Бот работает!'.encode('utf-8'))
        elif parsed.path.startswith('/api/get_code'):
            query = parse_qs(parsed.query)
            user_id = int(query.get('user_id', [0])[0])
            code = user_sessions.get(user_id, {}).get("code", "")
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"code": code}, ensure_ascii=False).encode('utf-8'))
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
    logger.info(f"Веб-сервер запущен на порту {PORT}")
    server.serve_forever()

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    run_web_server()
