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
user_published_pages = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== ФУНКЦИЯ СОЗДАНИЯ HTML СТРАНИЦЫ ====================
def create_html_page(code, filename="code.py", page_title="Мой код"):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{page_title}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
    <style>
        body {{ background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); font-family: monospace; padding: 40px 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{ background: rgba(0,0,0,0.5); border-radius: 20px; padding: 20px; margin-bottom: 20px; }}
        h1 {{ color: #667eea; }}
        .code-block {{ background: #1e1e1e; border-radius: 16px; overflow: hidden; }}
        .code-header {{ background: #2d2d2d; padding: 10px 20px; display: flex; justify-content: space-between; }}
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

# ==================== ПЕСОЧНИЦА ====================
SANDBOX_HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Python Песочница</title>
    <style>
        body { background: #1e1e1e; font-family: monospace; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .panels { display: flex; gap: 20px; flex-wrap: wrap; }
        .editor-panel { flex: 2; }
        .output-panel { flex: 1; }
        textarea { width: 100%; height: 400px; background: #1e1e1e; color: #d4d4d4; border: 1px solid #444; font-family: monospace; padding: 15px; }
        .output { background: #1e1e1e; border: 1px solid #444; padding: 15px; height: 400px; overflow: auto; white-space: pre-wrap; color: #d4d4d4; }
        button { background: #0e639c; color: white; border: none; padding: 10px 20px; margin-top: 10px; cursor: pointer; border-radius: 6px; }
        button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        h1 { color: #667eea; }
        .success { color: #6a9955; }
        .error { color: #f48771; }
    </style>
</head>
<body>
<div class="container">
    <h1>Python Песочница</h1>
    <div class="panels">
        <div class="editor-panel">
            <textarea id="code">print("Hello, World!")
for i in range(3):
    print(f"Number {i}")</textarea>
            <button class="primary" onclick="runCode()">Запустить</button>
            <button onclick="clearCode()">Очистить</button>
        </div>
        <div class="output-panel">
            <div class="output" id="output">Готов к работе</div>
        </div>
    </div>
</div>
<script>
async function runCode() {
    const code = document.getElementById('code').value;
    if (!code.trim()) { document.getElementById('output').innerHTML = '<span class="error">Нет кода</span>'; return; }
    document.getElementById('output').innerHTML = 'Выполнение...';
    const res = await fetch('/api/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    if (data.success) {
        document.getElementById('output').innerHTML = '<span class="success">Выполнено!</span><br><br>' + (data.output || '(нет вывода)');
    } else {
        document.getElementById('output').innerHTML = '<span class="error">Ошибка:</span><br><br>' + data.error;
    }
}
function clearCode() { document.getElementById('code').value = ''; document.getElementById('output').innerHTML = 'Редактор очищен'; }
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

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except:
        pass

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

def auto_fix_code(code):
    if not code.strip():
        return code, "Нет кода"
    fixed = code
    fixes = []
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes.append("добавлены двоеточия")
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes.append("исправлено деление на ноль")
    if fixes:
        return fixed, f"✅ Исправлено: {', '.join(fixes)}"
    return fixed, "✅ Код уже в хорошем состоянии"

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ Использование eval() - опасно")
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксическая ошибка: {e.msg}")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

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
    return f"📊 Анализ сложности:\n\nСтрок кода: {code_lines}\nФункций: {functions}\nСложность: {complexity:.1f}\nОценка: {rating}"

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

def save_code_with_bot_tag(user_id, filename, content):
    base, ext = os.path.splitext(filename)
    bot_filename = f"{base}_bot{ext}"
    header = f"# 🤖 Создано AI Code Bot\n# Дата: {datetime.now()}\n# Файл: {filename}\n\n"
    with open(bot_filename, "w") as f:
        f.write(header + content)
    return bot_filename

def detect_files_from_text(text):
    files = {}
    pattern = r'###\s*Файл:\s*([^\s]+)\s*```(?:\w+)?\n(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    for filename, content in matches:
        files[filename.strip()] = content.strip()
    return files

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "📊 Анализ"],
            ["🗑 Удалить последний", "📜 История"],
            ["🌐 Веб-редактор", "🌍 Опубликовать сайт"],
            ["🐍 Песочница", "🗑 Очистить всё"],
            ["❓ Помощь"]
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
    
    # Распознаём несколько файлов
    files = detect_files_from_text(text)
    if files:
        for name, content in files.items():
            user_sessions[uid]["code"] = content
        send_message(chat_id, f"✅ Распознано {len(files)} файлов:\n" + "\n".join(f"• {n}" for n in files.keys()))
        return
    
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю писать, исправлять и публиковать код!\n\n"
            "*Команды:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код (с подписью _bot)\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "🗑 /undo — удалить последнюю часть\n"
            "📜 /history — история кода\n"
            "🌐 /web — веб-редактор\n"
            "🌍 /publish — опубликовать сайт с кодом\n"
            "🐍 /sandbox — песочница\n"
            "🗑 /reset — очистить всё\n"
            "❓ /help — помощь",
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/help" or text == "❓ Помощь":
        send_message(chat_id, 
            "📚 *Команды:*\n\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать файл (с подписью _bot)\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "🗑 /undo — удалить последнюю отправленную часть\n"
            "📜 /history — показать историю кода\n"
            "🌐 /web — открыть веб-редактор\n"
            "🌍 /publish — создать сайт с кодом\n"
            "🐍 /sandbox — открыть песочницу\n"
            "🗑 /reset — очистить всё\n"
            "❓ /help — эта справка",
            parse_mode="Markdown")
    
    elif text == "/sandbox" or text == "🐍 Песочница":
        send_message(chat_id, f"🐍 *Песочница для кода:*\n{bot_url}/sandbox", parse_mode="Markdown")
    
    elif text == "/web" or text == "🌐 Веб-редактор":
        send_message(chat_id, f"🎨 *Веб-редактор:*\n{bot_url}/web/{uid}", parse_mode="Markdown")
    
    elif text == "/publish" or text == "🌍 Опубликовать сайт":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для публикации!")
            return
        page_id = f"{uid}_{int(time.time())}"
        html_page = create_html_page(code, "code.py", "AI Code Bot - Мой код")
        user_published_pages[page_id] = html_page
        send_message(chat_id, f"✅ *Сайт с кодом создан!*\n\n🔗 {bot_url}/publish/{page_id}\n\nЭту ссылку можно отправить кому угодно!", parse_mode="Markdown")
    
    elif text == "/show" or text == "📝 Показать код":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь мне код!")
        else:
            send_message(chat_id, f"```python\n{code[:3000]}\n```", parse_mode="Markdown")
    
    elif text == "/done" or text == "💾 Скачать код":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = save_code_with_bot_tag(uid, "code.py", code)
        send_document(chat_id, filename, "✅ Готовый код (с подписью _bot)")
        os.remove(filename)
    
    elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для исправления")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
    
    elif text == "/bugs" or text == "🐛 Ошибки":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для проверки")
            return
        bugs = find_bugs(code)
        send_message(chat_id, "\n".join(bugs))
    
    elif text == "/complexity" or text == "📊 Анализ":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для анализа")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, analysis)
    
    elif text == "/run" or text == "🏃 Запустить":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для запуска")
            return
        send_message(chat_id, "⏳ Выполнение...")
        result = run_code_safe(code)
        if result["success"]:
            output = result["output"][:3000] if result["output"] else "(нет вывода)"
            send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```", parse_mode="Markdown")
        else:
            error = result["error"][:2000] if result["error"] else "Неизвестная ошибка"
            send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```", parse_mode="Markdown")
    
    elif text == "/undo" or text == "🗑 Удалить последний":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 Нет частей для удаления")
        else:
            last = history.pop()
            user_sessions[uid]["history"] = history
            
            # Восстанавливаем код из оставшихся частей
            if history:
                full_code = "\n\n".join([h["part"] for h in history])
                user_sessions[uid]["code"] = full_code
                send_message(chat_id, f"🗑 Удалена последняя часть. Осталось частей: {len(history)}")
            else:
                user_sessions[uid]["code"] = ""
                send_message(chat_id, "🗑 Удалена последняя часть. Код полностью очищен.")
    
    elif text == "/history" or text == "📜 История":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 История пуста")
        else:
            msg = "📜 *История кода:*\n\n"
            for i, h in enumerate(history[-10:], 1):
                msg += f"{i}. [{h.get('time', '')[:16]}] `{h.get('part', '')[:40]}...`\n"
            send_message(chat_id, msg, parse_mode="Markdown")
    
    elif text == "/reset" or text == "🗑 Очистить всё":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
    
    # Обработка обычного кода (не команда)
    elif text and not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🏃", "🗑", "🌐", "❓", "🌍", "📜", "🐍"]):
        history = user_sessions[uid].get("history", [])
        history.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "part": text})
        user_sessions[uid]["history"] = history
        
        current = user_sessions[uid].get("code", "")
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        
        send_message(chat_id, f"✅ *Часть кода сохранена!*\n📊 Всего символов: {len(new_code)}\n📦 Частей: {len(history)}\n\n📝 /show — посмотреть код\n🔧 /fix — исправить ошибки", parse_mode="Markdown")

# ==================== HTTP СЕРВЕР ====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/web/'):
            uid = self.path.split('/')[2]
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Редактор</title>
<style>body{{background:#1e1e1e;margin:0;}} #editor{{height:100vh;}}</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body><div id="editor"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor; const USER_ID={uid};
require.config({{paths:{{vs:'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs'}}}});
require(['vs/editor/editor.main'],function(){{
    editor=monaco.editor.create(document.getElementById('editor'),{{
        value:'# Ваш код',language:'python',theme:'vs-dark',automaticLayout:true
    }});
    editor.onDidChangeModelContent(()=>{{
        fetch('/api/save_code',{{
            method:'POST',headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{user_id:USER_ID,code:editor.getValue()}})
        }});
    }});
}});
</script></body></html>'''
            self.wfile.write(html.encode('utf-8'))
        elif self.path.startswith('/publish/'):
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
        elif self.path == '/api/save_code':
            uid = data.get('user_id')
            code = data.get('code', '')
            if uid not in user_sessions:
                user_sessions[uid] = {}
            user_sessions[uid]['code'] = code
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 Telegram бот запущен!")
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
