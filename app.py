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
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
user_html_pages = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== AI ФУНКЦИИ ====================
def call_deepseek(prompt):
    """Вызов DeepSeek API"""
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code != 200:
            logger.error(f"API ошибка: {response.status_code}")
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

# ==================== НОВЫЕ AI ФУНКЦИИ ====================

def generate_code_by_description(description):
    """№1: Генерация кода по описанию"""
    prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код, без объяснений.

Описание: {description}

Код:"""
    return call_deepseek(prompt)

def generate_tests(code):
    """№2: Генерация авто-тестов"""
    prompt = f"""Напиши pytest тесты для этого кода. Верни ТОЛЬКО код тестов.

Код:
{code}

Тесты:"""
    return call_deepseek(prompt)

def convert_code(code, from_lang, to_lang):
    """№3: Преобразование кода из одного языка в другой"""
    prompt = f"""Переведи этот код с {from_lang} на {to_lang}. Верни ТОЛЬКО код.

Исходный код ({from_lang}):
{code}

Код на {to_lang}:"""
    return call_deepseek(prompt)

def code_review(code):
    """№4: Code Review - анализ кода как опытный разработчик"""
    prompt = f"""Проведи code review этого кода. Найди проблемы, дай рекомендации по улучшению.

Код:
{code}

Ответ в формате:
✅ Что хорошо:
[список]

⚠️ Что можно улучшить:
[список с конкретными строками]

💡 Рекомендации:
[список]"""
    return call_deepseek(prompt)

def add_comments(code):
    """№5: Добавление комментариев в код"""
    prompt = f"""Добавь подробные комментарии к этому коду. Объясни, что делает каждая функция и сложная часть. Верни ТОЛЬКО код с комментариями.

Код:
{code}

Код с комментариями:"""
    return call_deepseek(prompt)

def run_tests(test_code, main_code):
    """Запуск тестов (локально)"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        full_code = main_code + "\n\n" + test_code
        f.write(full_code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=10)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Превышено время выполнения тестов (10 сек)"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
    finally:
        os.unlink(temp_file)

def create_replit_export(code):
    """№18: Экспорт в Replit - создаёт ссылку для Replit"""
    # Replit принимает код через GET параметры
    encoded_code = code.replace('"', '\\"').replace('\n', '\\n')
    return f"https://replit.com/@replit/Replify?code={encoded_code[:500]}"

