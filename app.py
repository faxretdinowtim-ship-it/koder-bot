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
    """Вызов DeepSeek API с улучшенной обработкой ошибок"""
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000
        }
        response = requests.post(url, headers=headers, json=data, timeout=90)
        
        if response.status_code != 200:
            logger.error(f"DeepSeek API ошибка: {response.status_code} - {response.text}")
            return ""
        
        result = response.json()
        if "choices" not in result or not result["choices"]:
            logger.error(f"Неожиданный ответ от API: {result}")
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

# ==================== FALLBACK ГЕНЕРАЦИЯ КОДА ====================
def generate_fallback_code(description):
    """Простой генератор кода, когда AI недоступен"""
    desc_lower = description.lower()
    
    if "калькулятор" in desc_lower:
        return '''def calculator():
    while True:
        try:
            print("\\nКалькулятор")
            print("1 - Сложение")
            print("2 - Вычитание")
            print("3 - Умножение")
            print("4 - Деление")
            print("5 - Выход")
            
            choice = int(input("Выберите операцию: "))
            if choice == 5:
                break
            
            a = float(input("Введите первое число: "))
            b = float(input("Введите второе число: "))
            
            if choice == 1:
                print(f"Результат: {a + b}")
            elif choice == 2:
                print(f"Результат: {a - b}")
            elif choice == 3:
                print(f"Результат: {a * b}")
            elif choice == 4:
                if b != 0:
                    print(f"Результат: {a / b}")
                else:
                    print("Ошибка: деление на ноль!")
        except:
            print("Ошибка ввода!")

if __name__ == "__main__":
    calculator()'''
    
    elif "чат" in desc_lower or "мессенджер" in desc_lower or "веб чат" in desc_lower:
        return '''# Простой веб-чат
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

messages = []

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Чат</title>
    <style>
        body { font-family: Arial; margin: 20px; }
        #messages { border: 1px solid #ccc; height: 400px; overflow-y: scroll; padding: 10px; }
        .msg { margin: 5px 0; }
        .user { color: blue; }
        .bot { color: green; }
    </style>
</head>
<body>
    <h1>Чат</h1>
    <div id="messages"></div>
    <input type="text" id="input" placeholder="Введите сообщение...">
    <button onclick="send()">Отправить</button>
    <script>
        function load() {
            fetch('/messages')
                .then(r => r.json())
                .then(data => {
                    const div = document.getElementById('messages');
                    div.innerHTML = data.map(m => `<div class="${m.type}"><b>${m.type}:</b> ${m.text}</div>`).join('');
                });
        }
        function send() {
            const input = document.getElementById('input');
            fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: input.value})
            }).then(() => {
                input.value = '';
                load();
            });
        }
        setInterval(load, 1000);
        load();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/messages')
def get_messages():
    return jsonify(messages)

@app.route('/send', methods=['POST'])
def send_message():
    data = request.json
    user_msg = data.get('message', '')
    messages.append({"type": "user", "text": user_msg})
    messages.append({"type": "bot", "text": f"Вы сказали: {user_msg}"})
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)'''
    
    elif "телеграм" in desc_lower or "telegram" in desc_lower or "бот" in desc_lower:
        return '''import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "ВАШ_ТОКЕН"

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start - начать\\n/help - помощь")

if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    print("Бот запущен...")
    app.run_polling()'''
    
    elif "сортировка" in desc_lower:
        return '''def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr

def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)

# Пример использования
arr = [64, 34, 25, 12, 22, 11, 90]
print("Исходный массив:", arr)
print("Пузырьковая сортировка:", bubble_sort(arr.copy()))
print("Быстрая сортировка:", quick_sort(arr.copy()))'''
    
    elif "факториал" in desc_lower:
        return '''def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

# Пример использования
for i in range(1, 11):
    print(f"{i}! = {factorial(i)}")'''
    
    elif "фибоначчи" in desc_lower:
        return '''def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        print(a, end=" ")
        a, b = b, a + b
    print()

# Пример использования
print("Первые 10 чисел Фибоначчи:")
fibonacci(10)'''
    
    else:
        return f'''def main():
    print("Программа: {description[:100]}...")
    print()
    print("Этот код сгенерирован AI Code Bot")
    print("Для более точной генерации, опишите задачу подробнее:")
    print("- название функции")
    print("- входные и выходные данные")
    print("- пример использования")

if __name__ == "__main__":
    main()'''

