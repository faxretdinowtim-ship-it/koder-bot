import os
import re
import json
import logging
import tempfile
import subprocess
import time
from datetime import datetime
from flask import Flask, request, jsonify
import requests

TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
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

# ==================== ФУНКЦИИ ====================
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
    prompt = f"""Объедини эти части кода в один работающий файл. Верни ТОЛЬКО итоговый код.

Части:
{chr(10).join([f"--- ЧАСТЬ {i+1} ---\n{p}" for i, p in enumerate(parts)])}

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

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ"],
            ["📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ"],
            ["✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА"],
            ["🔄 ПРЕОБРАЗОВАТЬ", "🧪 ТЕСТЫ"],
            ["📋 CODE REVIEW", "📝 ДОБАВИТЬ КОММЕНТАРИИ"],
            ["📄 ЭКСПОРТ PDF", "🌐 ДРУГИЕ ЯЗЫКИ"],
            ["📁 ФАЙЛЫ", "➕ ДОБАВИТЬ ФАЙЛ"],
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

# ==================== СПИСОК КОМАНД И КНОПОК (НЕ СОХРАНЯТЬ В КОД) ====================
COMMANDS = [
    "/start", "/show", "/done", "/fix", "/bugs", "/complexity", 
    "/run", "/generate", "/reset", "/help", "/smart_merge",
    "/convert", "/tests", "/review", "/comment", "/pdf",
    "/languages", "/files", "/add_file", "/switch_file", "/export",
    "/undo", "/history"
]

BUTTONS = [
    "📝 Показать код", "💾 Скачать код", "🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ",
    "📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ", "✨ ГЕНЕРАЦИЯ", "🧠 УМНАЯ СКЛЕЙКА",
    "🔄 ПРЕОБРАЗОВАТЬ", "🧪 ТЕСТЫ", "📋 CODE REVIEW", "📝 ДОБАВИТЬ КОММЕНТАРИИ",
    "📄 ЭКСПОРТ PDF", "🌐 ДРУГИЕ ЯЗЫКИ", "📁 ФАЙЛЫ", "➕ ДОБАВИТЬ ФАЙЛ",
    "🗑 Удалить последний", "📜 ИСТОРИЯ", "🗑 ОЧИСТИТЬ ВСЁ", "❓ ПОМОЩЬ"
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
            
            # Проверяем, является ли текст командой или кнопкой (НЕ СОХРАНЯЕМ В КОД)
            if text.startswith("/") or text in BUTTONS:
                # Обработка команд
                if text == "/start" or text == "❓ ПОМОЩЬ":
                    send_message(chat_id, 
                        "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
                        "✨ /generate — создать код по описанию\n"
                        "🧠 /smart_merge — умная склейка\n"
                        "🔄 /convert — преобразовать в другой язык\n"
                        "🧪 /tests — сгенерировать тесты\n"
                        "📋 /review — Code Review\n"
                        "📝 /comment — добавить комментарии\n"
                        "📄 /pdf — экспорт в PDF\n"
                        "🌐 /languages — другие языки\n"
                        "📁 /files — управление файлами\n"
                        "🗑 /undo — удалить последнюю часть\n"
                        "📜 /history — история\n"
                        "🔧 /fix — исправить ошибки\n"
                        "🐛 /bugs — найти ошибки\n"
                        "📊 /complexity — анализ сложности\n"
                        "🏃 /run — выполнить код\n"
                        "📝 /show — показать код\n"
                        "💾 /done — скачать код\n"
                        "🗑 /reset — очистить всё",
                        reply_markup=json.dumps(get_keyboard()))
                
                elif text == "/show" or text == "📝 Показать код":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Код пуст. Отправь код или используй /generate")
                    else:
                        send_message(chat_id, f"```python\n{code[:3000]}\n```")
                
                elif text == "/done" or text == "💾 Скачать код":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "❌ Нет кода")
                    else:
                        filename = f"code_{user_id}.py"
                        with open(filename, "w") as f:
                            f.write(code)
                        send_document(chat_id, filename, "✅ Код")
                        os.remove(filename)
                
                elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для исправления")
                    else:
                        send_message(chat_id, "🔧 AI исправляет код... (5-10 сек)")
                        fixed = auto_fix_code(code)
                        if fixed and fixed != code:
                            user_sessions[user_id]["code"] = fixed
                            send_message(chat_id, f"✅ Исправлено:\n```python\n{fixed[:1500]}\n```")
                        else:
                            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
                
                elif text == "/bugs" or text == "🐛 ОШИБКИ":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для проверки")
                    else:
                        send_message(chat_id, "🐛 AI ищет ошибки... (3-5 сек)")
                        bugs = find_bugs_ai(code)
                        if bugs:
                            report = "🔍 *Найденные ошибки:*\n\n"
                            for b in bugs[:5]:
                                report += f"• {b.get('message', '')}\n"
                            send_message(chat_id, report)
                        else:
                            send_message(chat_id, "✅ Ошибок не найдено!")
                
                elif text == "/complexity" or text == "📊 АНАЛИЗ":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для анализа")
                    else:
                        analysis = analyze_complexity(code)
                        send_message(chat_id, f"📊 {analysis}")
                
                elif text == "/run" or text == "🏃 ЗАПУСТИТЬ":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для запуска")
                    else:
                        send_message(chat_id, "🏃 Запуск...")
                        result = run_code_safe(code)
                        if result["success"]:
                            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1500]}\n```")
                        else:
                            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:500]}\n```")
                
                elif text == "/generate" or text == "✨ ГЕНЕРАЦИЯ":
                    send_message(chat_id, "📝 *Опиши, какой код сгенерировать:*\n\nПример:\n- 'калькулятор на Python'\n- 'функция для сортировки списка'")
                    user_sessions[user_id]["waiting_for"] = "generate"
                
                elif text == "/smart_merge" or text == "🧠 УМНАЯ СКЛЕЙКА":
                    parts = user_sessions[user_id].get("parts", [])
                    if not parts:
                        send_message(chat_id, "📭 Нет частей для склейки. Отправляй код частями!")
                    else:
                        send_message(chat_id, "🧠 AI склеивает части... (5-10 сек)")
                        merged = smart_merge(parts)
                        if merged:
                            user_sessions[user_id]["code"] = merged
                            user_sessions[user_id]["parts"] = []
                            send_message(chat_id, f"✅ Код склеен!\n\n/show — посмотреть")
                        else:
                            send_message(chat_id, "❌ Ошибка склейки")
                
                elif text == "/reset" or text == "🗑 ОЧИСТИТЬ ВСЁ":
                    user_sessions[user_id] = {"code": "", "parts": [], "files": {"main.py": ""}, "current_file": "main.py", "history": []}
                    send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
                
                # НОВЫЕ ФУНКЦИИ
                elif text == "/tests" or text == "🧪 ТЕСТЫ":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для генерации тестов")
                    else:
                        send_message(chat_id, "🧪 AI генерирует тесты... (5-10 сек)")
                        tests = generate_tests(code)
                        if tests:
                            send_message(chat_id, f"✅ Тесты:\n```python\n{tests[:2000]}\n```")
                        else:
                            send_message(chat_id, "❌ Ошибка генерации тестов")
                
                elif text == "/review" or text == "📋 CODE REVIEW":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для ревью")
                    else:
                        send_message(chat_id, "📋 AI проводит Code Review... (5-10 сек)")
                        review = code_review(code)
                        send_message(chat_id, f"📋 *Code Review:*\n\n{review[:2000]}")
                
                elif text == "/comment" or text == "📝 ДОБАВИТЬ КОММЕНТАРИИ":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для добавления комментариев")
                    else:
                        send_message(chat_id, "📝 AI добавляет комментарии... (5-10 сек)")
                        commented = add_comments(code)
                        if commented:
                            user_sessions[user_id]["code"] = commented
                            send_message(chat_id, f"✅ Код с комментариями:\n```python\n{commented[:2000]}\n```")
                        else:
                            send_message(chat_id, "❌ Ошибка")
                
                elif text == "/pdf" or text == "📄 ЭКСПОРТ PDF":
                    code = user_sessions[user_id].get("code", "")
                    if not code.strip():
                        send_message(chat_id, "📭 Нет кода для экспорта")
                    else:
                        html = create_pdf_export(code)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                            f.write(html)
                            html_file = f.name
                        send_document(chat_id, html_file, "📄 Экспорт кода")
                        os.remove(html_file)
                
                elif text == "/languages" or text == "🌐 ДРУГИЕ ЯЗЫКИ":
                    send_message(chat_id, "🌐 *Выбери язык для преобразования:*", reply_markup=json.dumps(get_languages_keyboard()))
                
                elif text == "/files" or text == "📁 ФАЙЛЫ":
                    files = user_sessions[user_id].get("files", {})
                    if not files:
                        send_message(chat_id, "📭 Нет файлов. Используй /add_file")
                    else:
                        file_list = "\n".join([f"• {name}" for name in files.keys()])
                        send_message(chat_id, f"📁 *Файлы:*\n{file_list}\n\nТекущий: {user_sessions[user_id].get('current_file', 'main.py')}")
                
                elif text == "/undo" or text == "🗑 Удалить последний":
                    parts = user_sessions[user_id].get("parts", [])
                    if not parts:
                        send_message(chat_id, "📭 Нет частей для удаления")
                    else:
                        parts.pop()
                        user_sessions[user_id]["parts"] = parts
                        send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
                
                elif text == "/history" or text == "📜 ИСТОРИЯ":
                    history = user_sessions[user_id].get("history", [])
                    if not history:
                        send_message(chat_id, "📭 История пуста")
                    else:
                        msg = "📜 *История:*\n\n"
                        for i, h in enumerate(history[-10:], 1):
                            msg += f"{i}. {h.get('time', '')}\n"
                        send_message(chat_id, msg)
                
                elif user_sessions[user_id].get("waiting_for") == "generate":
                    user_sessions[user_id]["waiting_for"] = None
                    send_message(chat_id, "✨ Генерация кода... (10-15 сек)")
                    generated = generate_code(text)
                    if generated:
                        user_sessions[user_id]["code"] = generated
                        send_message(chat_id, f"✅ Сгенерировано:\n```python\n{generated[:2000]}\n```")
                    else:
                        send_message(chat_id, "❌ Ошибка генерации")
                
                else:
                    send_message(chat_id, f"❓ Неизвестная команда. Используй /help")
            
            # Если это НЕ команда и НЕ кнопка — сохраняем как код
            else:
                parts = user_sessions[user_id].get("parts", [])
                parts.append(text)
                user_sessions[user_id]["parts"] = parts
                user_sessions[user_id]["code"] = text if not user_sessions[user_id]["code"] else user_sessions[user_id]["code"] + "\n\n" + text
                user_sessions[user_id]["history"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "action": f"Добавлена часть {len(parts)}"
                })
                send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n🧠 /smart_merge — склеить части\n🗑 /undo — удалить последнюю")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return jsonify({"ok": False}), 500

@app.route("/")
def health():
    return "Bot is running!", 200

if __name__ == "__main__":
    time.sleep(2)
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)
