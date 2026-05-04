import os
import re
import json
import logging
import tempfile
import subprocess
import time
import zipfile
from io import BytesIO
from datetime import datetime
from flask import Flask, request, jsonify
import requests

TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"https://bot-koder.onrender.com/webhook"

# ==================== AI ФУНКЦИЯ ====================
MODELS = ["Phi-4", "DeepSeek-R1", "Mistral-Large", "Llama-3.3-70B", "GPT-4o"]

def call_ai(prompt, is_system=False):
    """Вызов AI с системным промптом"""
    system_prompt = """Ты — профессиональный AI Code Assistant. Твоя специализация — ТОЛЬКО код.
Отвечай на РУССКОМ языке. Если вопрос не о коде — вежливо откажись. Всегда давай примеры кода.
Будь краток и по делу."""
    
    for model in MODELS:
        try:
            url = "https://models.inference.ai.azure.com/chat/completions"
            headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"}
            
            messages = []
            if is_system:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            data = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 2000}
            response = requests.post(url, headers=headers, json=data, timeout=60)
            if response.status_code != 200:
                continue
            content = response.json()["choices"][0]["message"]["content"]
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)
            return content.strip()
        except:
            continue
    return None

def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    except:
        pass

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
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.\n\nКод:\n{code}\n\nИсправленный код:"""
    return call_ai(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Опиши каждую ошибку кратко.\n\nКод:\n{code}\n\nОшибки:"""
    response = call_ai(prompt)
    return response

def solve_problem(problem):
    prompt = f"""Реши задачу по программированию. Напиши код на Python.\n\nЗадача: {problem}\n\nРешение:"""
    return call_ai(prompt)

