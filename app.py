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
            
            data = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 4000}
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
        logger.info(f"Сообщение отправлено в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
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

# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================
def auto_fix_code(code):
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.\n\nКод:\n{code}\n\nИсправленный код:"""
    return call_ai(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Опиши каждую ошибку кратко.\n\nКод:\n{code}\n\nОшибки:"""
    response = call_ai(prompt)
    return response

def analyze_complexity(code):
    lines = code.split("\n")
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
    functions = code.count("def ")
    classes = code.count("class ")
    branches = code.count("if ") + code.count("for ") + code.count("while ")
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "🟢 Низкая (хорошо)"
    elif complexity < 20:
        rating = "🟡 Средняя (нормально)"
    else:
        rating = "🔴 Высокая (нужен рефакторинг)"
    return f"📊 *Анализ сложности кода*\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Классов: {classes}\n• Цикломатическая сложность: {complexity:.1f}\n• Оценка: {rating}"

def generate_code(description):
    prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код.\n\nОписание: {description}\n\nКод:"""
    return call_ai(prompt)

def smart_merge(parts):
    if not parts:
        return ""
    parts_text = "\n\n--- ЧАСТЬ ---\n\n".join(parts)
    prompt = f"""Объедини эти части кода в один работающий файл. Верни ТОЛЬКО итоговый код.\n\nЧасти:\n{parts_text}\n\nИтоговый код:"""
    return call_ai(prompt)

def convert_code(code, target_lang):
    prompt = f"""Переведи этот код с Python на {target_lang}. Верни ТОЛЬКО код.\n\nКод:\n{code}\n\nКод на {target_lang}:"""
    return call_ai(prompt)

def generate_tests(code):
    prompt = f"""Напиши pytest тесты для этого кода. Верни ТОЛЬКО код тестов.\n\nКод:\n{code}\n\nТесты:"""
    return call_ai(prompt)

def code_review(code):
    prompt = f"""Проведи code review этого кода. Найди проблемы, дай рекомендации.\n\nКод:\n{code}\n\nОтвет:"""
    return call_ai(prompt)

def add_comments(code):
    prompt = f"""Добавь подробные комментарии к этому коду. Верни ТОЛЬКО код с комментариями.\n\nКод:\n{code}\n\nКод с комментариями:"""
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

def format_code(code, style="black"):
    prompt = f"""Отформатируй этот код в стиле {style}. Верни ТОЛЬКО отформатированный код.\n\nКод:\n{code}\n\nОтформатированный код:"""
    return call_ai(prompt)

def search_in_code(code, search_term):
    lines = code.split('\n')
    results = []
    for i, line in enumerate(lines, 1):
        if search_term.lower() in line.lower():
            results.append(f"Строка {i}: {line[:100]}")
    if results:
        return "🔍 *Результаты поиска:*\n\n" + "\n".join(results[:20])
    return "❌ Ничего не найдено"

def replace_in_code(code, old, new):
    return code.replace(old, new)

def fix_bug_by_description(code, bug_description):
    prompt = f"""Пользователь описал баг: {bug_description}
Исправь этот баг в коде. Верни ТОЛЬКО исправленный код.
Код:
{code}
Исправленный код:"""
    return call_ai(prompt)

def improve_code_by_description(code, improvement):
    prompt = f"""Улучши код согласно описанию: {improvement}
Верни ТОЛЬКО улучшенный код.
Код:
{code}
Улучшенный код:"""
    return call_ai(prompt)

def explain_code(code):
    prompt = f"""Объясни, что делает этот код. Кратко и понятно.
Код:
{code}
Объяснение:"""
    return call_ai(prompt)

def refactor_code_ai(code):
    prompt = f"""Проведи рефакторинг этого кода: улучши структуру, читаемость, удали дубликаты.
Верни ТОЛЬКО отрефакторенный код.
Код:
{code}
Отрефакторенный код:"""
    return call_ai(prompt)

def translate_code(code, target_lang):
    prompt = f"""Переведи этот код с Python на {target_lang}. Верни ТОЛЬКО код.
Код:
{code}
Код на {target_lang}:"""
    return call_ai(prompt)

def github_push(repo_name, filename, content):
    if not GITHUB_TOKEN:
        return "❌ GitHub токен не настроен"
    try:
        from github import Github
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        try:
            repo = user.get_repo(repo_name)
        except:
            repo = user.create_repo(repo_name)
        try:
            file = repo.get_contents(filename)
            repo.update_file(filename, f"Update {filename}", content, file.sha)
        except:
            repo.create_file(filename, f"Add {filename}", content)
        return f"✅ Код загружен в GitHub!\n🔗 https://github.com/{user.login}/{repo_name}/blob/main/{filename}"
    except Exception as e:
        return f"❌ Ошибка GitHub: {e}"

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

def find_logic_bugs(code):
    prompt = f"""Найди логические ошибки в этом коде. Верни JSON.
Код:
{code}
JSON с ошибками:"""
    response = call_ai(prompt)
    if response:
        try:
            return json.loads(response)
        except:
            return {"bugs": [{"message": response[:500]}]}
    return {"bugs": []}

def get_stats(user_id):
    data = user_sessions.get(user_id, {})
    code_len = len(data.get("code", ""))
    parts_count = len(data.get("parts", []))
    history_count = len(data.get("history", []))
    files_count = len(data.get("files", {}))
    return f"""📊 *Статистика пользователя:*
• Символов кода: {code_len}
• Частей кода: {parts_count}
• Действий в истории: {history_count}
• Файлов в проекте: {files_count}"""

# ==================== УМНАЯ СБОРКА ПРОЕКТА ====================

def detect_file_type(code):
    """Определяет, к какому файлу относится код"""
    code_lower = code.lower()
    
    if "def " in code or "import " in code or "class " in code or "if __name__" in code:
        return "python", "main.py"
    elif "from flask import" in code_lower or "@app.route" in code_lower:
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

def ask_merge_confirmation(chat_id, user_id, filename, part_count):
    """Спрашивает пользователя перед склейкой"""
    question = f"📦 Найдено {part_count} частей для файла `{filename}`.\n\nХотите собрать проект сейчас?"
    
    reply_markup = {
        "keyboard": [["✅ ДА, СОБРАТЬ ПРОЕКТ"], ["❌ НЕТ, ПОКА НЕ НАДО"], ["➕ ДОБАВИТЬ ЕЩЁ"]],
        "resize_keyboard": True
    }
    
    send_message(chat_id, question, reply_markup=json.dumps(reply_markup))
    user_sessions[user_id]["waiting_for"] = "confirm_merge"

def auto_mode_analysis(user_id, chat_id, code):
    """Умный авторежим: сам решает, что делать с кодом"""
    file_type, suggested_name = detect_file_type(code)
    
    if "project_parts" not in user_sessions[user_id]:
        user_sessions[user_id]["project_parts"] = {}
    
    if file_type not in user_sessions[user_id]["project_parts"]:
        user_sessions[user_id]["project_parts"][file_type] = []
    
    user_sessions[user_id]["project_parts"][file_type].append(code)
    
    part_count = len(user_sessions[user_id]["project_parts"][file_type])
    
    # Проверка на ошибки
    if "def " in code and (":" not in code.split('\n')[0] if code.split('\n') else True):
        fixed = auto_fix_code(code)
        if fixed and fixed != code:
            send_message(chat_id, f"🔧 *Автоисправление:* Обнаружена синтаксическая ошибка в `{suggested_name}`, код исправлен.")
            user_sessions[user_id]["project_parts"][file_type][-1] = fixed
            return fixed
    
    if part_count >= 2:
        ask_merge_confirmation(chat_id, user_id, suggested_name, part_count)
        send_message(chat_id, f"✅ *Часть {part_count} для `{suggested_name}` сохранена!*\n\nОжидаю подтверждения сборки...")
    else:
        send_message(chat_id, f"✅ *Часть {part_count} для `{suggested_name}` сохранена!*\n\n📦 Отправляйте следующие части. Когда закончите, нажмите «СОБРАТЬ ПРОЕКТ».")
    
    return code

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
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")

# ==================== СПИСОК КНОПОК ====================
BUTTONS = {
    "📝 ПОКАЗАТЬ КОД": "/show", "💾 СКАЧАТЬ КОД": "/done", "🔧 ИСПРАВИТЬ": "/fix",
    "🐛 ОШИБКИ": "/bugs", "📊 АНАЛИЗ": "/complexity", "✨ ГЕНЕРАЦИЯ": "/generate",
    "🎨 ФОРМАТ": "/format", "🔍 ПОИСК": "/search", "🔄 ЗАМЕНИТЬ": "/replace",
    "🐞 FIX BUG": "/fixbug", "⚡ УЛУЧШИТЬ": "/improve", "📖 ОБЪЯСНИТЬ": "/explain",
    "🔧 РЕФАКТОРИНГ": "/refactor", "🔄 ПЕРЕВОД": "/translate", "🧪 ТЕСТЫ": "/tests",
    "📋 CODE REVIEW": "/review", "📝 КОММЕНТАРИИ": "/comment", "📄 ЭКСПОРТ PDF": "/pdf",
    "🏆 ТЕСТЫ С ОТЧЁТОМ": "/test_report", "🧠 ЛОГИЧЕСКИЕ БАГИ": "/logic_bugs",
    "📁 ФАЙЛЫ": "/files", "➕ ДОБАВИТЬ ФАЙЛ": "/add_file", "🗑 УДАЛИТЬ ПОСЛЕДНИЙ": "/undo",
    "📜 ИСТОРИЯ": "/history", "📊 СТАТИСТИКА": "/stats", "🧠 УМНЫЙ АВТОРЕЖИМ": "/auto_mode",
    "📦 СОБРАТЬ ПРОЕКТ": "/build_project", "📁 ЭКСПОРТ": "/export", "🗑 ОЧИСТИТЬ ВСЁ": "/reset",
    "❓ ПОМОЩЬ": "/help", "🏠 СТАРТ": "/start"
}

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
                user_sessions[user_id] = {
                    "code": "", "parts": [], "history": [], "files": {},
                    "project_parts": {}, "project_files": {}, "auto_mode": False
                }
            
            # Преобразование кнопок в команды
            if text in BUTTONS:
                text = BUTTONS[text]
                logger.info(f"Кнопка -> команда: {text}")
            
            # ========== КОМАНДЫ ==========
            if text in ["/start", "/help"]:
                send_message(chat_id, 
                    "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
                    "📝 /show — показать код\n"
                    "💾 /done — скачать код\n"
                    "🔧 /fix — исправить ошибки\n"
                    "🐛 /bugs — найти ошибки\n"
                    "📊 /complexity — анализ сложности\n"
                    "✨ /generate — создать код по описанию\n"
                    "🎨 /format — отформатировать код\n"
                    "🔍 /search — поиск в коде\n"
                    "🔄 /replace — замена в коде\n"
                    "🐞 /fixbug — исправить баг по описанию\n"
                    "⚡ /improve — улучшить код\n"
                    "📖 /explain — объяснить код\n"
                    "🔧 /refactor — рефакторинг\n"
                    "🔄 /translate — перевод на другой язык\n"
                    "🧪 /tests — сгенерировать тесты\n"
                    "📋 /review — Code Review\n"
                    "📝 /comment — добавить комментарии\n"
                    "📄 /pdf — экспорт в PDF\n"
                    "🏆 /test_report — тесты с отчётом\n"
                    "🧠 /logic_bugs — логические баги\n"
                    "📁 /files — список файлов\n"
                    "➕ /add_file — добавить файл\n"
                    "🗑 /undo — удалить последнюю часть\n"
                    "📜 /history — история\n"
                    "📊 /stats — статистика\n"
                    "🧠 /auto_mode — умный авторежим\n"
                    "📦 /build_project — собрать проект из частей\n"
                    "📁 /export — экспорт ZIP\n"
                    "🗑 /reset — очистить всё",
                    reply_markup=json.dumps(get_keyboard()))
            
            elif text == "/show":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, f"```python\n{code[:3000]}\n```")
                else:
                    send_message(chat_id, "📭 Код пуст")
            
            elif text == "/done":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    filename = f"code_{user_id}.py"
                    with open(filename, "w") as f:
                        f.write(code)
                    send_document(chat_id, filename, "✅ Код")
                    os.remove(filename)
                else:
                    send_message(chat_id, "❌ Нет кода")
            
            elif text == "/fix":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🔧 AI исправляет код...")
                    fixed = auto_fix_code(code)
                    if fixed and fixed != code:
                        user_sessions[user_id]["code"] = fixed
                        send_message(chat_id, f"✅ Исправлено:\n```python\n{fixed[:1500]}\n```")
                    else:
                        send_message(chat_id, "✅ Код уже в хорошем состоянии")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/bugs":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🐛 AI ищет ошибки...")
                    bugs = find_bugs_ai(code)
                    if bugs:
                        send_message(chat_id, f"🔍 *Ошибки:*\n{bugs[:2000]}")
                    else:
                        send_message(chat_id, "✅ Ошибок не найдено")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/complexity":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, analyze_complexity(code))
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/generate":
                send_message(chat_id, "📝 *Опиши код для генерации:*\n\nНапример: 'калькулятор на Python'")
                user_sessions[user_id]["waiting_for"] = "generate"
            
            elif text == "/format":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🎨 Форматирование...")
                    formatted = format_code(code)
                    if formatted:
                        user_sessions[user_id]["code"] = formatted
                        send_message(chat_id, f"✅ Отформатировано:\n```python\n{formatted[:1500]}\n```")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/search":
                send_message(chat_id, "🔍 *Введите текст для поиска:*")
                user_sessions[user_id]["waiting_for"] = "search"
            
            elif text == "/replace":
                send_message(chat_id, "🔄 *Формат:* `старое | новое`\nПример: `print | println`")
                user_sessions[user_id]["waiting_for"] = "replace"
            
            elif text == "/fixbug":
                send_message(chat_id, "🐞 *Опишите баг для исправления:*\nНапример: 'функция не работает с отрицательными числами'")
                user_sessions[user_id]["waiting_for"] = "fixbug"
            
            elif text == "/improve":
                send_message(chat_id, "⚡ *Опишите улучшение:*\nНапример: 'добавить кэширование'")
                user_sessions[user_id]["waiting_for"] = "improve"
            
            elif text == "/explain":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "📖 AI объясняет код...")
                    explanation = explain_code(code)
                    send_message(chat_id, f"📖 *Объяснение:*\n{explanation[:2000]}")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/refactor":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🔧 Рефакторинг...")
                    refactored = refactor_code_ai(code)
                    if refactored:
                        user_sessions[user_id]["code"] = refactored
                        send_message(chat_id, f"✅ Отрефакторено:\n```python\n{refactored[:1500]}\n```")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/translate":
                send_message(chat_id, "🌐 *Выбери язык:*\nPython → JavaScript, Java, C++, Go, Rust")
                user_sessions[user_id]["waiting_for"] = "translate"
            
            elif text == "/tests":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🧪 Генерация тестов...")
                    tests = generate_tests(code)
                    if tests:
                        send_message(chat_id, f"✅ Тесты:\n```python\n{tests[:1500]}\n```")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/review":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "📋 Code Review...")
                    review = code_review(code)
                    send_message(chat_id, f"📋 *Review:*\n{review[:2000]}")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/comment":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "📝 Добавляю комментарии...")
                    commented = add_comments(code)
                    if commented:
                        user_sessions[user_id]["code"] = commented
                        send_message(chat_id, f"✅ Код с комментариями:\n```python\n{commented[:1500]}\n```")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/pdf":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    html = create_pdf_export(code)
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                        f.write(html)
                        html_file = f.name
                    send_document(chat_id, html_file, "📄 PDF экспорт")
                    os.remove(html_file)
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/test_report":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🏆 Запуск тестов с отчётом...")
                    report = run_tests_with_report(code)
                    send_message(chat_id, report)
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/logic_bugs":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🧠 Поиск логических ошибок...")
                    result = find_logic_bugs(code)
                    bugs = result.get("bugs", [])
                    if bugs:
                        report = "🧠 *Логические ошибки:*\n"
                        for b in bugs[:5]:
                            report += f"• {b.get('message', '')}\n"
                        send_message(chat_id, report)
                    else:
                        send_message(chat_id, "✅ Логических ошибок не найдено")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif text == "/files":
                files = user_sessions[user_id].get("files", {})
                if files:
                    file_list = "\n".join([f"• {n}" for n in files.keys()])
                    send_message(chat_id, f"📁 *Файлы:*\n{file_list}\n\n📄 Текущий: {user_sessions[user_id].get('current_file', 'main.py')}")
                else:
                    send_message(chat_id, "📭 Нет файлов")
            
            elif text == "/add_file":
                send_message(chat_id, "📝 Введите имя файла:")
                user_sessions[user_id]["waiting_for"] = "add_file"
            
            elif text == "/undo":
                parts = user_sessions[user_id].get("parts", [])
                if parts:
                    parts.pop()
                    user_sessions[user_id]["parts"] = parts
                    send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
                else:
                    send_message(chat_id, "📭 Нет частей")
            
            elif text == "/history":
                history = user_sessions[user_id].get("history", [])
                if history:
                    msg = "📜 *История:*\n"
                    for i, h in enumerate(history[-10:], 1):
                        msg += f"{i}. {h.get('action', '')}\n"
                    send_message(chat_id, msg)
                else:
                    send_message(chat_id, "📭 История пуста")
            
            elif text == "/stats":
                stats = get_stats(user_id)
                send_message(chat_id, stats)
            
            elif text == "/auto_mode":
                user_sessions[user_id]["auto_mode"] = not user_sessions[user_id].get("auto_mode", False)
                status = "включён" if user_sessions[user_id]["auto_mode"] else "выключен"
                send_message(chat_id, f"🧠 Умный авторежим {status}!")
            
            elif text == "/build_project":
                result = smart_assembler(user_id, chat_id)
                if result:
                    send_message(chat_id, result)
                else:
                    send_message(chat_id, "📭 Нет частей для сборки. Отправьте код частями сначала.")
            
            elif text == "/export":
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
            
            elif text == "/reset":
                user_sessions[user_id] = {
                    "code": "", "parts": [], "history": [], "files": {},
                    "project_parts": {}, "project_files": {}, "auto_mode": False
                }
                send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
            
            # ========== ОБРАБОТКА ОЖИДАНИЙ ==========
            elif user_sessions[user_id].get("waiting_for") == "generate":
                user_sessions[user_id]["waiting_for"] = None
                send_message(chat_id, "✨ AI генерирует код... (10-15 сек)")
                generated = generate_code(text)
                if generated:
                    user_sessions[user_id]["code"] = generated
                    send_message(chat_id, f"✅ *Сгенерировано:*\n```python\n{generated[:2000]}\n```")
                else:
                    send_message(chat_id, "❌ Ошибка генерации. Попробуйте позже.")
            
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
                    send_message(chat_id, "❌ Формат: `старое | новое`")
            
            elif user_sessions[user_id].get("waiting_for") == "fixbug":
                user_sessions[user_id]["waiting_for"] = None
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "🐞 Исправление бага...")
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
                    send_message(chat_id, "⚡ Улучшение кода...")
                    improved = improve_code_by_description(code, text)
                    if improved:
                        user_sessions[user_id]["code"] = improved
                        send_message(chat_id, f"✅ Код улучшен!\n```python\n{improved[:1500]}\n```")
                else:
                    send_message(chat_id, "📭 Нет кода")
            
            elif user_sessions[user_id].get("waiting_for") == "translate":
                user_sessions[user_id]["waiting_for"] = None
                code = user_sessions[user_id].get("code", "")
                lang_map = {"javascript": "JavaScript", "js": "JavaScript", "java": "Java", "cpp": "C++", "go": "Go", "rust": "Rust"}
                target = lang_map.get(text.lower(), text)
                if code.strip():
                    send_message(chat_id, f"🔄 Перевод на {target}...")
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
            
            elif user_sessions[user_id].get("waiting_for") == "confirm_merge":
                user_sessions[user_id]["waiting_for"] = None
                if text == "✅ ДА, СОБРАТЬ ПРОЕКТ":
                    result = smart_assembler(user_id, chat_id)
                    if result:
                        send_message(chat_id, result)
                        user_sessions[user_id]["project_parts"] = {}
                    else:
                        send_message(chat_id, "❌ Ошибка сборки")
                elif text == "❌ НЕТ, ПОКА НЕ НАДО":
                    send_message(chat_id, "📦 Сборка отложена. Отправляйте ещё части, а потом нажмите «СОБРАТЬ ПРОЕКТ».")
                else:
                    send_message(chat_id, "➕ Продолжайте отправлять части кода.")
            
            # ========== УМНЫЙ АВТОРЕЖИМ ==========
            elif user_sessions[user_id].get("auto_mode", False) and not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "✨", "🎨", "🔍", "🔄", "🐞", "⚡", "📖", "🧪", "📋", "📄", "🏆", "🧠", "📁", "➕", "🗑", "📜", "📦", "❓"]):
                auto_mode_analysis(user_id, chat_id, text)
            
            # ========== ОБЫЧНЫЙ КОД ==========
            else:
                parts = user_sessions[user_id].get("parts", [])
                parts.append(text)
                user_sessions[user_id]["parts"] = parts
                if user_sessions[user_id]["code"]:
                    user_sessions[user_id]["code"] += "\n\n" + text
                else:
                    user_sessions[user_id]["code"] = text
                user_sessions[user_id]["history"].append({"time": datetime.now().strftime("%H:%M:%S"), "action": f"Часть {len(parts)}"})
                send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n🔧 /fix — исправить\n✨ /generate — создать код\n🧠 /auto_mode — включить умный авторежим")
        
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
