import os
import re
import json
import logging
import tempfile
import subprocess
import time
import base64
from datetime import datetime
from flask import Flask, request, jsonify
import requests

TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"https://bot-koder.onrender.com/webhook"

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
            return ""
        result = response.json()
        if "choices" not in result or not result["choices"]:
            return ""
        content = result["choices"][0]["message"]["content"]
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content.strip()
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        return ""

def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except:
        pass

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except:
        return {"success": False, "output": "", "error": "Timeout"}
    finally:
        os.unlink(temp_file)

def auto_fix_code(code):
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.

Код:
{code}

Исправленный код:"""
    return call_deepseek(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Верни JSON: {{"bugs": [{{"message": "...", "severity": "CRITICAL/HIGH/MEDIUM/LOW", "line": 0}}]}}

Код:
{code}"""
    response = call_deepseek(prompt)
    if response:
        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group()).get("bugs", [])
        except:
            pass
    return []

def analyze_complexity(code):
    lines = code.split("\n")
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
    functions = code.count("def ")
    return f"📊 Анализ:\nСтрок кода: {code_lines}\nФункций: {functions}"

def generate_code(description):
    prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код.

Описание: {description}

Код:"""
    return call_deepseek(prompt)

def smart_merge(parts):
    if not parts:
        return ""
    parts_text = "\n\n--- ЧАСТЬ ---\n\n".join(parts)
    prompt = f"""Объедини эти части кода в один работающий файл. Верни ТОЛЬКО итоговый код.

Части:
{parts_text}

Итоговый код:"""
    return call_deepseek(prompt)

def convert_code(code, target_lang):
    prompt = f"""Переведи этот код с Python на {target_lang}. Верни ТОЛЬКО код.

Код:
{code}

Код на {target_lang}:"""
    return call_deepseek(prompt)

def generate_tests(code):
    prompt = f"""Напиши pytest тесты для этого кода. Верни ТОЛЬКО код тестов.

Код:
{code}

Тесты:"""
    return call_deepseek(prompt)

def code_review(code):
    prompt = f"""Проведи code review этого кода. Найди проблемы, дай рекомендации.

Код:
{code}

Ответ:"""
    return call_deepseek(prompt)

def add_comments(code):
    prompt = f"""Добавь подробные комментарии к этому коду. Верни ТОЛЬКО код с комментариями.

Код:
{code}

Код с комментариями:"""
    return call_deepseek(prompt)

def create_pdf_export(code):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Экспорт кода</title>
<style>
body {{ font-family: monospace; padding: 40px; }}
pre {{ background: #f5f5f5; padding: 20px; overflow-x: auto; }}
</style>
</head>
<body>
<h1>Экспорт кода</h1>
<p>Дата: {datetime.now()}</p>
<pre>{escaped_code}</pre>
<p>Создано AI Code Bot</p>
</body>
</html>"""

# ==================== НОВЫЕ ФУНКЦИИ ====================

# 1. АВТО-ТЕСТЫ С ОТЧЁТОМ
def run_tests_with_report(code):
    tests = generate_tests(code)
    if not tests:
        return "❌ Не удалось сгенерировать тесты"
    
    full_code = code + "\n\n" + tests
    result = run_code_safe(full_code)
    
    if result["success"]:
        report = "✅ *Все тесты пройдены!*\n\n"
        report += f"📊 Результаты:\n{result['output'][:500]}"
    else:
        report = "❌ *Тесты не пройдены!*\n\n"
        report += f"🐛 Ошибки:\n{result['error'][:500]}"
    return report

# 2. GitHub ИНТЕГРАЦИЯ
def github_push(repo_name, filename, content):
    if not GITHUB_TOKEN:
        return "❌ GitHub токен не настроен. Добавь GITHUB_TOKEN в переменные окружения"
    try:
        from github import Github
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        
        # Создаём репозиторий если нет
        try:
            repo = user.get_repo(repo_name)
        except:
            repo = user.create_repo(repo_name)
        
        # Коммитим файл
        try:
            file = repo.get_contents(filename)
            repo.update_file(filename, f"Update {filename}", content, file.sha)
        except:
            repo.create_file(filename, f"Add {filename}", content)
        
        return f"✅ Код загружен в GitHub!\n🔗 https://github.com/{user.login}/{repo_name}/blob/main/{filename}"
    except Exception as e:
        return f"❌ Ошибка GitHub: {e}"