# ==================== ГЕНЕРАЦИЯ КОДА (С FALLBACK) ====================
def generate_code(description):
    try:
        prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код, без объяснений.

Описание: {description}

Код:"""
        
        response = call_deepseek(prompt)
        
        if response and len(response) > 10:
            logger.info(f"AI успешно сгенерировал код для: {description[:50]}")
            return response
        else:
            logger.warning(f"AI не ответил на запрос: {description[:50]}, используем fallback")
            return generate_fallback_code(description)
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        return generate_fallback_code(description)

# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================
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
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding='utf-8') as f:
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
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.

Код:
{code}

Исправленный код:"""
    response = call_deepseek(prompt)
    return response if response and len(response) > 10 else code

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
    classes = code.count("class ")
    branches = code.count("if ") + code.count("for ") + code.count("while ")
    complexity = 1 + branches * 0.5
    rating = "Низкая" if complexity < 10 else "Средняя" if complexity < 20 else "Высокая"
    return f"""📊 *Анализ сложности кода*

• Строк кода: {code_lines}
• Функций: {functions}
• Классов: {classes}
• Цикломатическая сложность: {complexity:.1f}
• Оценка: {rating}"""

def smart_merge(parts):
    if not parts:
        return ""
    parts_text = "\n\n--- ЧАСТЬ ---\n\n".join(parts)
    prompt = f"""Объедини эти части кода в один работающий файл. Верни ТОЛЬКО итоговый код.

Части:
{parts_text}

Итоговый код:"""
    response = call_deepseek(prompt)
    return response if response else "\n\n".join(parts)

def convert_code(code, target_lang):
    prompt = f"""Переведи этот код с Python на {target_lang}. Верни ТОЛЬКО код.

Код:
{code}

Код на {target_lang}:"""
    response = call_deepseek(prompt)
    return response if response else f"# Ошибка перевода на {target_lang}\n# {code}"

def generate_tests(code):
    prompt = f"""Напиши pytest тесты для этого кода. Верни ТОЛЬКО код тестов.

Код:
{code}

Тесты:"""
    response = call_deepseek(prompt)
    return response if response else "# Не удалось сгенерировать тесты"

def code_review(code):
    prompt = f"""Проведи code review этого кода. Найди проблемы, дай рекомендации.

Код:
{code}

Ответ в формате:
✅ Что хорошо:
- ...

⚠️ Что можно улучшить:
- ...

💡 Рекомендации:
- ..."""
    response = call_deepseek(prompt)
    return response if response else "Не удалось выполнить Code Review"

def add_comments(code):
    prompt = f"""Добавь подробные комментарии к этому коду. Верни ТОЛЬКО код с комментариями.

Код:
{code}

Код с комментариями:"""
    response = call_deepseek(prompt)
    return response if response else code

def format_code(code):
    prompt = f"""Отформатируй этот код в стиле PEP 8. Верни ТОЛЬКО отформатированный код.

Код:
{code}

Отформатированный код:"""
    response = call_deepseek(prompt)
    return response if response else code

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
    response = call_deepseek(prompt)
    return response if response else code

def improve_code_by_description(code, improvement):
    prompt = f"""Улучши код согласно описанию: {improvement}
Верни ТОЛЬКО улучшенный код.
Код:
{code}
Улучшенный код:"""
    response = call_deepseek(prompt)
    return response if response else code

def explain_code(code):
    prompt = f"""Объясни, что делает этот код. Кратко и понятно.
Код:
{code}
Объяснение:"""
    response = call_deepseek(prompt)
    return response if response else "Не удалось объяснить код"

def refactor_code_ai(code):
    prompt = f"""Проведи рефакторинг этого кода: улучши структуру, читаемость, удали дубликаты.
Верни ТОЛЬКО отрефакторенный код.
Код:
{code}
Отрефакторенный код:"""
    response = call_deepseek(prompt)
    return response if response else code

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

