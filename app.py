import os
import re
import json
import logging
import tempfile
import subprocess
import threading
import time
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

def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
        logger.info(f"Сообщение отправлено в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

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

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ Использование eval()")
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
    rating = "Низкая" if complexity < 10 else "Средняя" if complexity < 20 else "Высокая"
    return f"📊 *Анализ сложности:*\n\nСтрок кода: {code_lines}\nФункций: {functions}\nСложность: {complexity:.1f}\nОценка: {rating}"

def generate_code(description):
    prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код, без объяснений.

Описание: {description}

Код:"""
    return call_deepseek(prompt)

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

def delete_webhook():
    try:
        url = f"{API_URL}/deleteWebhook"
        response = requests.get(url, timeout=10)
        result = response.json()
        logger.info(f"Webhook удалён: {result}")
        return result
    except Exception as e:
        logger.error(f"Ошибка удаления webhook: {e}")
        return None

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ"],
            ["📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ"],
            ["✨ ГЕНЕРАЦИЯ", "🗑 ОЧИСТИТЬ"],
            ["❓ ПОМОЩЬ"]
        ],
        "resize_keyboard": True
    }

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
                user_sessions[user_id] = {"code": "", "history": []}
            
            # Обработка команд
            if text == "/start":
                send_message(chat_id, 
                    "🤖 *AI Code Bot*\n\n"
                    "Привет! Я помогаю с кодом!\n\n"
                    "*Команды:*\n"
                    "📝 /show — показать код\n"
                    "💾 /done — скачать код\n"
                    "🔧 /fix — исправить ошибки\n"
                    "🐛 /bugs — найти ошибки\n"
                    "📊 /complexity — анализ сложности\n"
                    "🏃 /run — выполнить код\n"
                    "✨ /generate — создать код по описанию\n"
                    "🗑 /reset — очистить всё\n"
                    "❓ /help — помощь",
                    reply_markup=json.dumps(get_keyboard()))
            
            elif text == "/help" or text == "❓ ПОМОЩЬ":
                send_message(chat_id, 
                    "📚 *Все команды:*\n\n"
                    "/show — показать код\n"
                    "/done — скачать код\n"
                    "/fix — исправить ошибки\n"
                    "/bugs — найти ошибки\n"
                    "/complexity — анализ сложности\n"
                    "/run — выполнить код\n"
                    "/generate — создать код по описанию\n"
                    "/reset — очистить всё\n"
                    "/help — эта справка")
            
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
                    filename = f"code_{user_id}.py"
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(f"# Создано AI Code Bot\n# {datetime.now()}\n\n{code}")
                    send_document(chat_id, filename, "✅ Готовый код")
                    os.remove(filename)
            
            elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для исправления")
                else:
                    send_message(chat_id, "🔧 AI исправляет код... (5-10 секунд)")
                    fixed = auto_fix_code(code)
                    if fixed:
                        user_sessions[user_id]["code"] = fixed
                        send_message(chat_id, f"✅ *Код исправлен!*\n\n```python\n{fixed[:1500]}\n```")
                    else:
                        send_message(chat_id, "❌ Ошибка при исправлении")
            
            elif text == "/bugs" or text == "🐛 ОШИБКИ":
                code = user_sessions[user_id].get("code", "")
                if not code.strip():
                    send_message(chat_id, "📭 Нет кода для проверки")
                else:
                    bugs = find_bugs(code)
                    send_message(chat_id, "🔍 *Результаты проверки:*\n\n" + "\n".join(bugs))
            
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
                    send_message(chat_id, "🏃 Запуск кода...")
                    result = run_code_safe(code)
                    if result["success"]:
                        output = result["output"][:2000] if result["output"] else "(нет вывода)"
                        send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```")
                    else:
                        error = result["error"][:1500] if result["error"] else "Неизвестная ошибка"
                        send_message(chat_id, f"❌ *Ошибка выполнения:*\n\n```\n{error}\n```")
            
            elif text == "/generate" or text == "✨ ГЕНЕРАЦИЯ":
                send_message(chat_id, "📝 *Опиши, какой код нужно сгенерировать:*\n\nНапример:\n- 'калькулятор на Python'\n- 'функция для сортировки списка'\n- 'бота для Telegram'")
                user_sessions[user_id]["waiting_for"] = "generate"
            
            elif text == "/reset" or text == "🗑 ОЧИСТИТЬ":
                user_sessions[user_id] = {"code": "", "history": []}
                send_message(chat_id, "🧹 Код полностью очищен!", reply_markup=json.dumps(get_keyboard()))
            
            elif user_sessions[user_id].get("waiting_for") == "generate":
                user_sessions[user_id]["waiting_for"] = None
                send_message(chat_id, "✨ AI генерирует код... (10-15 секунд)")
                generated = generate_code(text)
                if generated:
                    user_sessions[user_id]["code"] = generated
                    send_message(chat_id, f"✅ *Сгенерированный код:*\n\n```python\n{generated[:2000]}\n```\n\n/show — показать\n/run — выполнить")
                else:
                    send_message(chat_id, "❌ Не удалось сгенерировать код. Попробуй ещё раз.")
            
            else:
                # Сохраняем код
                user_sessions[user_id]["code"] = text
                send_message(chat_id, f"✅ *Код сохранён!*\n📊 Размер: {len(text)} символов\n\n/show — показать\n/run — выполнить\n/fix — исправить ошибки")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка webhook: {e}")
        return jsonify({"ok": False}), 500

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")

@app.route('/')
def health():
    return "Bot is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    # Удаляем старый webhook и устанавливаем новый
    delete_webhook()
    time.sleep(1)
    set_webhook()
    
    # Запускаем Flask сервер
    app.run(host='0.0.0.0', port=PORT)
