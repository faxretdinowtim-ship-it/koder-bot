import os
import re
import json
import logging
import tempfile
import subprocess
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"https://telegram-ai-bot-4g1k.onrender.com/webhook"

# ==================== AI ФУНКЦИИ ====================
def call_deepseek(prompt):
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code != 200:
            logger.error(f"DeepSeek API ошибка: {response.status_code}")
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

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С КОДОМ ====================
def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
        logger.info(f"Сообщение отправлено в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
        logger.info(f"Файл отправлен в {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")
        return False

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

def auto_fix_code(code):
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код, без объяснений.

Код:
{code}

Исправленный код:"""
    return call_deepseek(prompt)

def smart_merge(parts):
    if not parts:
        return ""
    prompt = f"""Объедини эти части кода в один работающий файл. Расположи импорты в начале, функции в правильном порядке. Верни ТОЛЬКО итоговый код.

Части кода:
{chr(10).join([f"--- ЧАСТЬ {i+1} ---\n{p}" for i, p in enumerate(parts)])}

Итоговый код:"""
    return call_deepseek(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Верни JSON: {{"bugs": [{{"message": "описание", "severity": "CRITICAL/HIGH/MEDIUM/LOW", "line": номер, "fix": "как исправить"}}]}}

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

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    classes = code.count('class ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "🟢 Низкая (хорошо)"
    elif complexity < 20:
        rating = "🟡 Средняя (нормально)"
    else:
        rating = "🔴 Высокая (нужен рефакторинг)"
    return f"📊 *Анализ сложности кода*\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Классов: {classes}\n• Цикломатическая сложность: {complexity:.1f}\n• Оценка: {rating}"

def generate_code_by_description(description, language="python"):
    prompt = f"""Напиши код на {language} по описанию. Верни ТОЛЬКО код, без объяснений.

Описание: {description}

Код на {language}:"""
    return call_deepseek(prompt)

def convert_code(code, from_lang, to_lang):
    prompt = f"""Переведи этот код с {from_lang} на {to_lang}. Верни ТОЛЬКО преобразованный код.

Исходный код ({from_lang}):
{code}

Код на {to_lang}:"""
    return call_deepseek(prompt)

def generate_tests(code):
    prompt = f"""Напиши pytest тесты для этого кода. Верни ТОЛЬКО код тестов.

Код:
{code}

Тесты:"""
    return call_deepseek(prompt)

def code_review(code):
    prompt = f"""Проведи code review этого кода. Найди проблемы, дай рекомендации по улучшению.

Код:
{code}

Ответ в формате:
✅ Что хорошо:
- ...

⚠️ Что можно улучшить:
- ...

💡 Рекомендации:
- ..."""
    return call_deepseek(prompt)

def add_comments(code):
    prompt = f"""Добавь подробные комментарии к этому коду. Верни ТОЛЬКО код с комментариями.

Код:
{code}

Код с комментариями:"""
    return call_deepseek(prompt)

def create_pdf_export(code, filename="code.py", user_name="Пользователь"):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Экспорт кода</title>
<style>
body {{ font-family: monospace; padding: 40px; }}
pre {{ background: #f5f5f5; padding: 20px; overflow-x: auto; }}
.signature {{ margin-top: 40px; padding: 20px; background: #f0f0f0; text-align: center; }}
</style>
</head>
<body>
<h1>📄 Экспорт кода</h1>
<p>Файл: {filename}</p>
<p>Дата: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}</p>
<p>Пользователь: {user_name}</p>
<pre><code>{escaped_code}</code></pre>
<div class="signature">
<p>🤖 Создано с помощью AI Code Bot</p>
<p>Подписано: AI Code Bot</p>
</div>
</body>
</html>'''

def save_code_file(user_id, content):
    filename = f"code_{user_id}_bot.py"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 🤖 Создано AI Code Bot\n# Дата: {datetime.now()}\n\n{content}")
    return filename

# ==================== КЛАВИАТУРА ====================
def get_main_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ"],
            ["📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ"],
            ["✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА"],
            ["🔄 ПРЕОБРАЗОВАТЬ", "🧪 ТЕСТЫ"],
            ["📋 CODE REVIEW", "📝 ДОБАВИТЬ КОММЕНТАРИИ"],
            ["📄 ЭКСПОРТ PDF", "🌐 ДРУГИЕ ЯЗЫКИ"],
            ["🗑 Удалить последний", "📜 ИСТОРИЯ"],
            ["🗑 ОЧИСТИТЬ ВСЁ", "❓ ПОМОЩЬ"]
        ],
        "resize_keyboard": True
    }

def get_languages_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🐍 Python", "callback_data": "lang_python"}],
            [{"text": "📜 JavaScript", "callback_data": "lang_javascript"}],
            [{"text": "☕ Java", "callback_data": "lang_java"}],
            [{"text": "⚡ C++", "callback_data": "lang_cpp"}],
            [{"text": "🚀 Go", "callback_data": "lang_go"}],
            [{"text": "🦀 Rust", "callback_data": "lang_rust"}]
        ]
    }

# ==================== УСТАНОВКА WEBHOOK ====================
def set_webhook():
    try:
        url = f"{API_URL}/setWebhook?url={WEBHOOK_URL}"
        response = requests.get(url, timeout=10)
        result = response.json()
        if result.get("ok"):
            logger.info(f"✅ Webhook успешно установлен: {WEBHOOK_URL}")
        else:
            logger.error(f"❌ Ошибка установки webhook: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка при установке webhook: {e}")
        return None

# ==================== ВЕБХУК ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"📩 Получено сообщение: {data}")
        
        if data and "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")
            
            if user_id not in user_sessions:
                user_sessions[user_id] = {
                    "code": "", 
                    "history": [], 
                    "parts": [], 
                    "language": "python",
                    "current_file": "main.py",
                    "files": {"main.py": ""}
                }
            
            # ========== ОСНОВНЫЕ КОМАНДЫ ==========
            if text == "/start":
                send_message(chat_id, 
                    "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
                    "Привет! Я использую ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ для работы с кодом!\n\n"
                    "*Основные команды:*\n"
                    "📝 /show — показать код\n"
                    "💾 /done — скачать код\n"
                    "🔧 /fix — исправить ошибки\n"
                    "🐛 /bugs — найти ошибки\n"
                    "📊 /complexity — анализ сложности\n"
                    "🏃 /run — выполнить код\n\n"
                    "*🤖 AI ФУНКЦИИ:*\n"
                    "✨ /generate — создать код по описанию\n"
                    "🧠 /smart_merge — умная склейка частей\n"
                    "🔄 /convert — преобразовать в другой язык\n"
                    "🧪 /tests — сгенерировать тесты\n"
                    "📋 /review — Code Review\n"
                    "📝 /comment — добавить комментарии\n"
                    "📄 /pdf — экспорт в PDF\n\n"
                    "🌐 /languages — другие языки программирования\n"
                    "🗑 /reset — очистить всё\n"
                    "❓ /help — помощь",
                    reply_markup=json.dumps(get_main_keyboard()))
            
            elif text == "/help" or text == "❓ ПОМОЩЬ":
                send_message(chat_id, 
                    "📚 *ВСЕ КОМАНДЫ БОТА:*\n\n"
                    "*📝 ОСНОВНЫЕ:*\n"
                    "/show — показать текущий код\n"
                    "/done — скачать код файлом\n"
                    "/fix — автоматически исправить ошибки\n"
                    "/bugs — найти все ошибки\n"
                    "/complexity — анализ сложности\n"
                    "/run — выполнить код в песочнице\n\n"
                    "*🤖 AI ФУНКЦИИ:*\n"
                    "/generate — создать код по описанию\n"
                    "/smart_merge — умно склеить части кода\n"
                    "/convert — преобразовать в другой язык\n"
                    "/tests — сгенерировать pytest тесты\n"
                    "/review — Code Review\n"
                    "/comment — добавить комментарии\n"
                    "/pdf — экспорт в PDF\n\n"
                    "*📁 ФАЙЛЫ:*\n"
                    "/files — список файлов\n"
                    "/add_file — добавить файл\n"
                    "/switch_file — переключить файл\n"
                    "/export — экспортировать все файлы\n\n"
                    "*🌐 ДРУГОЕ:*\n"
                    "/languages — другие языки\n"
                    "/undo — удалить последнюю часть\n"
                    "/history — история изменений\n"
                    "/reset — очистить всё",
                    reply_markup=json.dumps(get_main_keyboard()))
            
            elif text == "/show" or text == "📝 ПОКАЗАТЬ КОД":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Код пуст. Отправь код или используй /generate")
                else:
                    if len(code) > 4000:
                        for i in range(0, len(code), 4000):
                            send_message(chat_id, f"```python\n{code[i:i+4000]}\n```")
                    else:
                        send_message(chat_id, f"```python\n{code}\n```")
            
            elif text == "/done" or text == "💾 СКАЧАТЬ КОД":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "❌ Нет кода для скачивания")
                else:
                    filename = save_code_file(user_id, code)
                    send_document(chat_id, filename, "✅ Готовый код (с подписью _bot)")
                    os.remove(filename)
            
            elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для исправления")
                else:
                    send_message(chat_id, "🔧 AI исправляет код... (5-10 секунд)")
                    fixed = auto_fix_code(code)
                    if fixed and fixed != code:
                        user_sessions[user_id]["code"] = fixed
                        if len(fixed) > 3000:
                            send_message(chat_id, f"✅ *Код исправлен!*\n📊 Размер: {len(fixed)} символов\n\n/show — посмотреть результат")
                        else:
                            send_message(chat_id, f"✅ *Исправленный код:*\n\n```python\n{fixed}\n```")
                    else:
                        send_message(chat_id, "✅ Код уже в хорошем состоянии!")
            
            elif text == "/bugs" or text == "🐛 ОШИБКИ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для проверки")
                else:
                    send_message(chat_id, "🐛 AI ищет ошибки... (3-5 секунд)")
                    bugs = find_bugs_ai(code)
                    if bugs:
                        report = "🔍 *Найденные ошибки:*\n\n"
                        for b in bugs[:10]:
                            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(b.get("severity"), "⚪")
                            report += f"{icon} **{b.get('severity', 'UNKNOWN')}**"
                            if b.get("line"):
                                report += f" (строка {b['line']})"
                            report += f"\n   📝 {b.get('message', '')}\n"
                            if b.get("fix"):
                                report += f"   💡 *Исправление:* {b.get('fix', '')}\n"
                            report += "\n"
                        send_message(chat_id, report)
                    else:
                        send_message(chat_id, "✅ *Ошибок не найдено!* Код выглядит хорошо.")
            
            elif text == "/complexity" or text == "📊 АНАЛИЗ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для анализа")
                else:
                    analysis = analyze_complexity(code)
                    send_message(chat_id, analysis)
            
            elif text == "/run" or text == "🏃 ЗАПУСТИТЬ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для запуска")
                else:
                    send_message(chat_id, "🏃 Запускаю код в песочнице...")
                    result = run_code_safe(code)
                    if result["success"]:
                        output = result["output"][:3000] if result["output"] else "(нет вывода)"
                        send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```")
                    else:
                        error = result["error"][:2000] if result["error"] else "Неизвестная ошибка"
                        send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```")
            
            # ========== AI ФУНКЦИИ ==========
            elif text == "/generate" or text == "✨ ГЕНЕРАЦИЯ":
                send_message(chat_id, "📝 *Опиши, какой код нужно сгенерировать:*\n\nПримеры:\n- 'калькулятор на Python'\n- 'функция для сортировки списка'\n- 'бота для Telegram на aiogram'\n- 'веб-сервер на Flask'")
                user_sessions[user_id]["waiting_for"] = "generate"
            
            elif text == "/smart_merge" or text == "🧠 УМНАЯ СКЛЕЙКА":
                parts = user_sessions[user_id].get("parts", [])
                if not parts:
                    send_message(chat_id, "📭 Нет частей для склейки. Отправляй код частями, потом нажми эту кнопку!")
                else:
                    send_message(chat_id, "🧠 AI умно склеивает части кода... (5-10 секунд)")
                    merged = smart_merge(parts)
                    if merged:
                        user_sessions[user_id]["code"] = merged
                        user_sessions[user_id]["parts"] = []
                        if len(merged) > 3000:
                            send_message(chat_id, f"✅ *Код успешно склеен!*\n📊 Размер: {len(merged)} символов\n📦 Склеено частей: {len(parts)}\n\n/show — посмотреть результат")
                        else:
                            send_message(chat_id, f"✅ *Склеенный код:*\n\n```python\n{merged}\n```")
                    else:
                        send_message(chat_id, "❌ Ошибка склейки. Попробуй ещё раз.")
            
            elif text == "/convert" or text == "🔄 ПРЕОБРАЗОВАТЬ":
                send_message(chat_id, "🔄 *Преобразование кода*\n\nВыбери целевой язык:", reply_markup=json.dumps(get_languages_keyboard()))
                user_sessions[user_id]["waiting_for"] = "convert"
            
            elif text == "/tests" or text == "🧪 ТЕСТЫ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для генерации тестов")
                else:
                    send_message(chat_id, "🧪 AI генерирует тесты... (5-10 секунд)")
                    tests = generate_tests(code)
                    if tests:
                        user_sessions[user_id]["tests"] = tests
                        send_message(chat_id, f"✅ *Сгенерированные тесты:*\n\n```python\n{tests}\n```\n\n🏃 /run_tests — запустить тесты")
                    else:
                        send_message(chat_id, "❌ Не удалось сгенерировать тесты")
            
            elif text == "/run_tests":
                code = user_sessions[user_id].get("code", "")
                tests = user_sessions[user_id].get("tests", "")
                if not code.strip() or not tests.strip():
                    send_message(chat_id, "📭 Сначала сгенерируй тесты командой /tests")
                else:
                    send_message(chat_id, "🏃 Запуск тестов...")
                    full_code = code + "\n\n" + tests
                    result = run_code_safe(full_code)
                    if result["success"]:
                        send_message(chat_id, f"✅ *Все тесты пройдены!*\n\n```\n{result['output'][:2000]}\n```")
                    else:
                        send_message(chat_id, f"❌ *Тесты не пройдены:*\n\n```\n{result['error'][:2000]}\n```")
            
            elif text == "/review" or text == "📋 CODE REVIEW":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для ревью")
                else:
                    send_message(chat_id, "📋 AI проводит Code Review... (5-10 секунд)")
                    review = code_review(code)
                    send_message(chat_id, f"📋 *Code Review:*\n\n{review}")
            
            elif text == "/comment" or text == "📝 ДОБАВИТЬ КОММЕНТАРИИ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для добавления комментариев")
                else:
                    send_message(chat_id, "📝 AI добавляет комментарии... (5-10 секунд)")
                    commented = add_comments(code)
                    if commented:
                        user_sessions[user_id]["code"] = commented
                        send_message(chat_id, f"✅ *Код с комментариями:*\n\n```python\n{commented[:2500]}\n```")
                    else:
                        send_message(chat_id, "❌ Не удалось добавить комментарии")
            
            elif text == "/pdf" or text == "📄 ЭКСПОРТ PDF":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для экспорта в PDF")
                else:
                    send_message(chat_id, "📄 Создаю PDF файл...")
                    html_content = create_pdf_export(code, "code.py", f"User_{user_id}")
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                        f.write(html_content)
                        html_file = f.name
                    send_document(chat_id, html_file, "📄 Экспорт кода (HTML для печати в PDF)")
                    os.remove(html_file)
            
            elif text == "/languages" or text == "🌐 ДРУГИЕ ЯЗЫКИ":
                send_message(chat_id, 
                    "🌐 *Поддерживаемые языки программирования:*\n\n"
                    "• 🐍 Python\n"
                    "• 📜 JavaScript\n"
                    "• ☕ Java\n"
                    "• ⚡ C++\n"
                    "• 🚀 Go\n"
                    "• 🦀 Rust\n\n"
                    "*Команды:*\n"
                    "/set_language python — выбрать язык для генерации\n"
                    "/convert_js — преобразовать код в JavaScript\n"
                    "/convert_java — преобразовать в Java\n"
                    "/convert_cpp — преобразовать в C++\n"
                    "/convert_go — преобразовать в Go\n"
                    "/convert_rust — преобразовать в Rust",
                    reply_markup=json.dumps(get_languages_keyboard()))
            
            elif text.startswith("/convert_"):
                target = text.replace("/convert_", "")
                lang_map = {"js": "JavaScript", "java": "Java", "cpp": "C++", "go": "Go", "rust": "Rust"}
                target_lang = lang_map.get(target, target)
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для преобразования")
                else:
                    send_message(chat_id, f"🔄 Преобразую код из Python в {target_lang}... (10-15 секунд)")
                    converted = convert_code(code, "Python", target_lang)
                    if converted:
                        user_sessions[user_id]["code"] = converted
                        user_sessions[user_id]["language"] = target_lang.lower()
                        send_message(chat_id, f"✅ *Код на {target_lang}:*\n\n```{target_lang.lower()}\n{converted[:2500]}\n```")
                    else:
                        send_message(chat_id, "❌ Не удалось преобразовать код")
            
            elif text.startswith("/set_language"):
                lang = text.split()[1] if len(text.split()) > 1 else "python"
                user_sessions[user_id]["language"] = lang
                send_message(chat_id, f"✅ Язык установлен: {lang}")
            
            # ========== УПРАВЛЕНИЕ ФАЙЛАМИ ==========
            elif text == "/files" or text == "📁 ФАЙЛЫ":
                files = user_sessions[user_id].get("files", {})
                if not files:
                    send_message(chat_id, "📭 Нет файлов. Используй /add_file для добавления")
                else:
                    file_list = "\n".join([f"• `{name}`" for name in files.keys()])
                    send_message(chat_id, f"📁 *Файлы проекта:*\n{file_list}\n\n📄 Текущий файл: `{user_sessions[user_id].get('current_file', 'main.py')}`\n\n/switches\n\nswitch_file <имя> — переключиться")
            
            elif text.startswith("/switch_file"):
                parts = text.split()
                if len(parts) < 2:
                    send_message(chat_id, "📝 Использование: /switch_file main.py")
                else:
                    filename = parts[1]
                    files = user_sessions[user_id].get("files", {})
                    if filename in files:
                        user_sessions[user_id]["current_file"] = filename
                        user_sessions[user_id]["code"] = files[filename]
                        send_message(chat_id, f"✅ Переключён на файл: `{filename}`")
                    else:
                        send_message(chat_id, f"❌ Файл `{filename}` не найден")
            
            elif text == "/add_file":
                send_message(chat_id, "📝 Введите имя файла для добавления (например: `app.py`, `index.html`):")
                user_sessions[user_id]["waiting_for"] = "add_file"
            
            elif text == "/export":
                files = user_sessions[user_id].get("files", {})
                if not files:
                    send_message(chat_id, "📭 Нет файлов для экспорта")
                else:
                    send_message(chat_id, "📦 Создаю ZIP архив...")
                    import zipfile
                    from io import BytesIO
                    zip_buffer = BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for name, content in files.items():
                            zf.writestr(name, content)
                    zip_buffer.seek(0)
                    with open(f"project_{user_id}.zip", "wb") as f:
                        f.write(zip_buffer.getvalue())
                    send_document(chat_id, f"project_{user_id}.zip", "📦 Архив всех файлов")
                    os.remove(f"project_{user_id}.zip")
            
            # ========== ИСТОРИЯ И УПРАВЛЕНИЕ ==========
            elif text == "/undo" or text == "🗑 УДАЛИТЬ ПОСЛЕДНИЙ":
                parts = user_sessions[user_id].get("parts", [])
                if not parts:
                    send_message(chat_id, "📭 Нет частей для удаления")
                else:
                    last = parts.pop()
                    user_sessions[user_id]["parts"] = parts
                    if parts:
                        full_code = "\n\n".join(parts)
                        user_sessions[user_id]["code"] = full_code
                        send_message(chat_id, f"🗑 Удалена последняя часть. Осталось частей: {len(parts)}")
                    else:
                        user_sessions[user_id]["code"] = ""
                        send_message(chat_id, "🗑 Удалена последняя часть. Код полностью очищен.")
            
            elif text == "/history" or text == "📜 ИСТОРИЯ":
                history = user_sessions[user_id].get("history", [])
                if not history:
                    send_message(chat_id, "📭 История пуста")
                else:
                    msg = "📜 *История действий:*\n\n"
                    for i, h in enumerate(history[-15:], 1):
                        time_str = h.get('time', '')[:16]
                        action = h.get('action', 'Действие')
                        msg += f"{i}. [{time_str}] {action}\n"
                    send_message(chat_id, msg)
            
            elif text == "/reset" or text == "🗑 ОЧИСТИТЬ ВСЁ":
                user_sessions[user_id] = {
                    "code": "", 
                    "history": [], 
                    "parts": [], 
                    "language": "python",
                    "current_file": "main.py",
                    "files": {"main.py": ""}
                }
                send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_main_keyboard()))
            
            # ========== ОБРАБОТКА ОЖИДАНИЯ ==========
            elif user_sessions[user_id].get("waiting_for") == "generate":
                user_sessions[user_id]["waiting_for"] = None
                lang = user_sessions[user_id].get("language", "python")
                send_message(chat_id, f"✨ AI генерирует код на {lang}... (10-15 секунд)")
                generated = generate_code_by_description(text, lang)
                if generated:
                    user_sessions[user_id]["code"] = generated
                    if len(generated) > 3000:
                        send_message(chat_id, f"✅ *Код сгенерирован!*\n📊 Размер: {len(generated)} символов\n\n/show — посмотреть результат\n/run — выполнить")
                    else:
                        send_message(chat_id, f"✅ *Сгенерированный код:*\n\n```{lang}\n{generated}\n```")
                else:
                    send_message(chat_id, "❌ Не удалось сгенерировать код. Попробуй ещё раз.")
            
            elif user_sessions[user_id].get("waiting_for") == "add_file":
                user_sessions[user_id]["waiting_for"] = None
                filename = text.strip()
                if "files" not in user_sessions[user_id]:
                    user_sessions[user_id]["files"] = {}
                ext = filename.split('.')[-1] if '.' in filename else 'txt'
                templates = {
                    'py': '# Python code\ndef main():\n    pass\n',
                    'html': '<!DOCTYPE html>\n<html>\n<body>\n<h1>Hello</h1>\n</body>\n</html>',
                    'css': '/* Styles */\nbody { font-family: Arial; }\n',
                    'js': '// JavaScript\nconsole.log("Hello");\n'
                }
                user_sessions[user_id]["files"][filename] = templates.get(ext, f"# {filename}\n")
                send_message(chat_id, f"✅ Файл `{filename}` добавлен!")
            
            # ========== ОБЫЧНЫЙ КОД (ЧАСТИ ДЛЯ СКЛЕЙКИ) ==========
            else:
                parts = user_sessions[user_id].get("parts", [])
                parts.append(text)
                user_sessions[user_id]["parts"] = parts
                user_sessions[user_id]["history"].append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "action": f"Добавлена часть {len(parts)}"
                })
                send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n📊 Размер части: {len(text)} символов\n\n🧠 /smart_merge — умно склеить все части\n🗑 /undo — удалить последнюю часть")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")
        return jsonify({"ok": False}), 500

@app.route('/')
def health():
    return "🤖 AI Code Bot is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    time.sleep(2)
    set_webhook()
    app.run(host='0.0.0.0', port=PORT)