# ==================== КЛАВИАТУРЫ ====================
def get_full_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код", "🔧 ИСПРАВИТЬ"],
            ["🐛 ОШИБКИ", "📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ"],
            ["✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА", "🔄 ПРЕОБРАЗОВАТЬ"],
            ["🧪 ТЕСТЫ", "📋 CODE REVIEW", "📝 КОММЕНТАРИИ"],
            ["📄 ЭКСПОРТ PDF", "🎨 ФОРМАТИРОВАТЬ", "🔍 ПОИСК"],
            ["🔄 ЗАМЕНИТЬ", "🐞 FIX BUG", "⚡ УЛУЧШИТЬ"],
            ["📖 ОБЪЯСНИТЬ", "🔧 РЕФАКТОРИНГ", "🔄 ПЕРЕВОД"],
            ["🌐 ДРУГИЕ ЯЗЫКИ", "🐙 GITHUB PUSH", "🎤 ГОЛОСОВОЙ ВВОД"],
            ["🧠 ЛОГИЧЕСКИЕ БАГИ", "🏆 ТЕСТЫ С ОТЧЁТОМ", "📦 ЭКСПОРТ JSON"],
            ["📄 ЭКСПОРТ HTML", "⚙️ НАСТРОЙКИ", "📊 СТАТИСТИКА"],
            ["📁 ФАЙЛЫ", "➕ ДОБАВИТЬ ФАЙЛ", "🗑 Удалить последний"],
            ["📜 ИСТОРИЯ", "🗑 ОЧИСТИТЬ ВСЁ", "❓ ПОМОЩЬ"]
        ],
        "resize_keyboard": True
    }