def generate_code(description):
    prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код.\n\nОписание: {description}\n\nКод:"""
    return call_ai(prompt)

def analyze_complexity(code):
    lines = code.split("\n")
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
    functions = code.count("def ")
    classes = code.count("class ")
    branches = code.count("if ") + code.count("for ") + code.count("while ")
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "🟢 Низкая"
    elif complexity < 20:
        rating = "🟡 Средняя"
    else:
        rating = "🔴 Высокая"
    return f"📊 *Анализ сложности кода*\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Классов: {classes}\n• Сложность: {complexity:.1f}\n• Оценка: {rating}"

def format_code(code):
    prompt = f"""Отформатируй этот код. Верни ТОЛЬКО отформатированный код.\n\nКод:\n{code}\n\nОтформатированный код:"""
    return call_ai(prompt)

def search_in_code(code, term):
    lines = code.split('\n')
    results = [f"Строка {i+1}: {line[:80]}" for i, line in enumerate(lines) if term.lower() in line.lower()]
    return "🔍 *Результаты:*\n" + "\n".join(results[:20]) if results else "❌ Ничего не найдено"

def replace_in_code(code, old, new):
    return code.replace(old, new)

def fix_bug_by_description(code, bug_description):
    prompt = f"""Исправь баг в коде: {bug_description}\n\nКод:\n{code}\n\nИсправленный код:"""
    return call_ai(prompt)

def improve_code_by_description(code, improvement):
    prompt = f"""Улучши код: {improvement}\n\nКод:\n{code}\n\nУлучшенный код:"""
    return call_ai(prompt)

def explain_code(code):
    prompt = f"""Объясни, что делает этот код. Кратко и понятно.\n\nКод:\n{code}\n\nОбъяснение:"""
    return call_ai(prompt)

def refactor_code_ai(code):
    prompt = f"""Проведи рефакторинг кода. Улучши структуру, читаемость.\n\nКод:\n{code}\n\nОтрефакторенный код:"""
    return call_ai(prompt)

def translate_code(code, target_lang):
    prompt = f"""Переведи код с Python на {target_lang}. Верни ТОЛЬКО код.\n\nКод:\n{code}\n\nКод на {target_lang}:"""
    return call_ai(prompt)

def generate_tests(code):
    prompt = f"""Напиши pytest тесты для этого кода.\n\nКод:\n{code}\n\nТесты:"""
    return call_ai(prompt)

def code_review(code):
    prompt = f"""Проведи code review этого кода. Найди проблемы, дай рекомендации.\n\nКод:\n{code}\n\nReview:"""
    return call_ai(prompt)

def add_comments(code):
    prompt = f"""Добавь подробные комментарии к этому коду.\n\nКод:\n{code}\n\nКод с комментариями:"""
    return call_ai(prompt)

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

def run_tests_with_report(code):
    tests = generate_tests(code)
    if not tests:
        return "❌ Не удалось сгенерировать тесты"
    full_code = code + "\n\n" + tests
    result = run_code_safe(full_code)
    if result["success"]:
        return "✅ *Все тесты пройдены!*\n\n" + result['output'][:500]
    else:
        return "❌ *Тесты не пройдены!*\n\n" + result['error'][:500]

def get_stats(user_id):
    data = user_sessions.get(user_id, {})
    code_len = len(data.get("code", ""))
    parts_count = len(data.get("parts", []))
    history_count = len(data.get("history", []))
    return f"""📊 *Статистика:*\n• Символов кода: {code_len}\n• Частей: {parts_count}\n• Действий: {history_count}"""

# ==================== УМНАЯ СБОРКА ПРОЕКТА ====================

def detect_file_type(code):
    """Определяет, к какому файлу относится код"""
    code_lower = code.lower()
    
    if "def " in code or "import " in code or "class " in code or "if __name__" in code or "@app.route" in code:
        return "python", "main.py"
    elif from flask import" in code_lower:
        return "python", "app.py"
    elif "<html" in code_lower or "<!DOCTYPE" in code_lower or "<body" in code_lower:
        return "html", "index.html"
    elif "{" in code and "}" in code and ("body" in code_lower or "margin" in code_lower or "background" in code_lower):
        return "css", "style.css"
    elif "function" in code_lower or "const " in code or "let " in code or "document." in code_lower:
        return "javascript", "script.js"
    elif "SELECT" in code.upper() or "INSERT" in code.upper():
        return "sql", "database.sql"
    elif "docker" in code_lower or "FROM" in code.upper():
        return "dockerfile", "Dockerfile"
    else:
        return "unknown", "code.txt"

def smart_assembler(user_id, chat_id):
    """Умная сборка проекта из всех частей"""
    project_files = user_sessions[user_id].get("project_parts", {})
    
    if not project_files:
        return None
    
    grouped_files = {}
    for file_type, parts in project_files.items():
        for part in parts:
            detected_type, suggested_name = detect_file_type(part)
            if suggested_name not in grouped_files:
                grouped_files[suggested_name] = []
            grouped_files[suggested_name].append(part)
    
    final_files = {}
    errors_found = []
    
    for filename, code_parts in grouped_files.items():
        full_code = "\n\n".join(code_parts)
        
        if filename.endswith('.py'):
            check_result = auto_fix_code(full_code)
            if check_result and check_result != full_code:
                errors_found.append(f"• {filename}: исправлены ошибки")
                full_code = check_result
        
        final_files[filename] = full_code
    
    user_sessions[user_id]["project_files"] = final_files
    
    result_msg = "📦 *Проект успешно собран!*\n\n"
    result_msg += "📁 *Созданные файлы:*\n"
    for filename, code in final_files.items():
        result_msg += f"• `{filename}` ({len(code)} символов)\n"
    
    if errors_found:
        result_msg += "\n🔧 *Исправлено:*\n" + "\n".join(errors_found)
    
    result_msg += "\n\n💾 /export — скачать все файлы"
    
    return result_msg

def add_to_project(user_id, code):
    """Добавляет код в проект для умной сборки"""
    file_type, suggested_name = detect_file_type(code)
    
    if "project_parts" not in user_sessions[user_id]:
        user_sessions[user_id]["project_parts"] = {}
    
    if file_type not in user_sessions[user_id]["project_parts"]:
        user_sessions[user_id]["project_parts"][file_type] = []
    
    user_sessions[user_id]["project_parts"][file_type].append(code)
    
    return file_type, suggested_name

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 ПОКАЗАТЬ КОД", "💾 СКАЧАТЬ КОД"],
            ["🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ", "📊 АНАЛИЗ"],
            ["✨ ГЕНЕРАЦИЯ", "🎨 ФОРМАТ", "🔍 ПОИСК"],
            ["🔄 ЗАМЕНИТЬ", "🐞 FIX BUG", "⚡ УЛУЧШИТЬ"],
            ["📖 ОБЪЯСНИТЬ", "🔧 РЕФАКТОРИНГ", "🔄 ПЕРЕВОД"],
            ["🧪 ТЕСТЫ", "📋 CODE REVIEW", "📝 КОММЕНТАРИИ"],
            ["📄 ЭКСПОРТ PDF", "🏆 ТЕСТЫ С ОТЧЁТОМ", "🧠 ЛОГИЧЕСКИЕ БАГИ"],
            ["📁 ФАЙЛЫ", "➕ ДОБАВИТЬ ФАЙЛ", "🗑 УДАЛИТЬ ПОСЛЕДНИЙ"],
            ["📜 ИСТОРИЯ", "📊 СТАТИСТИКА", "🧠 УМНЫЙ АВТОРЕЖИМ"],
            ["📦 СОБРАТЬ ПРОЕКТ", "📁 ЭКСПОРТ", "🗑 ОЧИСТИТЬ ВСЁ"],
            ["❓ ПОМОЩЬ"]
        ],
        "resize_keyboard": True
    }

def set_webhook():
    try:
        url = f"{API_URL}/setWebhook?url={WEBHOOK_URL}"
        response = requests.get(url, timeout=10)
        if response.json().get("ok"):
            logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    except:
        pass

# ==================== ОБРАБОТКА ====================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"ok": True}), 200
        
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "")
        
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                "code": "", "parts": [], "history": [], "files": {},
                "project_parts": {}, "project_files": {}, "auto_mode": False
            }
        
        # ОБРАБОТКА КНОПОК
        if text == "📝 ПОКАЗАТЬ КОД":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                send_message(chat_id, f"```python\n{code[:3000]}\n```")
            else:
                send_message(chat_id, "📭 Код пуст")
        
        elif text == "💾 СКАЧАТЬ КОД":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                filename = f"code_{user_id}.py"
                with open(filename, "w") as f:
                    f.write(code)
                send_document(chat_id, filename, "✅ Код")
                os.remove(filename)
            else:
                send_message(chat_id, "❌ Нет кода")
        
        elif text == "🔧 ИСПРАВИТЬ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                send_message(chat_id, "🔧 AI исправляет код...")
                fixed = auto_fix_code(code)
                if fixed:
                    user_sessions[user_id]["code"] = fixed
                    send_message(chat_id, f"✅ Исправлено:\n```python\n{fixed[:1500]}\n```")
                else:
                    send_message(chat_id, "❌ Ошибка AI")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "🐛 ОШИБКИ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                send_message(chat_id, "🐛 AI ищет ошибки...")
                result = find_bugs_ai(code)
                send_message(chat_id, f"🔍 *Результат:*\n{result[:2000] if result else 'Ошибок не найдено'}")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "📊 АНАЛИЗ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                send_message(chat_id, analyze_complexity(code))
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "✨ ГЕНЕРАЦИЯ":
            send_message(chat_id, "📝 *Опиши код для генерации:*")
            user_sessions[user_id]["waiting_for"] = "generate"
        
        elif text == "🎨 ФОРМАТ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                send_message(chat_id, "🎨 Форматирование...")
                formatted = format_code(code)
                if formatted:
                    user_sessions[user_id]["code"] = formatted
                    send_message(chat_id, f"✅ Отформатировано:\n```python\n{formatted[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "🔍 ПОИСК":
            send_message(chat_id, "🔍 *Введите текст для поиска:*")
            user_sessions[user_id]["waiting_for"] = "search"
        
        elif text == "🔄 ЗАМЕНИТЬ":
            send_message(chat_id, "🔄 *Формат:* старое | новое")
            user_sessions[user_id]["waiting_for"] = "replace"
        
        elif text == "🐞 FIX BUG":
            send_message(chat_id, "🐞 *Опишите баг:*")
            user_sessions[user_id]["waiting_for"] = "fixbug"
        
        elif text == "⚡ УЛУЧШИТЬ":
            send_message(chat_id, "⚡ *Опишите улучшение:*")
            user_sessions[user_id]["waiting_for"] = "improve"
        
        elif text == "📖 ОБЪЯСНИТЬ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                explanation = explain_code(code)
                send_message(chat_id, f"📖 *Объяснение:*\n{explanation[:2000]}")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "🔧 РЕФАКТОРИНГ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                refactored = refactor_code_ai(code)
                if refactored:
                    user_sessions[user_id]["code"] = refactored
                    send_message(chat_id, f"✅ Отрефакторено:\n```python\n{refactored[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "🔄 ПЕРЕВОД":
            send_message(chat_id, "🌐 *Выбери язык:* Python → JavaScript, Java, C++, Go, Rust")
            user_sessions[user_id]["waiting_for"] = "translate"
        
        elif text == "🧪 ТЕСТЫ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                tests = generate_tests(code)
                if tests:
                    send_message(chat_id, f"✅ Тесты:\n```python\n{tests[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "📋 CODE REVIEW":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                review = code_review(code)
                send_message(chat_id, f"📋 *Review:*\n{review[:2000]}")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "📝 КОММЕНТАРИИ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                commented = add_comments(code)
                if commented:
                    user_sessions[user_id]["code"] = commented
                    send_message(chat_id, f"✅ Комментарии добавлены:\n```python\n{commented[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "📄 ЭКСПОРТ PDF":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                html = create_pdf_export(code)
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                    f.write(html)
                    fname = f.name
                send_document(chat_id, fname, "📄 PDF экспорт")
                os.remove(fname)
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "🏆 ТЕСТЫ С ОТЧЁТОМ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                report = run_tests_with_report(code)
                send_message(chat_id, report)
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "🧠 ЛОГИЧЕСКИЕ БАГИ":
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                send_message(chat_id, "🧠 AI ищет логические ошибки...")
                result = find_bugs_ai(f"Найди логические ошибки в коде:\n{code}")
                send_message(chat_id, f"🧠 *Результат:*\n{result[:2000]}")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif text == "📁 ФАЙЛЫ":
            files = user_sessions[user_id].get("files", {})
            if files:
                file_list = "\n".join([f"• {n}" for n in files.keys()])
                send_message(chat_id, f"📁 *Файлы:*\n{file_list}")
            else:
                send_message(chat_id, "📭 Нет файлов")
        
        elif text == "➕ ДОБАВИТЬ ФАЙЛ":
            send_message(chat_id, "📝 *Введите имя файла:*\nНапример: index.html, style.css, script.js")
            user_sessions[user_id]["waiting_for"] = "add_file"
        
        elif text == "🗑 УДАЛИТЬ ПОСЛЕДНИЙ":
            parts = user_sessions[user_id].get("parts", [])
            if parts:
                parts.pop()
                user_sessions[user_id]["parts"] = parts
                send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
            else:
                send_message(chat_id, "📭 Нет частей")
        
        elif text == "📜 ИСТОРИЯ":
            history = user_sessions[user_id].get("history", [])
            if history:
                msg = "📜 *История:*\n"
                for i, h in enumerate(history[-10:], 1):
                    msg += f"{i}. {h.get('action', '')}\n"
                send_message(chat_id, msg)
            else:
                send_message(chat_id, "📭 История пуста")
        
        elif text == "📊 СТАТИСТИКА":
            send_message(chat_id, get_stats(user_id))
        
        elif text == "🧠 УМНЫЙ АВТОРЕЖИМ":
            user_sessions[user_id]["auto_mode"] = not user_sessions[user_id].get("auto_mode", False)
            status = "включён" if user_sessions[user_id]["auto_mode"] else "выключен"
            send_message(chat_id, f"🧠 Умный авторежим {status}!")
        
        elif text == "📦 СОБРАТЬ ПРОЕКТ":
            result = smart_assembler(user_id, chat_id)
            if result:
                send_message(chat_id, result)
            else:
                send_message(chat_id, "📭 Нет частей для сборки. Отправьте код частями сначала.")
        
        elif text == "📁 ЭКСПОРТ":
            project_files = user_sessions[user_id].get("project_files", {})
            if project_files:
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for name, content in project_files.items():
                        zf.writestr(name, content)
                zip_buffer.seek(0)
                with open(f"project_{user_id}.zip", "wb") as f:
                    f.write(zip_buffer.getvalue())
                send_document(chat_id, f"project_{user_id}.zip", "📦 Архив проекта")
                os.remove(f"project_{user_id}.zip")
            else:
                send_message(chat_id, "📭 Нет собранного проекта. Сначала нажмите «СОБРАТЬ ПРОЕКТ».")
        
        elif text == "🗑 ОЧИСТИТЬ ВСЁ":
            user_sessions[user_id] = {
                "code": "", "parts": [], "history": [], "files": {},
                "project_parts": {}, "project_files": {}, "auto_mode": False
            }
            send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
        
        elif text == "❓ ПОМОЩЬ" or text == "/start":
            send_message(chat_id, 
                "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
                "📝 ПОКАЗАТЬ КОД — показать код\n"
                "💾 СКАЧАТЬ КОД — скачать файл\n"
                "🔧 ИСПРАВИТЬ — AI исправляет ошибки\n"
                "🐛 ОШИБКИ — AI находит ошибки\n"
                "📊 АНАЛИЗ — сложность кода\n"
                "✨ ГЕНЕРАЦИЯ — создать код\n"
                "🎨 ФОРМАТ — отформатировать\n"
                "🔍 ПОИСК — найти в коде\n"
                "🔄 ЗАМЕНИТЬ — заменить текст\n"
                "🐞 FIX BUG — исправить баг\n"
                "⚡ УЛУЧШИТЬ — улучшить код\n"
                "📖 ОБЪЯСНИТЬ — объяснить код\n"
                "🔧 РЕФАКТОРИНГ — рефакторинг\n"
                "🔄 ПЕРЕВОД — перевести на другой язык\n"
                "🧪 ТЕСТЫ — сгенерировать тесты\n"
                "📋 CODE REVIEW — ревью кода\n"
                "📝 КОММЕНТАРИИ — добавить комментарии\n"
                "📄 ЭКСПОРТ PDF — PDF экспорт\n"
                "🏆 ТЕСТЫ С ОТЧЁТОМ — запуск тестов\n"
                "🧠 ЛОГИЧЕСКИЕ БАГИ — поиск логических ошибок\n"
                "📁 ФАЙЛЫ — управление файлами\n"
                "➕ ДОБАВИТЬ ФАЙЛ — добавить файл\n"
                "📜 ИСТОРИЯ — история действий\n"
                "📊 СТАТИСТИКА — статистика\n"
                "🧠 УМНЫЙ АВТОРЕЖИМ — автоанализ кода\n"
                "📦 СОБРАТЬ ПРОЕКТ — собрать из частей\n"
                "📁 ЭКСПОРТ — скачать ZIP проекта\n"
                "🗑 ОЧИСТИТЬ ВСЁ — удалить всё\n\n"
                "💡 *Умная сборка:* отправляйте код частями, бот сам определит файлы!",
                reply_markup=json.dumps(get_keyboard()))
        
        # ОБРАБОТКА ОЖИДАНИЙ
        elif user_sessions[user_id].get("waiting_for") == "generate":
            user_sessions[user_id]["waiting_for"] = None
            send_message(chat_id, "✨ Генерация кода... (5-10 сек)")
            generated = generate_code(text)
            if generated:
                user_sessions[user_id]["code"] = generated
                send_message(chat_id, f"✅ *Сгенерировано:*\n```python\n{generated[:2000]}\n```")
            else:
                send_message(chat_id, "❌ Ошибка генерации")
        
        elif user_sessions[user_id].get("waiting_for") == "search":
            user_sessions[user_id]["waiting_for"] = None
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                result = search_in_code(code, text)
                send_message(chat_id, result)
            else:
                send_message(chat_id, "📭 Нет кода для поиска")
        
        elif user_sessions[user_id].get("waiting_for") == "replace":
            user_sessions[user_id]["waiting_for"] = None
            if "|" in text:
                old, new = text.split("|", 1)
                old = old.strip()
                new = new.strip()
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    new_code = replace_in_code(code, old, new)
                    user_sessions[user_id]["code"] = new_code
                    send_message(chat_id, f"✅ Заменено '{old}' на '{new}'")
                else:
                    send_message(chat_id, "📭 Нет кода")
            else:
                send_message(chat_id, "❌ Формат: старое | новое")
        
        elif user_sessions[user_id].get("waiting_for") == "fixbug":
            user_sessions[user_id]["waiting_for"] = None
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                fixed = fix_bug_by_description(code, text)
                if fixed:
                    user_sessions[user_id]["code"] = fixed
                    send_message(chat_id, f"✅ Баг исправлен!\n```python\n{fixed[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif user_sessions[user_id].get("waiting_for") == "improve":
            user_sessions[user_id]["waiting_for"] = None
            code = user_sessions[user_id].get("code", "")
            if code.strip():
                improved = improve_code_by_description(code, text)
                if improved:
                    user_sessions[user_id]["code"] = improved
                    send_message(chat_id, f"✅ Код улучшен!\n```python\n{improved[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif user_sessions[user_id].get("waiting_for") == "translate":
            user_sessions[user_id]["waiting_for"] = None
            code = user_sessions[user_id].get("code", "")
            target = text.lower()
            if code.strip():
                translated = translate_code(code, target)
                if translated:
                    user_sessions[user_id]["code"] = translated
                    send_message(chat_id, f"✅ Переведено на {target}:\n```\n{translated[:1500]}\n```")
            else:
                send_message(chat_id, "📭 Нет кода")
        
        elif user_sessions[user_id].get("waiting_for") == "add_file":
            user_sessions[user_id]["waiting_for"] = None
            filename = text.strip()
            user_sessions[user_id]["files"][filename] = ""
            send_message(chat_id, f"✅ Файл `{filename}` создан!")
        
        # УМНЫЙ АВТОРЕЖИМ (если включён и это не команда)
        elif user_sessions[user_id].get("auto_mode", False) and not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "✨", "🎨", "🔍", "🔄", "🐞", "⚡", "📖", "🧪", "📋", "📄", "🏆", "🧠", "📁", "➕", "🗑", "📜", "📦", "❓"]):
            file_type, filename = add_to_project(user_id, text)
            send_message(chat_id, f"✅ *Код добавлен в проект как `{filename}`*\n\n📦 Когда закончите, нажмите «СОБРАТЬ ПРОЕКТ».")
        
        # ОБЫЧНЫЙ КОД (сохраняется как есть)
        else:
            user_sessions[user_id]["code"] = text
            send_message(chat_id, f"✅ *Код сохранён!*\n\n🔧 /fix — исправить\n✨ /generate — создать код")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({"ok": False}), 500

@app.route("/")
def health():
    return "Bot is running!", 200

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)