def create_webapp_html(code, user_id):
    """№20: Telegram WebApp - создаёт HTML страницу с редактором кода"""
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Code Editor</title>
    <style>
        body {{ background: #1e1e1e; font-family: monospace; margin: 0; padding: 20px; }}
        #editor {{ width: 100%; height: 70vh; background: #1e1e1e; color: #d4d4d4; font-family: monospace; font-size: 14px; padding: 15px; border: 1px solid #333; border-radius: 8px; }}
        .toolbar {{ margin-bottom: 10px; }}
        button {{ background: #0e639c; color: white; border: none; padding: 8px 16px; margin-right: 8px; cursor: pointer; border-radius: 4px; }}
        button:hover {{ background: #1177bb; }}
        .output {{ background: #1e1e1e; border: 1px solid #333; border-radius: 8px; padding: 15px; margin-top: 10px; height: 200px; overflow: auto; font-family: monospace; }}
        h1 {{ color: #667eea; font-size: 20px; }}
    </style>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
</head>
<body>
    <h1>🤖 AI Code Editor</h1>
    <div class="toolbar">
        <button onclick="saveCode()">💾 Сохранить</button>
        <button onclick="runCode()">▶️ Запустить</button>
        <button onclick="analyzeCode()">📊 Анализ</button>
    </div>
    <textarea id="editor">{code}</textarea>
    <div class="output" id="output">⚡ Готов к работе</div>
    <script>
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();
        
        async function saveCode() {{
            const code = document.getElementById('editor').value;
            await fetch('/api/save_code', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{user_id: {user_id}, code: code}})
            }});
            document.getElementById('output').innerHTML = '<span style="color:#6a9955">✅ Сохранено!</span>';
        }}
        
        async function runCode() {{
            const code = document.getElementById('editor').value;
            const res = await fetch('/api/run', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{code: code}})
            }});
            const data = await res.json();
            if (data.success) {{
                document.getElementById('output').innerHTML = '<span style="color:#6a9955">✅ Выполнено!</span><br><br>' + (data.output || '(нет вывода)');
            }} else {{
                document.getElementById('output').innerHTML = '<span style="color:#f48771">❌ Ошибка:</span><br><br>' + data.error;
            }}
        }}
        
        async function analyzeCode() {{
            const code = document.getElementById('editor').value;
            const res = await fetch('/api/analyze', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{code: code}})
            }});
            const data = await res.json();
            document.getElementById('output').innerHTML = '📊 ' + data.report;
        }}
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
        return True
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return False

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
        return True
    except:
        return False

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

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    classes = code.count('class ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "🟢 Низкая"
    elif complexity < 20:
        rating = "🟡 Средняя"
    else:
        rating = "🔴 Высокая"
    return f"📊 *Анализ сложности кода*\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Классов: {classes}\n• Цикломатическая сложность: {complexity:.1f}\n• Оценка: {rating}"

def smart_merge(parts):
    if not parts:
        return ""
    prompt = f"""Объедини эти части кода в один работающий файл. Расположи импорты в начале, функции в правильном порядке. Верни ТОЛЬКО итоговый код.

Части кода:
{chr(10).join([f"--- ЧАСТЬ {i+1} ---\n{p}" for i, p in enumerate(parts)])}

Итоговый код:"""
    return call_deepseek(prompt)

def fix_code(code):
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.

Код:
{code}

Исправленный код:"""
    return call_deepseek(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Верни JSON: {{"bugs": [{{"message": "...", "severity": "CRITICAL/HIGH/MEDIUM/LOW", "line": номер}}]}}

Код:
{code}"""
    response = call_deepseek(prompt)
    if response:
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group()).get("bugs", [])
        except:
            pass
    return []

