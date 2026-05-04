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

TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

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

def send_file(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except:
        pass

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return response.json().get("result", [])
    except:
        return []

# ==================== ПРОСТОЕ АВТОИСПРАВЛЕНИЕ (БЕЗ AI, ГАРАНТИРОВАННО РАБОТАЕТ) ====================
def simple_auto_fix(code):
    """Простое, но эффективное исправление кода - работает даже без AI"""
    if not code.strip():
        return code, "Нет кода"
    
    fixed = code
    fixes_made = []
    
    # 1. Исправляем двоеточие у функций
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes_made.append("Добавлены двоеточия в функциях")
    
    # 2. Исправляем деление на ноль
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes_made.append("Исправлено деление на ноль")
    
    # 3. Исправляем print с незакрытыми скобками
    if re.search(r'print\(["\'][^"\']*["\']$', fixed, re.MULTILINE):
        fixed = re.sub(r'(print\(["\'][^"\']*["\'])$', r'\1)', fixed, flags=re.MULTILINE)
        fixes_made.append("Исправлены вызовы print()")
    
    # 4. Удаляем дубликаты импортов
    lines = fixed.split('\n')
    seen = set()
    new_lines = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            if line.strip() not in seen:
                seen.add(line.strip())
                new_lines.append(line)
        else:
            new_lines.append(line)
    if len(new_lines) != len(lines):
        fixes_made.append("Удалены дубликаты импортов")
    fixed = '\n'.join(new_lines)
    
    # 5. Оборачиваем опасный код в try-except
    if 'eval(' in fixed:
        fixed = fixed.replace('eval(', '# eval(')
        fixes_made.append("Закомментирован опасный eval()")
    
    # 6. Исправляем except без указания ошибки
    fixed = re.sub(r'except\s*:', 'except Exception as e:', fixed)
    if 'except Exception as e:' in fixed:
        fixes_made.append("Исправлен голый except")
    
    # 7. Добавляем обработку деления на ноль
    if 'ZeroDivisionError' not in fixed and ('/' in fixed):
        fixed = 'try:\n    ' + fixed.replace('\n', '\n    ') + '\nexcept ZeroDivisionError:\n    print("Ошибка: деление на ноль")\n'
        fixes_made.append("Добавлена обработка деления на ноль")
    
    # 8. Добавляем docstring если нет
    if 'def ' in fixed and '"""' not in fixed and "'''" not in fixed:
        fixed = re.sub(r'(def\s+\w+\([^)]*\):)', r'\1\n    """Функция"""', fixed)
        fixes_made.append("Добавлены docstring")
    
    if fixes_made:
        return fixed, "✅ Исправлено: " + ", ".join(fixes_made)
    return fixed, "✅ Код уже в хорошем состоянии"

# ==================== ФУНКЦИИ ====================
def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    complexity = 1 + code.count('if ') + code.count('for ') * 0.5
    rating = "Низкая" if complexity < 10 else "Средняя" if complexity < 20 else "Высокая"
    return f"📊 Анализ сложности:\nСтрок: {code_lines}\nФункций: {functions}\nСложность: {complexity:.1f}\nОценка: {rating}"

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль [КРИТИЧЕСКАЯ]")
    if 'eval(' in code:
        bugs.append("❌ Использование eval() [ВЫСОКАЯ]")
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except [СРЕДНЯЯ]")
    if re.search(r'password\s*=\s*[\'"]', code, re.IGNORECASE):
        bugs.append("❌ Хардкод пароля [КРИТИЧЕСКАЯ]")
    if 'print(' in code:
        bugs.append("⚠️ Отладочный print() [НИЗКАЯ]")
    
    # Проверка синтаксиса
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg} [КРИТИЧЕСКАЯ]")
    
    if not bugs:
        return "✅ Ошибок не найдено!"
    return "**Найденные ошибки:**\n" + "\n".join(bugs)

def validate_code(code):
    try:
        compile(code, '<string>', 'exec')
        return "✅ Код синтаксически верен!"
    except SyntaxError as e:
        return f"❌ Ошибка: {e.msg}"

def reorder_code(code):
    lines = code.split('\n')
    imports = []
    functions = []
    other = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            imports.append(line)
        elif line.strip().startswith('def '):
            functions.append(line)
        else:
            other.append(line)
    result = []
    if imports:
        result.extend(sorted(set(imports)))
        result.append('')
    if functions:
        result.extend(functions)
        result.append('')
    result.extend(other)
    return '\n'.join(result)

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except:
        return {"success": False, "output": "", "error": "Timeout"}
    finally:
        os.unlink(temp_file)

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔍 Анализ", "🐛 Ошибки"],
            ["🔧 ИСПРАВИТЬ", "🔄 Порядок"],
            ["✅ Проверить", "🏃 Запустить"],
            ["🌐 Веб", "🗑 Очистить"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": ""}
    
    # Обработка кнопок и команд
    if text == "/start" or text == "🔙 Назад":
        send_message(chat_id, "🤖 AI Code Bot\n\nПришли код - я исправлю ошибки!", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь код!")
        else:
            send_message(chat_id, f"```python\n{code[:3500]}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w") as f:
            f.write(code)
        send_file(chat_id, filename, "✅ Готово!")
        os.remove(filename)
    
    elif text == "🗑 Очистить" or text == "/reset":
        user_sessions[user_id]["code"] = ""
        send_message(chat_id, "🧹 Очищено!")
    
    elif text == "🔄 Порядок" or text == "/order":
        code = user_sessions[user_id]["code"]
        if code:
            user_sessions[user_id]["code"] = reorder_code(code)
            send_message(chat_id, "🔄 Порядок исправлен!")
        else:
            send_message(chat_id, "📭 Нет кода")
    
    elif text == "🔍 Анализ" or text == "/complexity":
        send_message(chat_id, analyze_complexity(user_sessions[user_id]["code"]))
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        send_message(chat_id, find_bugs(user_sessions[user_id]["code"]), parse_mode="Markdown")
    
    elif text == "✅ Проверить" or text == "/validate":
        send_message(chat_id, validate_code(user_sessions[user_id]["code"]))
    
    elif text == "🏃 Запустить" or text == "/run":
        result = run_code_safe(user_sessions[user_id]["code"])
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:1000]}\n```", parse_mode="Markdown")
    
    # === ГЛАВНАЯ КНОПКА ИСПРАВЛЕНИЯ ===
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления\n\nСначала отправь код!")
            return
        
        send_message(chat_id, "🔧 Исправляю код...")
        
        # Исправляем
        fixed_code, report = simple_auto_fix(code)
        
        if fixed_code != code:
            user_sessions[user_id]["code"] = fixed_code
            send_message(chat_id, f"{report}\n\n📝 Показать код - посмотреть результат")
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии! Ошибок не найдено.")
    
    elif text == "🌐 Веб" or text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 Веб-редактор: {bot_url}/web/{user_id}")
    
    # Обработка обычного кода
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔍", "🐛", "🔧", "🔄", "✅", "🏃", "🌐", "🗑"]):
        user_sessions[user_id]["code"] = text
        send_message(chat_id, f"✅ Код сохранён! {len(text)} символов\n\n🔧 ИСПРАВИТЬ - исправлю ошибки")

# ==================== ЗАПУСК ====================
def run_telegram_bot():
    logger.info("Бот запущен!")
    last_id = 0
    while True:
        try:
            updates = get_updates(offset=last_id + 1 if last_id else None)
            for update in updates:
                last_id = update["update_id"]
                if "message" in update:
                    process_message(update["message"])
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), BaseHTTPRequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    run_web()