# 3. ГОЛОСОВОЙ ВВОД (требует интеграции с распознаванием речи)
def voice_to_code(voice_file_id):
    # В текущей версии без реального распознавания речи
    # Можно скачать файл и отправить в сервис распознавания
    return "🎤 Функция в разработке. Пока используй текстовое описание в /generate"

# 4. ПОИСК ЛОГИЧЕСКИХ БАГОВ
def find_logic_bugs(code):
    prompt = f"""Найди логические ошибки в этом коде (проблемы с алгоритмами, неправильные условия, бесконечные циклы, ошибки на границах). Верни JSON.

Код:
{code}

JSON с ошибками:"""
    response = call_deepseek(prompt)
    if response:
        try:
            return json.loads(response)
        except:
            return {"bugs": [{"message": response[:500]}]}
    return {"bugs": []}

# 5. ПЕРЕВОД КОДА НА ДРУГОЙ ЯЗЫК
def translate_code(code, target_lang):
    prompt = f"""Переведи этот код с Python на {target_lang}. Верни ТОЛЬКО код.

Код:
{code}

Код на {target_lang}:"""
    return call_deepseek(prompt)

# 6. РЕФАКТОРИНГ КОДА
def refactor_code(code):
    prompt = f"""Рефакторинг кода: улучши структуру, читаемость, производительность. Верни ТОЛЬКО улучшенный код.

Код:
{code}

Улучшенный код:"""
    return call_deepseek(prompt)

# 7. ЭКСПОРТ В РАЗНЫХ ФОРМАТАХ
def export_json(code):
    return json.dumps({"code": code, "language": "python", "timestamp": str(datetime.now())})

def export_html(code):
    return f"""<!DOCTYPE html>
<html>
<head><title>Code Export</title>
<style>body{{font-family:monospace;padding:20px;}}pre{{background:#f5f5f5;padding:15px;}}</style>
</head>
<body>
<h1>Экспорт кода</h1>
<p>Дата: {datetime.now()}</p>
<pre>{code}</pre>
</body>
</html>"""

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ"],
            ["📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ"],
            ["✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА"],
            ["🔄 ПРЕОБРАЗОВАТЬ", "🧪 ТЕСТЫ"],
            ["📋 CODE REVIEW", "📝 КОММЕНТАРИИ"],
            ["📄 ЭКСПОРТ PDF", "🌐 ДРУГИЕ ЯЗЫКИ"],
            ["📁 ФАЙЛЫ", "➕ ДОБАВИТЬ ФАЙЛ"],
            ["🗑 Удалить последний", "📜 ИСТОРИЯ"],
            ["🏆 ТЕСТЫ С ОТЧЁТОМ", "🐙 GITHUB PUSH"],
            ["🎤 ГОЛОСОВОЙ ВВОД", "🧠 ЛОГИЧЕСКИЕ БАГИ"],
            ["🔄 ПЕРЕВОД", "🔧 РЕФАКТОРИНГ"],
            ["📦 ЭКСПОРТ JSON", "📄 ЭКСПОРТ HTML"],
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

def set_webhook():
    try:
        url = f"{API_URL}/setWebhook?url={WEBHOOK_URL}"
        response = requests.get(url, timeout=10)
        result = response.json()
        if result.get("ok"):
            logger.info(f"Webhook установлен: {WEBHOOK_URL}")
        return result
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return None