def save_code_file(user_id, content):
    filename = f"code_{user_id}_bot.py"
    header = f"# 🤖 Создано AI Code Bot\n# Дата: {datetime.now()}\n\n"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(header + content)
    return filename

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🧠 УМНАЯ СКЛЕЙКА", "🔧 ИСПРАВИТЬ"],
            ["🐛 НАЙТИ ОШИБКИ", "📊 Анализ"],
            ["✨ ГЕНЕРАЦИЯ КОДА", "🧪 АВТО-ТЕСТЫ"],
            ["🔄 ПРЕОБРАЗОВАТЬ", "📋 CODE REVIEW"],
            ["📝 ДОБАВИТЬ КОММЕНТАРИИ", "🌐 WEBAPP"],
            ["⚡ REPLIT", "📜 История"],
            ["🗑 Удалить последний", "🗑 Очистить всё"],
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
        user_sessions[uid] = {"code": "", "history": [], "parts": []}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    # НОВЫЕ КОМАНДЫ
    
    # №1: Генерация кода по описанию
    if text == "/generate" or text == "✨ ГЕНЕРАЦИЯ КОДА":
        send_message(chat_id, "📝 *Опиши, какой код нужно сгенерировать:*\n\nНапример:\n- 'калькулятор на Python'\n- 'функция для сортировки списка'\n- 'бота для Telegram на aiogram'", parse_mode="Markdown")
        user_sessions[uid]["waiting_for"] = "generate"
        return
    
    elif user_sessions[uid].get("waiting_for") == "generate":
        user_sessions[uid]["waiting_for"] = None
        send_message(chat_id, "✨ AI генерирует код...\n⏳ Обычно 10-15 секунд")
        generated = generate_code_by_description(text)
        if generated:
            user_sessions[uid]["code"] = generated
            user_sessions[uid]["history"].append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": "Генерация кода"})
            if len(generated) > 3000:
                send_message(chat_id, f"✅ *Код сгенерирован!*\n📊 Размер: {len(generated)} символов\n\n📝 /show — посмотреть результат", parse_mode="Markdown")
            else:
                send_message(chat_id, f"✅ *Сгенерированный код:*\n\n```python\n{generated}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Не удалось сгенерировать код. Попробуй ещё раз.")
        return
    
    # №2: Авто-тесты
    elif text == "/tests" or text == "🧪 АВТО-ТЕСТЫ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для генерации тестов. Сначала отправь код!")
            return
        send_message(chat_id, "🧪 AI генерирует тесты...\n⏳ Обычно 5-10 секунд")
        tests = generate_tests(code)
        if tests:
            user_sessions[uid]["tests"] = tests
            send_message(chat_id, f"✅ *Сгенерированные тесты:*\n\n```python\n{tests}\n```\n\n🏃 /run_tests — запустить тесты", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Не удалось сгенерировать тесты")
        return
    
    elif text == "/run_tests":
        code = user_sessions[uid].get("code", "")
        tests = user_sessions[uid].get("tests", "")
        if not code.strip() or not tests.strip():
            send_message(chat_id, "📭 Сначала сгенерируй тесты командой /tests")
            return
        send_message(chat_id, "🏃 Запуск тестов...")
        result = run_tests(tests, code)
        if result["success"]:
            send_message(chat_id, f"✅ *Все тесты пройдены!*\n\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ *Тесты не пройдены:*\n\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
        return
    
    # №3: Преобразование кода
    elif text == "/convert" or text == "🔄 ПРЕОБРАЗОВАТЬ":
        send_message(chat_id, "📝 *Введи команду в формате:*\n`/convert java python`\n\nПоддерживаемые языки: python, java, javascript, cpp, go, rust", parse_mode="Markdown")
        user_sessions[uid]["waiting_for"] = "convert"
        return
    
    elif user_sessions[uid].get("waiting_for") == "convert" and text.startswith("/convert"):
        parts = text.split()
        if len(parts) >= 3:
            from_lang = parts[1]
            to_lang = parts[2]
            code = user_sessions[uid].get("code", "")
            if not code.strip():
                send_message(chat_id, "📭 Нет кода для преобразования")
                return
            send_message(chat_id, f"🔄 Преобразую код из {from_lang} в {to_lang}...\n⏳ Обычно 10-15 секунд")
            converted = convert_code(code, from_lang, to_lang)
            if converted:
                user_sessions[uid]["code"] = converted
                send_message(chat_id, f"✅ *Преобразованный код ({to_lang}):*\n\n```\n{converted[:3000]}\n```", parse_mode="Markdown")
            else:
                send_message(chat_id, "❌ Не удалось преобразовать код")
        else:
            send_message(chat_id, "❌ Используй: `/convert java python`")
        user_sessions[uid]["waiting_for"] = None
        return
    
    # №4: Code Review
    elif text == "/review" or text == "📋 CODE REVIEW":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для ревью")
            return
        send_message(chat_id, "📋 AI проводит Code Review...\n⏳ Обычно 10-15 секунд")
        review = code_review(code)
        send_message(chat_id, f"📋 *Code Review:*\n\n{review}", parse_mode="Markdown")
        return
    
    # №5: Добавление комментариев
    elif text == "/comment" or text == "📝 ДОБАВИТЬ КОММЕНТАРИИ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для добавления комментариев")
            return
        send_message(chat_id, "📝 AI добавляет комментарии...\n⏳ Обычно 10-15 секунд")
        commented = add_comments(code)
        if commented:
            user_sessions[uid]["code"] = commented
            send_message(chat_id, f"✅ *Код с комментариями:*\n\n```python\n{commented[:3000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Не удалось добавить комментарии")
        return
    
    # №18: Экспорт в Replit
    elif text == "/replit" or text == "⚡ REPLIT":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для экспорта в Replit")
            return
        replit_url = create_replit_export(code)
        send_message(chat_id, f"⚡ *Экспорт в Replit:*\n\n{replit_url}\n\nОткрой ссылку, чтобы запустить код в Replit!", parse_mode="Markdown")
        return
    
    # №20: Telegram WebApp
    elif text == "/webapp" or text == "🌐 WEBAPP":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для WebApp")
            return
        html = create_webapp_html(code, uid)
        user_html_pages[f"webapp_{uid}"] = html
        send_message(chat_id, f"🌐 *Telegram WebApp Editor:*\n\n{bot_url}/webapp/{uid}\n\nОткрой в Telegram (нажми на кнопку ниже)", parse_mode="Markdown")
        
        # Отправляем кнопку для открытия WebApp
        reply_markup = {
            "inline_keyboard": [[{
                "text": "🚀 ОТКРЫТЬ РЕДАКТОР",
                "web_app": {"url": f"{bot_url}/webapp/{uid}"}
            }]]
        }
        requests.post(f"{API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "🚀 Нажми на кнопку, чтобы открыть редактор в Telegram!",
            "reply_markup": json.dumps(reply_markup)
        })
        return
    
    # ОСТАЛЬНЫЕ КОМАНДЫ (из предыдущей версии)
    elif text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot (DeepSeek) - ПОЛНАЯ ВЕРСИЯ*\n\n"
            "Привет! Я использую ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ!\n\n"
            "*НОВЫЕ ФУНКЦИИ:*\n"
            "✨ /generate — создать код по описанию\n"
            "🧪 /tests — сгенерировать авто-тесты\n"
            "🔄 /convert — преобразовать код в другой язык\n"
            "📋 /review — Code Review\n"
            "📝 /comment — добавить комментарии\n"
            "⚡ /replit — экспорт в Replit\n"
            "🌐 /webapp — Telegram WebApp редактор\n\n"
            "*ОСНОВНЫЕ КОМАНДЫ:*\n"
            "🧠 /smart_merge — умная склейка\n"
            "🔧 /smart_fix — исправить ошибки\n"
            "🐛 /smart_bugs — найти ошибки\n"
            "📊 /complexity — анализ сложности\n"
            "💾 /done — скачать код\n"
            "📝 /show — показать код\n"
            "🗑 /undo — удалить последнюю часть\n"
            "📜 /history — история\n"
            "🗑 /reset — очистить всё\n\n"
            "💡 *Просто отправляй код частями!*",
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
        return
    
    elif text == "/help" or text == "❓ Помощь":
        send_message(chat_id, 
            "📚 *ВСЕ КОМАНДЫ БОТА:*\n\n"
            "*🤖 AI ФУНКЦИИ:*\n"
            "✨ /generate <описание> — генерация кода\n"
            "🧪 /tests — генерация тестов\n"
            "🏃 /run_tests — запуск тестов\n"
            "🔄 /convert <из> <в> — преобразование кода\n"
            "📋 /review — Code Review\n"
            "📝 /comment — добавить комментарии\n"
            "⚡ /replit — экспорт в Replit\n"
            "🌐 /webapp — Telegram WebApp\n\n"
            "*🧠 УМНЫЕ ФУНКЦИИ:*\n"
            "🧠 /smart_merge — умная склейка\n"
            "🔧 /smart_fix — исправление ошибок\n"
            "🐛 /smart_bugs — поиск ошибок\n\n"
            "*📊 АНАЛИЗ:*\n"
            "📊 /complexity — сложность кода\n\n"
            "*📁 ФАЙЛЫ:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🗑 /undo — удалить последнюю часть\n"
            "📜 /history — история\n"
            "🗑 /reset — очистить всё",
            parse_mode="Markdown")
        return
    
    elif text == "/smart_merge" or text == "🧠 УМНАЯ СКЛЕЙКА":
        parts = user_sessions[uid].get("parts", [])
        if not parts:
            send_message(chat_id, "📭 Нет частей для склейки")
            return
        send_message(chat_id, "🧠 AI умно склеивает код...\n⏳ 5-10 секунд")
        merged = smart_merge(parts)
        if merged:
            user_sessions[uid]["code"] = merged
            user_sessions[uid]["history"].append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": "Умная склейка"})
            send_message(chat_id, f"✅ *Код склеен!*\n📊 Размер: {len(merged)} символов\n\n📝 /show — посмотреть", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибка склейки")
        return
    
    elif text == "/smart_fix" or text == "🔧 ИСПРАВИТЬ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        send_message(chat_id, "🔧 AI исправляет код...\n⏳ 5-10 секунд")
        fixed = fix_code(code)
        if fixed:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, f"✅ *Код исправлен!*\n\n```python\n{fixed[:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибка исправления")
        return
    
    elif text == "/smart_bugs" or text == "🐛 НАЙТИ ОШИБКИ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для проверки")
            return
        send_message(chat_id, "🐛 AI ищет ошибки...\n⏳ 3-5 секунд")
        bugs = find_bugs_ai(code)
        if bugs:
            report = "🔍 *Найденные ошибки:*\n\n"
            for b in bugs[:10]:
                icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(b.get("severity"), "⚪")
                report += f"{icon} **{b.get('severity', 'UNKNOWN')}**"
                if b.get("line"):
                    report += f" (строка {b['line']})"
                report += f"\n   {b.get('message', '')}\n\n"
            send_message(chat_id, report, parse_mode="Markdown")
        else:
            send_message(chat_id, "✅ *Ошибок не найдено!*", parse_mode="Markdown")
        return
    
    elif text == "/complexity" or text == "📊 Анализ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для анализа")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, analysis, parse_mode="Markdown")
        return
    
    elif text == "/show" or text == "📝 Показать код":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            if len(code) > 4000:
                for i in range(0, len(code), 4000):
                    send_message(chat_id, f"```python\n{code[i:i+4000]}\n```", parse_mode="Markdown")
            else:
                send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
        return
    
    elif text == "/done" or text == "💾 Скачать код":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = save_code_file(uid, code)
        send_document(chat_id, filename, "✅ Готовый код")
        os.remove(filename)
        return
    
    elif text == "/undo" or text == "🗑 Удалить последний":
        parts = user_sessions[uid].get("parts", [])
        if not parts:
            send_message(chat_id, "📭 Нет частей для удаления")
        else:
            parts.pop()
            user_sessions[uid]["parts"] = parts
            send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
        return
    
    elif text == "/history" or text == "📜 История":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 История пуста")
        else:
            msg = "📜 *История действий:*\n\n"
            for i, h in enumerate(history[-15:], 1):
                msg += f"{i}. [{h.get('time', '')[:16]}] {h.get('action', 'Действие')}\n"
            send_message(chat_id, msg, parse_mode="Markdown")
        return
    
    elif text == "/reset" or text == "🗑 Очистить всё":
        user_sessions[uid] = {"code": "", "history": [], "parts": []}
        send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
        return
    
    # Сохранение частей кода
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🧠", "🔧", "🐛", "📊", "✨", "🧪", "🔄", "📋", "⚡", "🌐", "🗑", "📜", "❓"]):
        parts = user_sessions[uid].get("parts", [])
        parts.append(text)
        user_sessions[uid]["parts"] = parts
        send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n🧠 /smart_merge — умно склеить", parse_mode="Markdown")
        return

# ==================== HTTP СЕРВЕР ====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/webapp/'):
            uid = self.path.split('/')[2]
            html = user_html_pages.get(f"webapp_{uid}", "<h1>Страница не найдена</h1>")
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
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
        elif self.path == '/api/analyze':
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

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 AI Telegram бот запущен!")
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

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
