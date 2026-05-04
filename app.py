import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
processed_update_ids = set()
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ШАБЛОН HTML СТРАНИЦЫ ДЛЯ ЗАПУСКА КОДА ====================
CODE_RUNNER_HTML = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>🚀 Выполнение кода</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: 'Courier New', monospace; padding: 20px; }
        .container { max-width: 100%; margin: 0 auto; }
        .code { background: #2d2d2d; padding: 15px; border-radius: 10px; overflow-x: auto; color: #d4d4d4; font-size: 14px; white-space: pre-wrap; margin-bottom: 20px; }
        .output { background: #0a0a0a; padding: 15px; border-radius: 10px; color: #4ec9b0; font-size: 14px; white-space: pre-wrap; font-family: monospace; }
        .title { color: #569cd6; margin-bottom: 15px; font-size: 20px; }
        .success { color: #4ec9b0; border-left: 3px solid #4ec9b0; padding-left: 15px; }
        .error { color: #f48771; border-left: 3px solid #f48771; padding-left: 15px; }
        .info { color: #9cdcfe; font-size: 12px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="title">🚀 Результат выполнения кода</div>
        <div class="code">{{ code }}</div>
        <div class="output {{ 'success' if success else 'error' }}">
            <strong>{{ '✅ ВЫПОЛНЕНИЕ УСПЕШНО' if success else '❌ ОШИБКА ВЫПОЛНЕНИЯ' }}</strong>
            <pre style="margin-top: 10px; white-space: pre-wrap;">{{ output }}</pre>
        </div>
        <div class="info">💡 Этот результат получен из кода, который ты отправил боту</div>
    </div>
</body>
</html>
'''

# ==================== ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except:
        pass

def send_webapp_button(chat_id, text, webapp_url):
    reply_markup = {"inline_keyboard": [[{"text": text, "web_app": {"url": webapp_url}}]]}
    send_message(chat_id, "🎮 Нажми на кнопку, чтобы открыть результат!", reply_markup=json.dumps(reply_markup))

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return response.json().get("result", [])
    except:
        return []

def run_code_safe(code):
    """Безопасный запуск Python кода"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {
            "success": process.returncode == 0,
            "output": process.stdout if process.stdout else process.stderr,
            "error": process.stderr if not process.stdout else ""
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Превышено время выполнения (5 сек)"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
    finally:
        os.unlink(temp_file)

def auto_fix_code(code):
    if not code.strip():
        return code, "Нет кода"
    fixed = code
    fixes = []
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes.append("двоеточия")
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes.append("деление на ноль")
    if re.search(r'print\(["\'][^"\']*["\']$', fixed, re.MULTILINE):
        fixed = re.sub(r'(print\(["\'][^"\']*["\'])$', r'\1)', fixed, flags=re.MULTILINE)
        fixes.append("print()")
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код уже в хорошем состоянии")

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ Использование eval()")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg}")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

# ==================== FLASK МАРШРУТЫ ====================
@app.route('/')
def health():
    return "🚀 Bot is running!", 200

@app.route('/run/<int:user_id>')
def run_code_page(user_id):
    """Страница с результатом выполнения кода пользователя"""
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        return render_template_string(CODE_RUNNER_HTML, code="# Код пуст", output="Нет кода для выполнения", success=False)
    
    result = run_code_safe(code)
    return render_template_string(CODE_RUNNER_HTML, 
                                  code=code[:2000],
                                  output=result["output"][:5000] if result["output"] else result["error"][:5000],
                                  success=result["success"])

# ==================== ОБРАБОТКА TELEGRAM ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    if text == "/start":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "🔥 *Отправь мне код, и я:*\n"
            "✅ Исправлю ошибки\n"
            "🚀 Запущу его\n"
            "🎮 Открою результат в Telegram\n\n"
            "*Команды:*\n"
            "/run - запустить код\n"
            "/fix - исправить ошибки\n"
            "/bugs - найти ошибки\n"
            "/show - показать код\n"
            "/reset - очистить код\n\n"
            "📝 *Пример кода:*\n"
            "```python\nprint('Hello World!')\nfor i in range(5):\n    print(f'Строка {i}')\n```",
            parse_mode="Markdown")
    
    elif text == "/run" or text == "🚀 ЗАПУСТИТЬ":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для запуска\n\nОтправь код и напиши /run")
            return
        
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, "🚀 Запускаю код...")
        send_webapp_button(chat_id, "🎮 ОТКРЫТЬ РЕЗУЛЬТАТ", f"{bot_url}/run/{user_id}")
    
    elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        fixed_code, report = auto_fix_code(code)
        if fixed_code != code:
            user_sessions[user_id]["code"] = fixed_code
            send_message(chat_id, f"{report}\n\n🚀 Теперь напиши /run чтобы запустить!")
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!\n\n🚀 Напиши /run чтобы запустить")
    
    elif text == "/show" or text == "📝 ПОКАЗАТЬ":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь код!")
        else:
            send_message(chat_id, f"```python\n{code[:3000]}\n```", parse_mode="Markdown")
    
    elif text == "/bugs" or text == "🐛 ОШИБКИ":
        bugs = find_bugs(user_sessions[user_id]["code"])
        send_message(chat_id, "🐛 Результат поиска:\n" + "\n".join(bugs), parse_mode="Markdown")
    
    elif text == "/reset" or text == "🗑 ОЧИСТИТЬ":
        user_sessions[user_id] = {"code": "", "history": []}
        send_message(chat_id, "🧹 Код очищен! Отправь новый код.")
    
    elif text == "/help":
        send_message(chat_id, 
            "📚 *Команды бота:*\n\n"
            "/start - начать\n"
            "/run - запустить код (откроется в Telegram)\n"
            "/fix - исправить ошибки\n"
            "/bugs - найти ошибки\n"
            "/show - показать код\n"
            "/reset - очистить код\n"
            "/help - эта справка\n\n"
            "💡 *Как использовать:*\n"
            "1. Отправь код\n"
            "2. Напиши /fix (если есть ошибки)\n"
            "3. Напиши /run\n"
            "4. Нажми на кнопку - результат откроется в Telegram!",
            parse_mode="Markdown")
    
    elif not text.startswith("/"):
        # Сохраняем код
        current = user_sessions[user_id]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[user_id]["code"] = new_code
        
        # Проверяем на ошибки
        bugs = find_bugs(new_code)
        if len(bugs) == 1 and bugs[0] == "✅ Ошибок не найдено!":
            send_message(chat_id, f"✅ Код сохранён!\n\n🚀 Напиши /run чтобы запустить!")
        else:
            send_message(chat_id, f"✅ Код сохранён!\n\n🐛 Найдены ошибки:\n" + "\n".join(bugs[:3]) + f"\n\n🔧 Напиши /fix чтобы исправить")

# ==================== TELEGRAM БОТ ====================
def run_telegram_bot():
    logger.info("Telegram бот запущен!")
    last_id = 0
    while True:
        try:
            updates = get_updates(offset=last_id + 1 if last_id else None)
            for update in updates:
                update_id = update["update_id"]
                if update_id in processed_update_ids:
                    continue
                processed_update_ids.add(update_id)
                if len(processed_update_ids) > 1000:
                    processed_update_ids.clear()
                
                if "message" in update:
                    process_message(update["message"])
                last_id = update_id
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