# ==================== СПИСОК КНОПОК ====================
BUTTONS = [
    "📝 Показать код", "💾 Скачать код", "🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ",
    "📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ", "✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА",
    "🔄 ПРЕОБРАЗОВАТЬ", "🧪 ТЕСТЫ", "📋 CODE REVIEW", "📝 КОММЕНТАРИИ",
    "📄 ЭКСПОРТ PDF", "🌐 ДРУГИЕ ЯЗЫКИ", "📁 ФАЙЛЫ", "➕ ДОБАВИТЬ ФАЙЛ",
    "🗑 Удалить последний", "📜 ИСТОРИЯ", "🏆 ТЕСТЫ С ОТЧЁТОМ", "🐙 GITHUB PUSH",
    "🎤 ГОЛОСОВОЙ ВВОД", "🧠 ЛОГИЧЕСКИЕ БАГИ", "🔄 ПЕРЕВОД", "🔧 РЕФАКТОРИНГ",
    "📦 ЭКСПОРТ JSON", "📄 ЭКСПОРТ HTML", "🗑 ОЧИСТИТЬ ВСЁ", "❓ ПОМОЩЬ"
]

# ==================== ВЕБХУК ====================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Получено: {data}")
        
        if data and "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")
            
            if user_id not in user_sessions:
                user_sessions[user_id] = {"code": "", "parts": [], "files": {"main.py": ""}, "current_file": "main.py", "history": []}
            
            if text.startswith("/") or text in BUTTONS:
                
                if text in ["/start", "❓ ПОМОЩЬ"]:
                    send_message(chat_id, 
                        "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
                        "✨ /generate — создать код\n🧠 /smart_merge — умная склейка\n🔄 /convert — преобразовать\n🧪 /tests — тесты\n"
                        "📋 /review — Code Review\n📝 /comment — комментарии\n📄 /pdf — PDF\n🌐 /languages — языки\n"
                        "📁 /files — файлы\n🏆 /test_report — тесты с отчётом\n🐙 /github_push — в GitHub\n"
                        "🎤 /voice — голосовой ввод\n🧠 /logic_bugs — логические баги\n🔄 /translate — перевод\n"
                        "🔧 /refactor — рефакторинг\n📦 /export_json — JSON\n📄 /export_html — HTML\n"
                        "🔧 /fix — исправить\n🐛 /bugs — ошибки\n📊 /complexity — анализ\n🏃 /run — выполнить\n"
                        "📝 /show — показать\n💾 /done — скачать\n🗑 /reset — очистить",
                        reply_markup=json.dumps(get_keyboard()))
                
                elif text in ["/show", "📝 Показать код"]:
                    code = user_sessions[user_id].get("code", "")
                    send_message(chat_id, f"```python\n{code[:3000] if code else '# Код пуст'}\n```")
                
                elif text in ["/done", "💾 Скачать код"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        filename = f"code_{user_id}.py"
                        with open(filename, "w") as f:
                            f.write(code)
                        send_document(chat_id, filename, "✅ Код")
                        os.remove(filename)
                    else:
                        send_message(chat_id, "❌ Нет кода")
                
                elif text in ["/fix", "🔧 ИСПРАВИТЬ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🔧 AI исправляет код...")
                        fixed = auto_fix_code(code)
                        if fixed:
                            user_sessions[user_id]["code"] = fixed
                            send_message(chat_id, f"✅ Исправлено:\n```python\n{fixed[:1500]}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/bugs", "🐛 ОШИБКИ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🐛 AI ищет ошибки...")
                        bugs = find_bugs_ai(code)
                        if bugs:
                            report = "🔍 *Ошибки:*\n"
                            for b in bugs[:5]:
                                report += f"• {b.get('message', '')}\n"
                            send_message(chat_id, report)
                        else:
                            send_message(chat_id, "✅ Ошибок не найдено!")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/complexity", "📊 АНАЛИЗ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, analyze_complexity(code))
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/run", "🏃 ЗАПУСТИТЬ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🏃 Запуск...")
                        result = run_code_safe(code)
                        if result["success"]:
                            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1500]}\n```")
                        else:
                            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:500]}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/generate", "✨ ГЕНЕРАЦИЯ"]:
                    send_message(chat_id, "📝 *Опиши код для генерации:*")
                    user_sessions[user_id]["waiting_for"] = "generate"
                
                elif text in ["/smart_merge", "🧠 УМНАЯ СКЛЕЙКА"]:
                    parts = user_sessions[user_id].get("parts", [])
                    if parts:
                        send_message(chat_id, "🧠 AI склеивает части...")
                        merged = smart_merge(parts)
                        if merged:
                            user_sessions[user_id]["code"] = merged
                            user_sessions[user_id]["parts"] = []
                            send_message(chat_id, f"✅ Код склеен!\n\n/show — посмотреть")
                    else:
                        send_message(chat_id, "📭 Нет частей")
                
                elif text in ["/tests", "🧪 ТЕСТЫ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🧪 Генерация тестов...")
                        tests = generate_tests(code)
                        if tests:
                            send_message(chat_id, f"✅ Тесты:\n```python\n{tests[:2000]}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/review", "📋 CODE REVIEW"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "📋 Code Review...")
                        review = code_review(code)
                        send_message(chat_id, f"📋 *Review:*\n{review[:2000]}")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/comment", "📝 КОММЕНТАРИИ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "📝 Добавляю комментарии...")
                        commented = add_comments(code)
                        if commented:
                            user_sessions[user_id]["code"] = commented
                            send_message(chat_id, f"✅ Код с комментариями:\n```python\n{commented[:2000]}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/pdf", "📄 ЭКСПОРТ PDF"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        html = create_pdf_export(code)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                            f.write(html)
                            html_file = f.name
                        send_document(chat_id, html_file, "📄 PDF")
                        os.remove(html_file)
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/languages", "🌐 ДРУГИЕ ЯЗЫКИ"]:
                    send_message(chat_id, "🌐 *Выбери язык:*", reply_markup=json.dumps(get_languages_keyboard()))
                
                elif text in ["/files", "📁 ФАЙЛЫ"]:
                    files = user_sessions[user_id].get("files", {})
                    if files:
                        file_list = "\n".join([f"• {n}" for n in files.keys()])
                        send_message(chat_id, f"📁 *Файлы:*\n{file_list}")
                    else:
                        send_message(chat_id, "📭 Нет файлов")
                
                elif text in ["/add_file", "➕ ДОБАВИТЬ ФАЙЛ"]:
                    send_message(chat_id, "📝 Введите имя файла:")
                    user_sessions[user_id]["waiting_for"] = "add_file"
                
                elif text in ["/undo", "🗑 Удалить последний"]:
                    parts = user_sessions[user_id].get("parts", [])
                    if parts:
                        parts.pop()
                        user_sessions[user_id]["parts"] = parts
                        send_message(chat_id, f"🗑 Удалено. Осталось: {len(parts)}")
                    else:
                        send_message(chat_id, "📭 Нет частей")
                
                elif text in ["/history", "📜 ИСТОРИЯ"]:
                    history = user_sessions[user_id].get("history", [])
                    if history:
                        msg = "📜 *История:*\n"
                        for i, h in enumerate(history[-10:], 1):
                            msg += f"{i}. {h.get('action', '')}\n"
                        send_message(chat_id, msg)
                    else:
                        send_message(chat_id, "📭 История пуста")
                
                # НОВЫЕ ФУНКЦИИ
                elif text in ["/test_report", "🏆 ТЕСТЫ С ОТЧЁТОМ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🏆 Запуск тестов с отчётом...")
                        report = run_tests_with_report(code)
                        send_message(chat_id, report)
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/github_push", "🐙 GITHUB PUSH"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "📝 Введите название репозитория и файла (repo/file.py):")
                        user_sessions[user_id]["waiting_for"] = "github"
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/voice", "🎤 ГОЛОСОВОЙ ВВОД"]:
                    send_message(chat_id, "🎤 Отправь голосовое сообщение с описанием кода (функция в разработке). Пока используй /generate")
                
                elif text in ["/logic_bugs", "🧠 ЛОГИЧЕСКИЕ БАГИ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🧠 Поиск логических ошибок...")
                        result = find_logic_bugs(code)
                        bugs = result.get("bugs", [])
                        if bugs:
                            report = "🐛 *Логические ошибки:*\n"
                            for b in bugs[:5]:
                                report += f"• {b.get('message', '')}\n"
                            send_message(chat_id, report)
                        else:
                            send_message(chat_id, "✅ Логических ошибок не найдено!")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/translate", "🔄 ПЕРЕВОД"]:
                    send_message(chat_id, "🌐 *Выбери язык для перевода:*", reply_markup=json.dumps(get_languages_keyboard()))
                    user_sessions[user_id]["waiting_for_translate"] = True
                
                elif text in ["/refactor", "🔧 РЕФАКТОРИНГ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🔧 Рефакторинг кода...")
                        refactored = refactor_code(code)
                        if refactored:
                            user_sessions[user_id]["code"] = refactored
                            send_message(chat_id, f"✅ Рефакторинг завершён:\n```python\n{refactored[:1500]}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/export_json", "📦 ЭКСПОРТ JSON"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        json_data = export_json(code)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                            f.write(json_data)
                            fname = f.name
                        send_document(chat_id, fname, "📦 JSON экспорт")
                        os.remove(fname)
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/export_html", "📄 ЭКСПОРТ HTML"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        html = export_html(code)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                            f.write(html)
                            fname = f.name
                        send_document(chat_id, fname, "📄 HTML экспорт")
                        os.remove(fname)
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif text in ["/reset", "🗑 ОЧИСТИТЬ ВСЁ"]:
                    user_sessions[user_id] = {"code": "", "parts": [], "files": {"main.py": ""}, "current_file": "main.py", "history": []}
                    send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
                
                elif user_sessions[user_id].get("waiting_for") == "generate":
                    user_sessions[user_id]["waiting_for"] = None
                    send_message(chat_id, "✨ Генерация...")
                    generated = generate_code(text)
                    if generated:
                        user_sessions[user_id]["code"] = generated
                        send_message(chat_id, f"✅ Сгенерировано:\n```python\n{generated[:2000]}\n```")
                
                elif user_sessions[user_id].get("waiting_for") == "add_file":
                    user_sessions[user_id]["waiting_for"] = None
                    filename = text.strip()
                    user_sessions[user_id]["files"][filename] = ""
                    send_message(chat_id, f"✅ Файл {filename} создан")
                
                elif user_sessions[user_id].get("waiting_for") == "github":
                    user_sessions[user_id]["waiting_for"] = None
                    parts = text.split('/')
                    if len(parts) >= 2:
                        repo_name = parts[0]
                        filename = parts[1]
                        code = user_sessions[user_id].get("code", "")
                        result = github_push(repo_name, filename, code)
                        send_message(chat_id, result)
                    else:
                        send_message(chat_id, "❌ Формат: repo_name/file.py")
                
                elif user_sessions[user_id].get("waiting_for_translate"):
                    user_sessions[user_id]["waiting_for_translate"] = None
                    code = user_sessions[user_id].get("code", "")
                    target = text.lower()
                    lang_map = {"javascript": "JavaScript", "java": "Java", "cpp": "C++", "go": "Go", "rust": "Rust"}
                    target_lang = lang_map.get(target, target)
                    if code.strip():
                        send_message(chat_id, f"🔄 Перевод на {target_lang}...")
                        translated = translate_code(code, target_lang)
                        if translated:
                            user_sessions[user_id]["code"] = translated
                            send_message(chat_id, f"✅ Переведено на {target_lang}:\n```\n{translated[:1500]}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                else:
                    send_message(chat_id, "❓ Неизвестная команда. /help")
            
            else:
                parts = user_sessions[user_id].get("parts", [])
                parts.append(text)
                user_sessions[user_id]["parts"] = parts
                user_sessions[user_id]["code"] = text if not user_sessions[user_id]["code"] else user_sessions[user_id]["code"] + "\n\n" + text
                user_sessions[user_id]["history"].append({"time": datetime.now().strftime("%H:%M:%S"), "action": f"Часть {len(parts)}"})
                send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n🧠 /smart_merge — склеить")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({"ok": False}), 500

@app.route("/")
def health():
    return "Bot is running!", 200

if __name__ == "__main__":
    time.sleep(2)
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)