def get_settings_keyboard():
    return {
        "keyboard": [
            ["🔊 Уведомления ВКЛ", "🔇 Уведомления ВЫКЛ"],
            ["🌙 Тёмная тема", "☀️ Светлая тема"],
            ["💾 Автосохранение ВКЛ", "💾 Автосохранение ВЫКЛ"],
            ["🔙 ГЛАВНОЕ МЕНЮ"]
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

# ==================== СПИСОК ВСЕХ КНОПОК ====================
BUTTONS = [
    "📝 Показать код", "💾 Скачать код", "🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ",
    "📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ", "✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА",
    "🔄 ПРЕОБРАЗОВАТЬ", "🧪 ТЕСТЫ", "📋 CODE REVIEW", "📝 КОММЕНТАРИИ",
    "📄 ЭКСПОРТ PDF", "🎨 ФОРМАТИРОВАТЬ", "🔍 ПОИСК", "🔄 ЗАМЕНИТЬ",
    "🐞 FIX BUG", "⚡ УЛУЧШИТЬ", "📖 ОБЪЯСНИТЬ", "🔧 РЕФАКТОРИНГ",
    "🔄 ПЕРЕВОД", "🌐 ДРУГИЕ ЯЗЫКИ", "🐙 GITHUB PUSH", "🎤 ГОЛОСОВОЙ ВВОД",
    "🧠 ЛОГИЧЕСКИЕ БАГИ", "🏆 ТЕСТЫ С ОТЧЁТОМ", "📦 ЭКСПОРТ JSON",
    "📄 ЭКСПОРТ HTML", "⚙️ НАСТРОЙКИ", "📊 СТАТИСТИКА", "📁 ФАЙЛЫ",
    "➕ ДОБАВИТЬ ФАЙЛ", "🗑 Удалить последний", "📜 ИСТОРИЯ",
    "🗑 ОЧИСТИТЬ ВСЁ", "❓ ПОМОЩЬ", "🔙 ГЛАВНОЕ МЕНЮ",
    "🔊 Уведомления ВКЛ", "🔇 Уведомления ВЫКЛ", "🌙 Тёмная тема",
    "☀️ Светлая тема", "💾 Автосохранение ВКЛ", "💾 Автосохранение ВЫКЛ"
]

# ==================== WEBHOOK УСТАНОВКА ====================
def set_webhook():
    try:
        url = f"{API_URL}/setWebhook?url={WEBHOOK_URL}"
        response = requests.get(url, timeout=10)
        result = response.json()
        if result.get("ok"):
            logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")
        else:
            logger.error(f"❌ Ошибка установки webhook: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")
        return None

# ==================== ВЕБХУК ====================
@app.route("/webhook", methods=["POST"])
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
                    "code": "", "parts": [], "files": {"main.py": ""},
                    "current_file": "main.py", "history": [],
                    "settings": {"notifications": True, "theme": "dark", "autosave": True}
                }
            
            # Обработка приветствий
            greetings = ["привет", "здравствуй", "hello", "hi", "ку", "здарова", "добрый день", "доброе утро", "добрый вечер", "здравствуйте"]
            
            if text.startswith("/") or text in BUTTONS:
                # ========== ГЛАВНЫЕ КОМАНДЫ ==========
                if text in ["/start", "🔙 ГЛАВНОЕ МЕНЮ"]:
                    send_message(chat_id, "🤖 *AI Code Bot*\n\nВыбери действие:", reply_markup=json.dumps(get_full_keyboard()))
                
                elif text in ["/help", "❓ ПОМОЩЬ"]:
                    help_text = """🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*

*📝 ОСНОВНЫЕ КОМАНДЫ:*
/show — показать код
/done — скачать код
/fix — ИСПРАВИТЬ ошибки
/bugs — найти ошибки
/complexity — анализ сложности
/run — выполнить код

*🤖 AI ФУНКЦИИ:*
/generate — создать код по описанию
/smart_merge — умная склейка
/convert — преобразовать в другой язык
/tests — сгенерировать тесты
/review — Code Review
/comment — добавить комментарии
/explain — объяснить код
/refactor — рефакторинг

*🛠️ ИНСТРУМЕНТЫ:*
/format — форматирование кода
/search <текст> — поиск в коде
/replace <старое> <новое> — замена
/fixbug <описание> — исправление бага
/improve <описание> — улучшение кода

*📁 ФАЙЛЫ:*
/files — список файлов
/add_file — добавить файл
/undo — удалить последнюю часть
/history — история
/reset — очистить всё

*🌐 ДРУГОЕ:*
/languages — другие языки
/github_push — GitHub интеграция
/logic_bugs — логические баги
/test_report — тесты с отчётом
/settings — настройки
/stats — статистика"""
                    send_message(chat_id, help_text, reply_markup=json.dumps(get_full_keyboard()))
                
                elif text in ["/generate", "✨ ГЕНЕРАЦИЯ"]:
                    send_message(chat_id, "📝 *Опиши, какой код сгенерировать:*\n\nПримеры:\n- 'калькулятор на Python'\n- 'функция сортировки списка'\n- 'веб чат на Flask'\n- 'телеграм бот'")
                    user_sessions[user_id]["waiting_for"] = "generate"
                
                elif text in ["/show", "📝 Показать код"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, f"```python\n{code[:3500]}\n```")
                    else:
                        send_message(chat_id, "📭 Код пуст. Используй /generate для создания кода")
                
                elif text in ["/done", "💾 Скачать код"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        filename = f"code_{user_id}.py"
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(code)
                        send_document(chat_id, filename, "✅ Готовый код")
                        os.remove(filename)
                    else:
                        send_message(chat_id, "❌ Нет кода для скачивания")
                
                elif text in ["/fix", "🔧 ИСПРАВИТЬ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🔧 AI исправляет код... (5-10 сек)")
                        fixed = auto_fix_code(code)
                        if fixed and fixed != code:
                            user_sessions[user_id]["code"] = fixed
                            send_message(chat_id, f"✅ Исправлено:\n```python\n{fixed[:1500]}\n```")
                        else:
                            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
                    else:
                        send_message(chat_id, "📭 Нет кода для исправления")
                
                elif text in ["/bugs", "🐛 ОШИБКИ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🐛 AI ищет ошибки... (3-5 сек)")
                        bugs = find_bugs_ai(code)
                        if bugs:
                            report = "🔍 *Найденные ошибки:*\n\n"
                            for b in bugs[:5]:
                                report += f"• {b.get('message', '')}\n"
                            send_message(chat_id, report)
                        else:
                            send_message(chat_id, "✅ Ошибок не найдено!")
                    else:
                        send_message(chat_id, "📭 Нет кода для проверки")
                
                elif text in ["/complexity", "📊 АНАЛИЗ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        analysis = analyze_complexity(code)
                        send_message(chat_id, analysis)
                    else:
                        send_message(chat_id, "📭 Нет кода для анализа")
                
                elif text in ["/run", "🏃 ЗАПУСТИТЬ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🏃 Запуск кода в песочнице...")
                        result = run_code_safe(code)
                        if result["success"]:
                            output = result["output"][:2000] if result["output"] else "(нет вывода)"
                            send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```")
                        else:
                            error = result["error"][:1500] if result["error"] else "Неизвестная ошибка"
                            send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```")
                    else:
                        send_message(chat_id, "📭 Нет кода для запуска")
                
                elif text in ["/smart_merge", "🧠 УМНАЯ СКЛЕЙКА"]:
                    parts = user_sessions[user_id].get("parts", [])
                    if parts:
                        send_message(chat_id, "🧠 AI склеивает части кода... (5-10 сек)")
                        merged = smart_merge(parts)
                        if merged:
                            user_sessions[user_id]["code"] = merged
                            user_sessions[user_id]["parts"] = []
                            send_message(chat_id, f"✅ Код склеен!\n📊 Размер: {len(merged)} символов\n\n/show — посмотреть")
                        else:
                            send_message(chat_id, "❌ Ошибка склейки")
                    else:
                        send_message(chat_id, "📭 Нет частей для склейки")
                
                elif text in ["/format", "🎨 ФОРМАТИРОВАТЬ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🎨 Форматирование кода...")
                        formatted = format_code(code)
                        if formatted and formatted != code:
                            user_sessions[user_id]["code"] = formatted
                            send_message(chat_id, f"✅ Отформатировано:\n```python\n{formatted[:1500]}\n```")
                        else:
                            send_message(chat_id, "✅ Код уже в хорошем формате")
                    else:
                        send_message(chat_id, "📭 Нет кода для форматирования")
                
                elif text in ["/search", "🔍 ПОИСК"]:
                    send_message(chat_id, "🔍 *Введите текст для поиска в коде:*")
                    user_sessions[user_id]["waiting_for"] = "search"
                
                elif text in ["/replace", "🔄 ЗАМЕНИТЬ"]:
                    send_message(chat_id, "🔄 *Формат:* `старое | новое`\nПример: `print | println`")
                    user_sessions[user_id]["waiting_for"] = "replace"
                
                elif text in ["/fixbug", "🐞 FIX BUG"]:
                    send_message(chat_id, "🐞 *Опишите баг, который нужно исправить:*\n\nПример: 'функция divide падает при делении на ноль'")
                    user_sessions[user_id]["waiting_for"] = "fixbug"
                
                elif text in ["/improve", "⚡ УЛУЧШИТЬ"]:
                    send_message(chat_id, "⚡ *Опишите, как улучшить код:*\n\nПример: 'добавить кэширование' или 'ускорить выполнение'")
                    user_sessions[user_id]["waiting_for"] = "improve"
                
                elif text in ["/explain", "📖 ОБЪЯСНИТЬ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "📖 AI анализирует код... (5-10 сек)")
                        explanation = explain_code(code)
                        send_message(chat_id, f"📖 *Объяснение кода:*\n\n{explanation[:2000]}")
                    else:
                        send_message(chat_id, "📭 Нет кода для объяснения")
                
                elif text in ["/refactor", "🔧 РЕФАКТОРИНГ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🔧 Рефакторинг кода... (5-10 сек)")
                        refactored = refactor_code_ai(code)
                        if refactored and refactored != code:
                            user_sessions[user_id]["code"] = refactored
                            send_message(chat_id, f"✅ Отрефакторенный код:\n```python\n{refactored[:1500]}\n```")
                        else:
                            send_message(chat_id, "✅ Код уже оптимизирован")
                    else:
                        send_message(chat_id, "📭 Нет кода для рефакторинга")
                
                elif text in ["/translate", "🔄 ПЕРЕВОД"]:
                    send_message(chat_id, "🌐 *Введите целевой язык:*\n\nДоступные языки: JavaScript, Java, C++, Go, Rust")
                    user_sessions[user_id]["waiting_for"] = "translate_lang"
                
                elif text in ["/pdf", "📄 ЭКСПОРТ PDF"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        html = create_pdf_export(code)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                            f.write(html)
                            html_file = f.name
                        send_document(chat_id, html_file, "📄 Экспорт кода (HTML для печати в PDF)")
                        os.remove(html_file)
                    else:
                        send_message(chat_id, "📭 Нет кода для экспорта")
                
                elif text in ["/export_json", "📦 ЭКСПОРТ JSON"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        json_data = json.dumps({"code": code, "timestamp": str(datetime.now())}, ensure_ascii=False)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                            f.write(json_data)
                            fname = f.name
                        send_document(chat_id, fname, "📦 JSON экспорт")
                        os.remove(fname)
                    else:
                        send_message(chat_id, "📭 Нет кода для экспорта")
                
                elif text in ["/export_html", "📄 ЭКСПОРТ HTML"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Code Export</title>
<style>body{{font-family:monospace;padding:20px;}}pre{{background:#f5f5f5;padding:15px;overflow-x:auto;}}</style>
</head>
<body>
<h1>Экспорт кода</h1>
<p>Дата: {datetime.now()}</p>
<pre>{code}</pre>
<hr>
<p>Создано AI Code Bot</p>
</body>
</html>"""
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                            f.write(html)
                            fname = f.name
                        send_document(chat_id, fname, "📄 HTML экспорт")
                        os.remove(fname)
                    else:
                        send_message(chat_id, "📭 Нет кода для экспорта")
                
                elif text in ["/tests", "🧪 ТЕСТЫ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🧪 Генерация тестов... (5-10 сек)")
                        tests = generate_tests(code)
                        if tests:
                            send_message(chat_id, f"✅ Сгенерированные тесты:\n```python\n{tests[:2000]}\n```")
                        else:
                            send_message(chat_id, "❌ Не удалось сгенерировать тесты")
                    else:
                        send_message(chat_id, "📭 Нет кода для генерации тестов")
                
                elif text in ["/review", "📋 CODE REVIEW"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "📋 AI проводит Code Review... (5-10 сек)")
                        review = code_review(code)
                        send_message(chat_id, f"📋 *Code Review:*\n\n{review[:2000]}")
                    else:
                        send_message(chat_id, "📭 Нет кода для ревью")
                
                elif text in ["/comment", "📝 КОММЕНТАРИИ"]:
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "📝 AI добавляет комментарии... (5-10 сек)")
                        commented = add_comments(code)
                        if commented and commented != code:
                            user_sessions[user_id]["code"] = commented
                            send_message(chat_id, f"✅ Код с комментариями:\n```python\n{commented[:2000]}\n```")
                        else:
                            send_message(chat_id, "✅ Комментарии уже есть или AI не смог их добавить")
                    else:
                        send_message(chat_id, "📭 Нет кода для добавления комментариев")
                
                elif text in ["/files", "📁 ФАЙЛЫ"]:
                    files = user_sessions[user_id].get("files", {})
                    if files:
                        file_list = "\n".join([f"• `{n}`" for n in files.keys()])
                        send_message(chat_id, f"📁 *Файлы проекта:*\n{file_list}\n\n📄 Текущий: `{user_sessions[user_id].get('current_file', 'main.py')}`\n\n/switch_file <имя> — переключиться")
                    else:
                        send_message(chat_id, "📭 Нет файлов. Используй /add_file")
                
                elif text in ["/add_file", "➕ ДОБАВИТЬ ФАЙЛ"]:
                    send_message(chat_id, "📝 *Введите имя файла:*\n\nНапример: `app.py`, `index.html`, `style.css`")
                    user_sessions[user_id]["waiting_for"] = "add_file"
                
                elif text in ["/undo", "🗑 Удалить последний"]:
                    parts = user_sessions[user_id].get("parts", [])
                    if parts:
                        parts.pop()
                        user_sessions[user_id]["parts"] = parts
                        send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
                    else:
                        send_message(chat_id, "📭 Нет частей для удаления")
                
                elif text in ["/history", "📜 ИСТОРИЯ"]:
                    history = user_sessions[user_id].get("history", [])
                    if history:
                        msg = "📜 *История действий:*\n\n"
                        for i, h in enumerate(history[-15:], 1):
                            time_str = h.get('time', '')[:16]
                            action = h.get('action', 'Действие')
                            msg += f"{i}. [{time_str}] {action}\n"
                        send_message(chat_id, msg)
                    else:
                        send_message(chat_id, "📭 История пуста")
                
                elif text in ["/reset", "🗑 ОЧИСТИТЬ ВСЁ"]:
                    user_sessions[user_id] = {
                        "code": "", "parts": [], "files": {"main.py": ""},
                        "current_file": "main.py", "history": [],
                        "settings": {"notifications": True, "theme": "dark", "autosave": True}
                    }
                    send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_full_keyboard()))
                
                elif text in ["/settings", "⚙️ НАСТРОЙКИ"]:
                    send_message(chat_id, "⚙️ *Настройки бота:*\n\nВыберите параметр:", reply_markup=json.dumps(get_settings_keyboard()))
                
                elif text in ["/stats", "📊 СТАТИСТИКА"]:
                    stats = get_stats(user_id)
                    send_message(chat_id, stats)
                
                elif text in ["/languages", "🌐 ДРУГИЕ ЯЗЫКИ"]:
                    send_message(chat_id, "🌐 *Выберите язык для преобразования:*", reply_markup=json.dumps(get_languages_keyboard()))
                
                elif text in ["🔊 Уведомления ВКЛ"]:
                    user_sessions[user_id]["settings"]["notifications"] = True
                    send_message(chat_id, "🔊 Уведомления включены")
                
                elif text in ["🔇 Уведомления ВЫКЛ"]:
                    user_sessions[user_id]["settings"]["notifications"] = False
                    send_message(chat_id, "🔇 Уведомления выключены")
                
                elif text in ["🌙 Тёмная тема"]:
                    user_sessions[user_id]["settings"]["theme"] = "dark"
                    send_message(chat_id, "🌙 Тёмная тема установлена")
                
                elif text in ["☀️ Светлая тема"]:
                    user_sessions[user_id]["settings"]["theme"] = "light"
                    send_message(chat_id, "☀️ Светлая тема установлена")
                
                elif text in ["💾 Автосохранение ВКЛ"]:
                    user_sessions[user_id]["settings"]["autosave"] = True
                    send_message(chat_id, "💾 Автосохранение включено")
                
                elif text in ["💾 Автосохранение ВЫКЛ"]:
                    user_sessions[user_id]["settings"]["autosave"] = False
                    send_message(chat_id, "💾 Автосохранение выключено")
                
                # ========== ОБРАБОТКА ОЖИДАНИЙ ==========
                elif user_sessions[user_id].get("waiting_for") == "generate":
                    user_sessions[user_id]["waiting_for"] = None
                    send_message(chat_id, "✨ AI генерирует код... (10-20 сек)")
                    generated = generate_code(text)
                    if generated:
                        user_sessions[user_id]["code"] = generated
                        if len(generated) > 2000:
                            send_message(chat_id, f"✅ *Код сгенерирован!*\n📊 Размер: {len(generated)} символов\n\n/show — посмотреть\n/run — выполнить")
                        else:
                            send_message(chat_id, f"✅ *Сгенерированный код:*\n\n```python\n{generated}\n```")
                    else:
                        send_message(chat_id, "❌ Ошибка генерации кода. Попробуй ещё раз или опиши подробнее.")
                
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
                            send_message(chat_id, f"✅ Заменено '{old}' на '{new}'\n\n/show — посмотреть результат")
                        else:
                            send_message(chat_id, "📭 Нет кода")
                    else:
                        send_message(chat_id, "❌ Неверный формат. Используй: `старое | новое`")
                
                elif user_sessions[user_id].get("waiting_for") == "fixbug":
                    user_sessions[user_id]["waiting_for"] = None
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "🐞 AI исправляет баг... (5-10 сек)")
                        fixed = fix_bug_by_description(code, text)
                        if fixed and fixed != code:
                            user_sessions[user_id]["code"] = fixed
                            send_message(chat_id, f"✅ Баг исправлен!\n```python\n{fixed[:1500]}\n```")
                        else:
                            send_message(chat_id, "❌ Не удалось исправить баг или он не найден")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif user_sessions[user_id].get("waiting_for") == "improve":
                    user_sessions[user_id]["waiting_for"] = None
                    code = user_sessions[user_id].get("code", "")
                    if code.strip():
                        send_message(chat_id, "⚡ AI улучшает код... (5-10 сек)")
                        improved = improve_code_by_description(code, text)
                        if improved and improved != code:
                            user_sessions[user_id]["code"] = improved
                            send_message(chat_id, f"✅ Код улучшен!\n```python\n{improved[:1500]}\n```")
                        else:
                            send_message(chat_id, "❌ Не удалось улучшить код")
                    else:
                        send_message(chat_id, "📭 Нет кода")
                
                elif user_sessions[user_id].get("waiting_for") == "translate_lang":
                    user_sessions[user_id]["waiting_for"] = None
                    code = user_sessions[user_id].get("code", "")
                    lang_map = {
                        "javascript": "JavaScript", "js": "JavaScript",
                        "java": "Java", "cpp": "C++", "c++": "C++",
                        "go": "Go", "rust": "Rust"
                    }
                    target = lang_map.get(text.lower(), text)
                    if code.strip():
                        send_message(chat_id, f"🔄 Перевод кода с Python на {target}... (10-15 сек)")
                        translated = convert_code(code, target)
                        if translated:
                            user_sessions[user_id]["code"] = translated
                            send_message(chat_id, f"✅ *Код переведён на {target}:*\n\n```{target.lower()}\n{translated[:1500]}\n```")
                        else:
                            send_message(chat_id, "❌ Ошибка перевода кода")
                    else:
                        send_message(chat_id, "📭 Нет кода для перевода")
                
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
                
                else:
                    send_message(chat_id, "❓ Неизвестная команда. Используй /help", reply_markup=json.dumps(get_full_keyboard()))
            
            # Обработка приветствий
            elif text.lower().strip() in greetings:
                send_message(chat_id, "👋 *Привет!* Я AI Code Bot.\n\n🤖 Я помогаю с кодом. Вот что я умею:\n\n"
                                      "✨ `/generate` — создать код по описанию\n"
                                      "🔧 `/fix` — исправить ошибки\n"
                                      "🔍 `/search` — найти в коде\n"
                                      "🎨 `/format` — отформатировать код\n"
                                      "📖 `/explain` — объяснить код\n"
                                      "🏃 `/run` — выполнить код\n"
                                      "📝 `/show` — показать код\n\n"
                                      "❓ `/help` — все команды\n\n"
                                      "📝 *Отправь код, и я помогу его обработать!*")
            else:
                parts = user_sessions[user_id].get("parts", [])
                parts.append(text)
                user_sessions[user_id]["parts"] = parts
                user_sessions[user_id]["code"] = text if not user_sessions[user_id]["code"] else user_sessions[user_id]["code"] + "\n\n" + text
                user_sessions[user_id]["history"].append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": f"Добавлена часть {len(parts)}"})
                
                # Проверка, похоже ли на код
                is_code = any(keyword in text for keyword in ["def ", "import ", "class ", "print(", "return ", "if ", "for ", "while ", "=", "{", "}", ":", "(", ")"])
                if is_code:
                    send_message(chat_id, f"✅ *Часть {len(parts)} сохранена как код!*\n📊 Размер части: {len(text)} символов\n\n🧠 /smart_merge — склеить все части\n🗑 /undo — удалить последнюю часть")
                else:
                    send_message(chat_id, f"📝 *Текст сохранён как часть {len(parts)}*\n\n💡 Это не похоже на код. Если хочешь сгенерировать код, используй `/generate`\n🗑 /undo — удалить")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")
        return jsonify({"ok": False}), 500

@app.route("/")
def health():
    return "🤖 AI Code Bot is running!", 200

if __name__ == "__main__":
    time.sleep(2)
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)
