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

# ==================== ФУНКЦИЯ ОБЪЕДИНЕНИЯ И ИСПРАВЛЕНИЯ ====================
def merge_and_fix(parts):
    if not parts:
        return "", "Нет частей для сборки"
    
    full_code = "\n\n".join(parts)
    fixed_code, report = simple_auto_fix(full_code)
    return fixed_code, report

def simple_auto_fix(code):
    if not code.strip():
        return code, "Нет кода"
    
    fixed = code
    fixes_made = []
    
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes_made.append("добавлены двоеточия")
    
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes_made.append("исправлено деление на ноль")
    
    if re.search(r'print\(["\'][^"\']*["\']$', fixed, re.MULTILINE):
        fixed = re.sub(r'(print\(["\'][^"\']*["\'])$', r'\1)', fixed, flags=re.MULTILINE)
        fixes_made.append("исправлены скобки в print()")
    
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
        fixes_made.append("удалены дубликаты импортов")
    fixed = '\n'.join(new_lines)
    
    if re.search(r'except\s*:', fixed):
        fixed = re.sub(r'except\s*:', 'except Exception as e:', fixed)
        fixes_made.append("исправлен голый except")
    
    if 'def ' in fixed and '"""' not in fixed and "'''" not in fixed:
        fixed = re.sub(r'(def\s+\w+\([^)]*\):)', r'\1\n    """Функция"""', fixed)
        fixes_made.append("добавлены docstring")
    
    if fixes_made:
        return fixed, f"✅ Исправлено: {', '.join(fixes_made)}"
    return fixed, "✅ Код уже в хорошем состоянии!"

