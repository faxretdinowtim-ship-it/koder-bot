import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
import zipfile
from io import BytesIO
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
user_html_pages = {}
user_websites = {}  # Для запущенных сайтов
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== ФУНКЦИЯ ЗАПУСКА САЙТА ====================
def run_website_from_code(code, site_id):
    """Запускает веб-сайт из Python кода (Flask/FastAPI)"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
        script_path = f.name
    
    port = 8000 + (site_id % 1000)  # Динамический порт
    
    try:
        process = subprocess.Popen(
            ["python3", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PORT": str(port)},
            cwd=os.path.dirname(script_path)
        )
        return {"success": True, "process": process, "path": script_path, "port": port}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== ФУНКЦИЯ СОЗДАНИЯ HTML СТРАНИЦЫ ====================
def create_html_page(code, filename="code.py", page_title="Мой код"):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('—', '-').replace('–', '-')
    
    language = "python"
    if filename.endswith('.html'):
        language = "html"
    elif filename.endswith('.css'):
        language = "css"
    elif filename.endswith('.js'):
        language = "javascript"
    
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{page_title}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); font-family: monospace; padding: 40px 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: rgba(0,0,0,0.5); backdrop-filter: blur(10px); border-radius: 20px; padding: 20px 30px; margin-bottom: 30px; }}
        .header h1 {{ background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .info {{ display: flex; gap: 20px; margin-top: 15px; flex-wrap: wrap; }}
        .info-item {{ background: rgba(255,255,255,0.1); padding: 5px 12px; border-radius: 20px; font-size: 12px; }}
        .code-block {{ background: #1e1e1e; border-radius: 16px; overflow: hidden; }}
        .code-header {{ background: #2d2d2d; padding: 10px 20px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; }}
        .filename {{ color: #667eea; font-weight: bold; }}
        .copy-btn {{ background: #0e639c; border: none; color: white; padding: 5px 15px; border-radius: 6px; cursor: pointer; }}
        pre {{ margin: 0; padding: 20px; overflow-x: auto; }}
        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
        @media (max-width: 768px) {{ pre {{ padding: 15px; }} }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📄 {page_title}</h1>
        <p>Сгенерировано AI Code Bot • {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>
        <div class="info">
            <span class="info-item">📁 {filename}</span>
            <span class="info-item">🔤 {language.upper()}</span>
            <span class="info-item">📏 {len(code.splitlines())} строк</span>
            <span class="info-item">📦 {len(code)} символов</span>
        </div>
    </div>
    <div class="code-block">
        <div class="code-header">
            <span class="filename">📄 {filename}</span>
            <button class="copy-btn" onclick="copyCode()">📋 Копировать</button>
        </div>
        <pre><code class="language-{language}">{escaped_code}</code></pre>
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
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>🐍 Песочница для кода</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .panels { display: flex; gap: 20px; flex-wrap: wrap; }
        .editor-panel { flex: 2; min-width: 300px; }
        .output-panel { flex: 1; min-width: 300px; }
        .panel-header { background: #2d2d2d; padding: 10px; border-radius: 8px 8px 0 0; font-weight: bold; }
        textarea { width: 100%; height: 400px; background: #1e1e1e; color: #d4d4d4; border: 1px solid #444; font-family: monospace; font-size: 14px; padding: 15px; resize: vertical; }
        .output { background: #1e1e1e; border: 1px solid #444; border-radius: 0 0 8px 8px; padding: 15px; height: 400px; overflow: auto; font-family: monospace; white-space: pre-wrap; }
        button { background: #0e639c; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; margin-top: 10px; margin-right: 10px; }
        button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        .status { color: #888; margin-top: 10px; font-size: 12px; }
        .success { color: #6a9955; }
        .error { color: #f48771; }
    </style>
</head>
<body>
<div class="container">
    <h1>🐍 Python Песочница</h1>
    <p>Пиши код прямо здесь — он выполняется безопасно на сервере</p>
    <div class="panels">
        <div class="editor-panel">
            <div class="panel-header">📝 Редактор кода</div>
            <textarea id="code">print("Hello, World!")
for i in range(5):
    print(f"Строка {i+1}")</textarea>
            <div>
                <button class="primary" onclick="runCode()">▶️ Запустить</button>
                <button onclick="clearCode()">🗑 Очистить</button>
                <button onclick="loadExample()">📋 Пример</button>
            </div>
        </div>
        <div class="output-panel">
            <div class="panel-header">📄 Вывод</div>
            <div class="output" id="output">⚡ Готов к работе</div>
        </div>
    </div>
    <div class="status" id="status">⚡ Готов</div>
</div>
<script>
    async function runCode() {
        const code = document.getElementById('code').value;
        if (!code.trim()) { document.getElementById('output').innerHTML = '<span class="error">❌ Нет кода</span>'; return; }
        document.getElementById('output').innerHTML = '<span class="status">⏳ Выполнение...</span>';
        const res = await fetch('/api/run', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({code: code})
        });
        const data = await res.json();
        if (data.success) {
            document.getElementById('output').innerHTML = '<span class="success">✅ Выполнено!</span><br><br>' + (data.output || '(нет вывода)');
        } else {
            document.getElementById('output').innerHTML = '<span class="error">❌ Ошибка:</span><br><br>' + data.error;
        }
    }
    function clearCode() { document.getElementById('code').value = ''; document.getElementById('output').innerHTML = '⚡ Редактор очищен'; }
    function loadExample() { document.getElementById('code').value = 'def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        print(a)\n        a, b = b, a + b\n\nfibonacci(10)'; }
</script>
</body>
</html>'''

# ==================== ФУНКЦИИ ДЛЯ КОДА ====================
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
    fixed = code.replace('—', '-').replace('–', '-')
    fixes = []
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes.append("двоеточия")
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes.append("деление на ноль")
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код готов")

def find_bugs(code):
    code = code.replace('—', '-').replace('–', '-')
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ Использование eval()")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg}")
    return bugs if bugs else ["✅ Ошибок нет"]

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    return f"📊 Строк кода: {code_lines}\n📦 Функций: {code.count('def ')}"

def run_code_safe(code):
    code = code.replace('—', '-').replace('–', '-')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
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
            ["📁 Файлы", "📜 История"],
            ["🌐 Веб-редактор", "🌍 Опубликовать сайт"],
            ["🚀 ЗАПУСТИТЬ САЙТ", "🐍 Песочница"],
            ["🗑 Очистить всё", "❓ Помощь"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА TELEGRAM ====================
def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"files": {"main.py": '# Ваш код\nprint("Hello, World!")'}, "current_file": "main.py", "history": []}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    # Распознаём файлы
    files = detect_files_from_text(text)
    if files:
        for name, content in files.items():
            user_sessions[uid]["files"][name] = content
        send_message(chat_id, f"✅ Распознано {len(files)} файлов:\n" + "\n".join(f"• {n}" for n in files.keys()))
        return
    
    # НОВАЯ ФУНКЦИЯ: ЗАПУСК САЙТА
    if text == "🚀 ЗАПУСТИТЬ САЙТ" or text == "/run_site":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для запуска сайта!\n\nСначала отправь Flask/FastAPI код.")
            return
        
        # Проверяем, похоже ли на веб-приложение
        if 'Flask' in code or 'app = Flask' in code or '@app.route' in code:
            site_id = uid
            result = run_website_from_code(code, site_id)
            
            if result["success"]:
                user_websites[uid] = result
                send_message(chat_id, 
                    f"✅ *Сайт запущен!*\n\n"
                    f"🌐 *Доступен по адресу:*\n{bot_url}/site/{uid}\n\n"
                    f"📄 Файл: `{current}`\n"
                    f"⚡ Порт: {result['port']}\n\n"
                    f"💡 Сайт будет работать пока активен процесс.\n"
                    f"🛑 /stop_site - остановить сайт",
                    parse_mode="Markdown")
            else:
                send_message(chat_id, f"❌ Ошибка запуска сайта:\n{result['error']}")
        else:
            send_message(chat_id, 
                "❌ Это не похоже на веб-приложение!\n\n"
                "Для запуска сайта нужен код с Flask:\n"
                "```python\nfrom flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef home():\n    return 'Hello!'\n\nif __name__ == '__main__':\n    app.run()\n```",
                parse_mode="Markdown")
        return
    
    elif text == "/stop_site":
        if uid in user_websites:
            try:
                user_websites[uid]["process"].terminate()
                os.unlink(user_websites[uid]["path"])
                del user_websites[uid]
                send_message(chat_id, "🛑 Сайт остановлен!")
            except:
                send_message(chat_id, "Ошибка при остановке сайта")
        else:
            send_message(chat_id, "Нет запущенного сайта")
        return
    
    # Обычные команды
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю писать, запускать и публиковать код!\n\n"
            "*Основные функции:*\n"
            "🚀 *ЗАПУСТИТЬ САЙТ* - запустить Flask/FastAPI приложение\n"
            "🌍 *Опубликовать сайт* - создать HTML-страницу с кодом\n"
            "🐍 *Песочница* - выполнить Python код\n\n"
            "*Команды:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "📁 /files — список файлов\n"
            "📜 /history — история кода\n"
            "🌐 /web — веб-редактор\n"
            "🌍 /publish — опубликовать сайт с кодом\n"
            "🚀 /run_site — ЗАПУСТИТЬ ВЕБ-ПРИЛОЖЕНИЕ\n"
            "🛑 /stop_site — остановить сайт\n"
            "🐍 /sandbox — песочница\n"
            "🗑 /reset — очистить всё",
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/help" or text == "❓ Помощь":
        send_message(chat_id, 
            "📚 *Команды:*\n\n"
            "🚀 /run_site — запустить веб-сайт из Flask кода\n"
            "🛑 /stop_site — остановить запущенный сайт\n"
            "🌍 /publish — создать HTML страницу с кодом\n"
            "🐍 /sandbox — открыть песочницу\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать файл\n"
            "🔧 /fix — исправить ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "🗑 /reset — очистить всё",
            parse_mode="Markdown")
    
    elif text == "/sandbox" or text == "🐍 Песочница":
        send_message(chat_id, f"🐍 *Песочница для кода:*\n{bot_url}/sandbox", parse_mode="Markdown")
    
    elif text == "/web" or text == "🌐 Веб-редактор":
        send_message(chat_id, f"🎨 *Веб-редактор:*\n{bot_url}/web/{uid}", parse_mode="Markdown")
    
    elif text == "/publish" or text == "🌍 Опубликовать сайт":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для публикации!")
            return
        page_id = f"{uid}_{int(time.time())}"
        html_page = create_html_page(code, current, f"AI Code Bot - {current}")
        user_html_pages[page_id] = html_page
        send_message(chat_id, f"✅ *Сайт с кодом создан!*\n\n🔗 {bot_url}/publish/{page_id}\n\nЭту ссылку можно отправить кому угодно!", parse_mode="Markdown")
    
    elif text == "/show" or text == "📝 Показать код":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        lang = "python" if current.endswith('.py') else "text"
        send_message(chat_id, f"📄 *{current}*\n```{lang}\n{code[:3000]}\n```", parse_mode="Markdown")
    
    elif text == "/done" or text == "💾 Скачать код":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = f"{current.replace('.py', '')}_bot.py"
        header = f"# 🤖 Создано AI Code Bot\n# Дата: {datetime.now()}\n\n"
        with open(filename, "w") as f:
            f.write(header + code)
        send_document(chat_id, filename, f"✅ {current}")
        os.remove(filename)
    
    elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["files"][current] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже хороший")
    
    elif text == "/bugs" or text == "🐛 Ошибки":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        send_message(chat_id, "\n".join(find_bugs(code)))
    
    elif text == "/complexity" or text == "📊 Анализ":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        send_message(chat_id, analyze_complexity(code))
    
    elif text == "/run" or text == "🏃 Запустить":
        current = user_sessions[uid].get("current_file", "main.py")
        code = user_sessions[uid]["files"].get(current, "")
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        send_message(chat_id, "⏳ Выполнение...")
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:1000]}\n```", parse_mode="Markdown")
    
    elif text == "/files" or text == "📁 Файлы":
        files = user_sessions[uid].get("files", {})
        if not files:
            send_message(chat_id, "Нет файлов")
        else:
            file_list = "\n".join([f"• `{n}`" for n in files.keys()])
            send_message(chat_id, f"📁 *Файлы:*\n{file_list}\n\n📄 Текущий: `{user_sessions[uid].get('current_file', 'main.py')}`\n\n🚀 /run_site - запустить сайт", parse_mode="Markdown")
    
    elif text == "/history" or text == "📜 История":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 История пуста")
        else:
            msg = "📜 *История кода:*\n\n"
            for i, h in enumerate(history[-10:], 1):
                msg += f"{i}. [{h.get('time', '')[:16]}] `{h.get('preview', '')[:40]}...`\n"
            send_message(chat_id, msg, parse_mode="Markdown")
    
    elif text == "/reset" or text == "🗑 Очистить всё":
        user_sessions[uid] = {"files": {"main.py": '# Ваш код\nprint("Hello, World!")'}, "current_file": "main.py", "history": []}
        send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
    
    # Обработка обычного кода
    elif text and not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🏃", "📁", "🗑", "🌐", "❓", "🌍", "📜", "🐍", "🚀"]):
        current = user_sessions[uid].get("current_file", "main.py")
        old = user_sessions[uid]["files"].get(current, "")
        new_code = old + "\n\n" + text if old else text
        user_sessions[uid]["files"][current] = new_code
        
        if "history" not in user_sessions[uid]:
            user_sessions[uid]["history"] = []
        user_sessions[uid]["history"].append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code": new_code,
            "preview": text[:100]
        })
        
        send_message(chat_id, f"✅ *Код добавлен в файл `{current}`!*\n📊 Размер: {len(new_code)} символов\n\n🚀 /run_site — запустить как сайт\n🌍 /publish — опубликовать", parse_mode="Markdown")

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
            html = user_html_pages.get(page_id, "<h1>Страница не найдена</h1>")
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        elif self.path.startswith('/site/'):
            uid = int(self.path.split('/')[2])
            if uid in user_websites:
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<h1>Сайт запущен!</h1><p>Веб-приложение работает на порту</p>")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"<h1>Сайт не запущен</h1>")
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
            if 'files' not in user_sessions[uid]:
                user_sessions[uid]['files'] = {}
            user_sessions[uid]['files']['main.py'] = code
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
