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
from urllib.parse import urlparse
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
        return True
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return False

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
        return True
    except:
        return False

def get_updates():
    global last_update_id
    params = {"timeout": 30}
    if last_update_id:
        params["offset"] = last_update_id + 1
    try:
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except:
        return []

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С КОДОМ ====================
def auto_fix_code(code):
    if not code.strip():
        return code, "Нет кода"
    fixed = code
    fixes = []
    
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes.append("добавлены двоеточия")
    
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes.append("исправлено деление на ноль")
    
    if re.search(r'print\(["\'][^"\']*["\']$', fixed, re.MULTILINE):
        fixed = re.sub(r'(print\(["\'][^"\']*["\'])$', r'\1)', fixed, flags=re.MULTILINE)
        fixes.append("исправлены скобки в print()")
    
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
        fixes.append("удалены дубликаты импортов")
    fixed = '\n'.join(new_lines)
    
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код уже в хорошем состоянии")

def find_bugs(code):
    code = code.replace('—', '-').replace('–', '-')
    bugs = []
    
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль [КРИТИЧЕСКАЯ]")
    if 'eval(' in code:
        bugs.append("❌ Использование eval() [ВЫСОКАЯ]")
    if 'exec(' in code:
        bugs.append("❌ Использование exec() [ВЫСОКАЯ]")
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except [СРЕДНЯЯ]")
    if re.search(r'password\s*=\s*[\'"]', code, re.IGNORECASE):
        bugs.append("❌ Хардкод пароля [КРИТИЧЕСКАЯ]")
    if 'print(' in code:
        bugs.append("⚠️ Отладочный print() [НИЗКАЯ]")
    
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксическая ошибка: {e.msg} [КРИТИЧЕСКАЯ]")
    
    return bugs if bugs else ["✅ Ошибок не найдено!"]

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

def save_code_file(user_id, content):
    filename = f"code_{user_id}_bot.py"
    header = f"# 🤖 Создано AI Code Bot\n# Дата: {datetime.now()}\n\n"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(header + content)
    return filename

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "📊 Анализ"],
            ["🗑 Удалить последний", "📜 История"],
            ["🗑 Очистить всё", "❓ Помощь"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА TELEGRAM ====================
def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": []}
    
    # Обработка команд
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю собирать и исправлять код из частей.\n\n"
            "*Команды:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🔧 /fix — ИСПРАВИТЬ ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "🗑 /undo — удалить последнюю часть\n"
            "📜 /history — история кода\n"
            "🗑 /reset — очистить всё\n\n"
            "💡 *Как использовать:* просто отправляй код частями!",
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
        return
    
    elif text == "/help" or text == "❓ Помощь":
        send_message(chat_id, 
            "📚 *Команды бота:*\n\n"
            "📝 /show — показать текущий код\n"
            "💾 /done — скачать код файлом\n"
            "🔧 /fix — автоматически исправить ошибки\n"
            "🐛 /bugs — найти все ошибки\n"
            "🏃 /run — выполнить код в песочнице\n"
            "📊 /complexity — анализ сложности кода\n"
            "🗑 /undo — удалить последнюю отправленную часть\n"
            "📜 /history — показать историю изменений\n"
            "🗑 /reset — очистить весь код\n\n"
            "💡 *Совет:* Отправляй код частями — я склею их в один файл!",
            parse_mode="Markdown")
        return
    
    elif text == "/show" or text == "📝 Показать код":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст. Отправь мне часть кода!")
        else:
            if len(code) > 4000:
                for i in range(0, len(code), 4000):
                    send_message(chat_id, f"```python\n{code[i:i+4000]}\n```", parse_mode="Markdown")
            else:
                send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
        return
    
    elif text == "/done" or text == "💾 Скачать код":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для скачивания")
            return
        filename = save_code_file(uid, code)
        send_document(chat_id, filename, "✅ Готовый код (с подписью _bot)")
        os.remove(filename)
        return
    
    elif text == "/fix" or text == "🔧 ИСПРАВИТЬ":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        send_message(chat_id, "🔧 Исправляю код...")
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
        return
    
    elif text == "/bugs" or text == "🐛 Ошибки":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для проверки")
            return
        bugs = find_bugs(code)
        send_message(chat_id, "\n".join(bugs), parse_mode="Markdown")
        return
    
    elif text == "/complexity" or text == "📊 Анализ":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для анализа")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, analysis, parse_mode="Markdown")
        return
    
    elif text == "/run" or text == "🏃 Запустить":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для запуска")
            return
        send_message(chat_id, "🏃 Запускаю код...")
        result = run_code_safe(code)
        if result["success"]:
            output = result["output"][:3000] if result["output"] else "(нет вывода)"
            send_message(chat_id, f"✅ *Выполнение успешно!*\n\n```\n{output}\n```", parse_mode="Markdown")
        else:
            error = result["error"][:2000] if result["error"] else "Неизвестная ошибка"
            send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```", parse_mode="Markdown")
        return
    
    elif text == "/undo" or text == "🗑 Удалить последний":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 Нет частей для удаления")
        else:
            last = history.pop()
            user_sessions[uid]["history"] = history
            
            if history:
                full_code = "\n\n".join([h["part"] for h in history])
                user_sessions[uid]["code"] = full_code
                send_message(chat_id, f"🗑 Удалена последняя часть. Осталось частей: {len(history)}")
            else:
                user_sessions[uid]["code"] = ""
                send_message(chat_id, "🗑 Удалена последняя часть. Код полностью очищен.")
        return
    
    elif text == "/history" or text == "📜 История":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 История пуста")
        else:
            msg = "📜 *История кода:*\n\n"
            for i, h in enumerate(history[-15:], 1):
                time_str = h.get('time', '')[:16]
                preview = h.get('part', '')[:50].replace('\n', ' ')
                msg += f"{i}. [{time_str}] `{preview}...`\n"
            msg += f"\n📊 Всего сохранено: {len(history)} частей"
            send_message(chat_id, msg, parse_mode="Markdown")
        return
    
    elif text == "/reset" or text == "🗑 Очистить всё":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "🧹 Код полностью очищен!", reply_markup=json.dumps(get_keyboard()))
        return
    
    # Обработка обычного кода (склеивание частей) - без дублирования
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🏃", "🗑", "📜", "❓"]):
        history = user_sessions[uid].get("history", [])
        history.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "part": text})
        user_sessions[uid]["history"] = history
        
        current = user_sessions[uid].get("code", "")
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        
        send_message(chat_id, 
            f"✅ *Часть кода сохранена!*\n"
            f"📊 Всего символов: {len(new_code)}\n"
            f"📦 Частей получено: {len(history)}\n\n"
            f"📝 /show — посмотреть код\n"
            f"🔧 /fix — исправить ошибки\n"
            f"🏃 /run — выполнить код",
            parse_mode="Markdown")
        return

# ==================== HTTP СЕРВЕР ====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 Telegram бот запущен!")
    while True:
        try:
            updates = get_updates()
            for upd in updates:
                uid = upd["update_id"]
                if uid in processed_ids:
                    continue
                processed_ids.add(uid)
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                if "message" in upd:
                    process_message(upd["message"])
                last_update_id = uid
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