def find_errors(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ Использование eval()")
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except")
    if 'print(' in code:
        bugs.append("⚠️ Отладочный print()")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg}")
    return bugs

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать части", "📋 Показать полный код"],
            ["🔧 СОБРАТЬ И ИСПРАВИТЬ", "🐛 Найти ошибки"],
            ["📜 ИСТОРИЯ КОДОВ", "💾 Скачать код"],
            ["🏃 Запустить код", "🗑 Очистить всё"],
            ["🌐 Веб-редактор"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"parts": [], "full_code": "", "history": []}
    
    # Обработка кнопок
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\n"
            "📝 *Как использовать:*\n"
            "1. Отправляй код по частям\n"
            "2. Нажми «🔧 СОБРАТЬ И ИСПРАВИТЬ»\n"
            "3. Получи готовый код!\n\n"
            "📜 *ИСТОРИЯ КОДОВ* — показывает все предыдущие версии",
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "📝 Показать части":
        parts = user_sessions[user_id]["parts"]
        if not parts:
            send_message(chat_id, "📭 Нет сохранённых частей. Отправь код по частям!")
        else:
            result = f"📦 *Сохранено частей: {len(parts)}*\n\n"
            for i, p in enumerate(parts, 1):
                preview = p[:100] + "..." if len(p) > 100 else p
                result += f"*{i}.* ```\n{preview}\n```\n"
            send_message(chat_id, result[:4000], parse_mode="Markdown")
    
    elif text == "📋 Показать полный код":
        full = user_sessions[user_id]["full_code"]
        if not full:
            send_message(chat_id, "📭 Сначала нажми «СОБРАТЬ И ИСПРАВИТЬ»")
        else:
            send_message(chat_id, f"```python\n{full[:3500]}\n```", parse_mode="Markdown")
    
    # === НОВАЯ КНОПКА: ИСТОРИЯ КОДОВ ===
    elif text == "📜 ИСТОРИЯ КОДОВ":
        history = user_sessions[user_id]["history"]
        if not history:
            send_message(chat_id, "📭 История пуста. Сначала собери код через «СОБРАТЬ И ИСПРАВИТЬ»")
        else:
            result = "📜 *ИСТОРИЯ СОБРАННЫХ ВЕРСИЙ КОДА*\n\n"
            for i, entry in enumerate(history[-10:], 1):  # Показываем последние 10
                date = entry.get("date", "unknown")
                code_preview = entry.get("code", "")[:100] + "..." if len(entry.get("code", "")) > 100 else entry.get("code", "")
                result += f"*{i}.* 📅 {date}\n```\n{code_preview}\n```\n\n"
            send_message(chat_id, result[:4000], parse_mode="Markdown")
    
    elif text == "🔧 СОБРАТЬ И ИСПРАВИТЬ":
        parts = user_sessions[user_id]["parts"]
        if not parts:
            send_message(chat_id, "📭 Нет частей для сборки. Отправь код по частям!")
            return
        
        send_message(chat_id, f"🔧 Собираю {len(parts)} частей и исправляю ошибки...")
        
        full_code, report = merge_and_fix(parts)
        user_sessions[user_id]["full_code"] = full_code
        
        # Сохраняем в историю
        if "history" not in user_sessions[user_id]:
            user_sessions[user_id]["history"] = []
        user_sessions[user_id]["history"].append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code": full_code,
            "parts_count": len(parts)
        })
        
        bugs = find_errors(full_code)
        
        response = f"{report}\n\n"
        if bugs:
            response += f"🐛 *Найдено проблем:* {len(bugs)}\n"
            for b in bugs[:3]:
                response += f"{b}\n"
        else:
            response += "✅ Ошибок не найдено!\n"
        
        response += f"\n📋 Показать полный код — посмотреть результат\n💾 Скачать код — сохранить файл"
        send_message(chat_id, response, parse_mode="Markdown")
    
    elif text == "🐛 Найти ошибки":
        full = user_sessions[user_id]["full_code"]
        if not full:
            send_message(chat_id, "📭 Сначала нажми «СОБРАТЬ И ИСПРАВИТЬ»")
            return
        bugs = find_errors(full)
        if bugs:
            send_message(chat_id, "🐛 *Найденные ошибки:*\n" + "\n".join(bugs), parse_mode="Markdown")
        else:
            send_message(chat_id, "✅ Ошибок не найдено! Код хороший.")
    
    elif text == "💾 Скачать код":
        full = user_sessions[user_id]["full_code"]
        if not full:
            send_message(chat_id, "📭 Сначала нажми «СОБРАТЬ И ИСПРАВИТЬ»")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(full)
        send_file(chat_id, filename, f"✅ Код готов! {len(full)} символов")
        os.remove(filename)
    
    elif text == "🗑 Очистить всё":
        user_sessions[user_id] = {"parts": [], "full_code": "", "history": []}
        send_message(chat_id, "🧹 Все части, код и история очищены! Начинай заново.", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "🏃 Запустить код":
        full = user_sessions[user_id]["full_code"]
        if not full:
            send_message(chat_id, "📭 Сначала нажми «СОБРАТЬ И ИСПРАВИТЬ»")
            return
        send_message(chat_id, "🏃 Запускаю код...")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(full)
            temp_file = f.name
        try:
            process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
            if process.returncode == 0:
                output = process.stdout[:2000] if process.stdout else "(нет вывода)"
                send_message(chat_id, f"✅ Выполнено!\n```\n{output}\n```", parse_mode="Markdown")
            else:
                send_message(chat_id, f"❌ Ошибка:\n```\n{process.stderr[:2000]}\n```", parse_mode="Markdown")
        except subprocess.TimeoutExpired:
            send_message(chat_id, "❌ Превышено время выполнения (5 сек)")
        except Exception as e:
            send_message(chat_id, f"❌ Ошибка: {e}")
        finally:
            os.unlink(temp_file)
    
    elif text == "🌐 Веб-редактор":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 Веб-редактор: {bot_url}/web/{user_id}")
    
    # Обработка кода (сохраняем части)
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "📋", "🔧", "🐛", "💾", "🗑", "🏃", "🌐", "📜"]):
        parts = user_sessions[user_id]["parts"]
        parts.append(text)
        user_sessions[user_id]["parts"] = parts
        
        send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n📦 Всего частей: {len(parts)}\n🔧 Нажми «СОБРАТЬ И ИСПРАВИТЬ» когда закончишь!", parse_mode="Markdown")

# ==================== ЗАПУСК ====================
def run_telegram_bot():
    logger.info("🤖 Бот запущен!")
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
