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
from urllib.parse import urlparse
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
user_published_pages = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== ФУНКЦИЯ СОЗДАНИЯ САЙТА С КОДОМ ====================
def create_code_website(code, filename="code.py"):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>📄 Просмотр кода</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
    <style>
        body {{ background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); font-family: monospace; padding: 40px 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{ background: rgba(0,0,0,0.5); border-radius: 20px; padding: 20px; margin-bottom: 20px; }}
        h1 {{ color: #667eea; }}
        .code-block {{ background: #1e1e1e; border-radius: 16px; overflow: hidden; }}
        .code-header {{ background: #2d2d2d; padding: 10px 20px; }}
        pre {{ margin: 0; padding: 20px; overflow-x: auto; }}
        .copy-btn {{ background: #0e639c; border: none; color: white; padding: 5px 15px; border-radius: 6px; cursor: pointer; }}
        .footer {{ text-align: center; margin-top: 20px; color: #666; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📄 {filename}</h1>
        <p>Создано AI Code Bot • {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>
    </div>
    <div class="code-block">
        <div class="code-header">
            <span>📄 {filename}</span>
            <button class="copy-btn" onclick="copyCode()">📋 Копировать</button>
        </div>
        <pre><code class="language-python">{escaped_code}</code></pre>
    </div>
    <div class="footer">🤖 Создано с помощью AI Code Bot в Telegram</div>
</div>
<script>
    function copyCode() {{
        const code = document.querySelector('code').innerText;
        navigator.clipboard.writeText(code);
        const btn = document.querySelector('.copy-btn');
        btn.innerHTML = '✅ Скопировано!';
        setTimeout(() => btn.innerHTML = '📋 Копировать', 2000);
    }}
</script>
</body>
</html>'''

# ==================== ОТДЕЛЬНАЯ ПЕСОЧНИЦА ====================
SANDBOX_HTML = '''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>🐍 Песочница</title>
<style>
body{background:#1e1e1e;font-family:monospace;padding:20px;}
.container{max-width:1400px;margin:0 auto;}
.panels{display:flex;gap:20px;flex-wrap:wrap;}
.editor-panel{flex:2;}
.output-panel{flex:1;}
textarea{width:100%;height:400px;background:#1e1e1e;color:#fff;border:1px solid #444;font-family:monospace;padding:15px;}
.output{background:#1e1e1e;border:1px solid #444;padding:15px;height:400px;overflow:auto;white-space:pre-wrap;}
button{background:#0e639c;color:white;border:none;padding:10px 20px;margin-top:10px;cursor:pointer;}
button.primary{background:linear-gradient(135deg,#667eea,#764ba2);}
</style>
</head>
<body>
<div class="container">
<h1>🐍 Python Песочница</h1>
<div class="panels">
<div class="editor-panel"><textarea id="code">print("Hello, World!")</textarea><button class="primary" onclick="runCode()">▶️ Запустить</button></div>
<div class="output-panel"><div class="output" id="output">⚡ Готов</div></div>
</div>
</div>
<script>
async function runCode(){
    const code=document.getElementById('code').value;
    const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code})});
    const data=await res.json();
    document.getElementById('output').innerHTML=data.success?data.output||'✅ Выполнено':`❌ ${data.error}`;
}
</script>
</body>
</html>'''

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
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
    except:
        return []

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

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "📦 Опубликовать сайт"],
            ["🔧 Исправить", "🐛 Ошибки"],
            ["🏃 Запустить", "🐍 Песочница"],
            ["🗑 Очистить"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА TELEGRAM ====================
def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": []}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю с кодом!\n\n"
            "*Как работает:*\n"
            "1. Отправь мне код\n"
            "2. Я создам САЙТ с твоим кодом и дам ссылку\n"
            "3. Ты можешь поделиться ссылкой с кем угодно\n\n"
            "*Команды:*\n"
            "📝 /show — показать код\n"
            "📦 /publish — создать сайт с кодом\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "🐍 /sandbox — открыть песочницу\n"
            "🗑 /reset — очистить код",
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/sandbox" or text == "🐍 Песочница":
        send_message(chat_id, f"🐍 *Песочница для кода:*\n{bot_url}/sandbox", parse_mode="Markdown")
    
    elif text == "/publish" or text == "📦 Опубликовать сайт":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для публикации! Сначала отправь код.")
            return
        page_id = f"{uid}_{int(time.time())}"
        html = create_code_website(code, "code.py")
        user_published_pages[page_id] = html
        send_message(chat_id, f"✅ *Сайт с кодом создан!*\n\n🔗 {bot_url}/publish/{page_id}\n\nЭту ссылку можно отправить кому угодно!", parse_mode="Markdown")
    
    elif text == "/show" or text == "📝 Показать код":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь мне код!")
        else:
            send_message(chat_id, f"```python\n{code[:3000]}\n```", parse_mode="Markdown")
    
    elif text == "/fix" or text == "🔧 Исправить":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        # Простое исправление
        fixed = code
        if '/ 0' in fixed:
            fixed = fixed.replace('/ 0', '/ 1')
        if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
            fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        user_sessions[uid]["code"] = fixed
        send_message(chat_id, "✅ Код исправлен!")
    
    elif text == "/bugs" or text == "🐛 Ошибки":
        code = user_sessions[uid]["code"]
        bugs = []
        if '/ 0' in code:
            bugs.append("❌ Деление на ноль")
        if 'eval(' in code:
            bugs.append("❌ Использование eval()")
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            bugs.append(f"❌ {e.msg}")
        if bugs:
            send_message(chat_id, "\n".join(bugs))
        else:
            send_message(chat_id, "✅ Ошибок не найдено!")
    
    elif text == "/run" or text == "🏃 Запустить":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        send_message(chat_id, "⏳ Выполнение...")
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:1000]}\n```", parse_mode="Markdown")
    
    elif text == "/reset" or text == "🗑 Очистить":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "🧹 Код очищен!")
    
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "📦", "🔧", "🐛", "🏃", "🐍", "🗑"]):
        user_sessions[uid]["code"] = text
        user_sessions[uid]["history"].append({"time": str(datetime.now()), "code": text[:100]})
        
        # АВТОМАТИЧЕСКИ СОЗДАЁМ САЙТ
        page_id = f"{uid}_{int(time.time())}"
        html = create_code_website(text, "code.py")
        user_published_pages[page_id] = html
        
        send_message(chat_id, 
            f"✅ *Код сохранён!*\n"
            f"📊 Размер: {len(text)} символов\n\n"
            f"🌍 *Твой код опубликован на сайте:*\n{bot_url}/publish/{page_id}\n\n"
            f"📝 /show — посмотреть код\n"
            f"📦 /publish — обновить сайт\n"
            f"🔧 /fix — исправить ошибки",
            parse_mode="Markdown")

# ==================== HTTP СЕРВЕР ====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/publish/'):
            page_id = self.path.split('/')[2]
            html = user_published_pages.get(page_id, "<h1>Страница не найдена</h1>")
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/sandbox':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(SANDBOX_HTML.encode('utf-8'))
        elif self.path == '/' or self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        data = json.loads(body) if body else {}
        
        if self.path == '/api/run':
            result = run_code_safe(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 Telegram бот запущен! Жду сообщения...")
    while True:
        try:
            updates = get_updates()
            for upd in updates:
                uid = upd["update_id"]
                if uid in processed_ids:
                    continue
                processed_ids.add(uid)
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                if "message" in upd:
                    process_message(upd["message"])
                last_update_id = uid
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
