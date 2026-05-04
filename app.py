import os
import re
import json
import logging
import time
import ast
from datetime import datetime
from typing import List, Dict
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_file(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_button(chat_id, text, button_text, callback_data):
    """Отправляет сообщение с кнопкой"""
    reply_markup = {
        "inline_keyboard": [[{
            "text": button_text,
            "callback_data": callback_data
        }]]
    }
    send_message(chat_id, text, parse_mode="Markdown", reply_markup=json.dumps(reply_markup))

def edit_message(chat_id, message_id, text, reply_markup=None):
    """Редактирует сообщение"""
    try:
        data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/editMessageText", json=data, timeout=10)
    except:
        pass

def answer_callback(callback_id, text="", show_alert=False):
    """Отвечает на callback запрос"""
    try:
        data = {"callback_query_id": callback_id, "text": text, "show_alert": show_alert}
        requests.post(f"{API_URL}/answerCallbackQuery", json=data, timeout=10)
    except:
        pass

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        return requests.get(f"{API_URL}/getUpdates", params=params, timeout=35).json().get("result", [])
    except:
        return []

# ==================== AI ФУНКЦИЯ ====================
def call_deepseek(prompt):
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-coder", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 2000},
            timeout=30
        )
        return response.json()["choices"][0]["message"]["content"]
    except:
        return ""

# ==================== СУПЕР-АНАЛИЗ ОШИБОК ====================
class SuperBugHunter:
    def __init__(self):
        self.bugs = []
        self.warnings = []
    
    def hunt_all(self, code: str) -> Dict:
        self.bugs = []
        self.warnings = []
        
        # Синтаксис
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            self.bugs.append({"severity": "CRITICAL", "message": f"Синтаксис: {e.msg}", "line": e.lineno})
        
        # Паттерны ошибок
        patterns = [
            (r'/\s*0\b', 'CRITICAL', 'Деление на ноль'),
            (r'eval\s*\(', 'HIGH', 'Использование eval()'),
            (r'except\s*:', 'MEDIUM', 'Голый except'),
            (r'password\s*=\s*[\'"]', 'HIGH', 'Хардкод пароля'),
            (r'print\(', 'LOW', 'Отладочный print()'),
        ]
        
        for pattern, severity, msg in patterns:
            if re.search(pattern, code):
                self.bugs.append({"severity": severity, "message": msg})
        
        return {
            "bugs": self.bugs,
            "warnings": self.warnings,
            "total_bugs": len(self.bugs),
            "critical_count": sum(1 for b in self.bugs if b.get("severity") == "CRITICAL"),
            "high_count": sum(1 for b in self.bugs if b.get("severity") == "HIGH"),
            "medium_count": sum(1 for b in self.bugs if b.get("severity") == "MEDIUM"),
            "low_count": sum(1 for b in self.bugs if b.get("severity") == "LOW")
        }
    
    def generate_report(self, result: Dict) -> str:
        if result["total_bugs"] == 0:
            return "🎉 **ИДЕАЛЬНЫЙ КОД!** Ошибок не найдено."
        
        report = "🔍 **РЕЗУЛЬТАТЫ СКАНА**\n\n"
        report += f"🔴 CRITICAL: {result['critical_count']}\n"
        report += f"🟠 HIGH: {result['high_count']}\n"
        report += f"🟡 MEDIUM: {result['medium_count']}\n"
        report += f"🔵 LOW: {result['low_count']}\n\n"
        
        for b in result["bugs"][:5]:
            report += f"• {b['message']} `[{b['severity']}]`\n"
        
        return report

hunter = SuperBugHunter()

# ==================== ФУНКЦИИ АНАЛИЗА ====================
def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "🟢 Низкая"
    elif complexity < 20:
        rating = "🟡 Средняя"
    else:
        rating = "🔴 Высокая"
    return f"📊 *Анализ сложности*\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Сложность: {complexity:.1f}\n• Оценка: {rating}"

def find_bugs(code):
    bugs = []
    patterns = [
        (r'/\s*0\b', 'Деление на ноль', 'CRITICAL'),
        (r'eval\s*\(', 'Использование eval()', 'HIGH'),
        (r'except\s*:', 'Голый except', 'MEDIUM'),
        (r'password\s*=\s*[\'"]', 'Хардкод пароля', 'CRITICAL'),
    ]
    for pattern, msg, severity in patterns:
        if re.search(pattern, code):
            bugs.append(f"• {msg} `[{severity}]`")
    if not bugs:
        return "✅ Багов не найдено!"
    return "🐛 *Найденные проблемы:*\n" + "\n".join(bugs)

def validate_code(code):
    try:
        compile(code, '<string>', 'exec')
        return "✅ Код в идеальном состоянии!"
    except SyntaxError as e:
        return f"⚠️ *Ошибка:* {e.msg}\n📍 Строка: {e.lineno}"

def reorder_code(code):
    lines = code.split('\n')
    imports = []
    functions = []
    other = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            imports.append(line)
        elif line.strip().startswith(('def ', 'async def ')):
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

def auto_fix_with_ai(code: str, bugs: List[Dict]) -> str:
    if not bugs:
        return code
    
    bugs_text = "\n".join([f"- {b.get('message', '')}" for b in bugs[:5]])
    prompt = f"""Исправь ошибки в коде. Верни ТОЛЬКО исправленный код.

Ошибки:
{bugs_text}

Код:
{code}

Исправленный код:"""
    
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-coder", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 4000},
            timeout=30
        )
        fixed = response.json()["choices"][0]["message"]["content"]
        if fixed.startswith("```"):
            lines = fixed.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            fixed = '\n'.join(lines)
        return fixed
    except:
        return code

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": [], "last_message_id": None}
    
    # Команды
    if text == "/start":
        # Отправляем сообщение с КНОПКОЙ СКАЧАТЬ
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📥 СКАЧАТЬ КОД", "callback_data": "download"}],
                [{"text": "🔍 АНАЛИЗ", "callback_data": "analyze"}, {"text": "🐛 БАГИ", "callback_data": "bugs"}],
                [{"text": "📊 СЛОЖНОСТЬ", "callback_data": "complexity"}, {"text": "🔄 ПОРЯДОК", "callback_data": "order"}]
            ]
        }
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\n"
            "Привет! Я собираю код из частей с помощью DeepSeek AI.\n\n"
            "📝 *Как использовать:*\n"
            "1. Отправь мне часть кода\n"
            "2. Бот автоматически соберёт его\n"
            "3. Нажми кнопку СКАЧАТЬ\n\n"
            "*Команды:*\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить\n"
            "/super_scan — полный анализ\n"
            "/auto_fix — исправить ошибки\n"
            "/help — справка", 
            parse_mode="Markdown", 
            reply_markup=json.dumps(reply_markup))
    
    elif text == "/help":
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📥 СКАЧАТЬ", "callback_data": "download"}],
                [{"text": "🔍 АНАЛИЗ", "callback_data": "analyze"}, {"text": "🐛 БАГИ", "callback_data": "bugs"}]
            ]
        }
        send_message(chat_id,
            "📚 *Команды бота*\n\n"
            "/start — начать\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить\n"
            "/order — переставить функции\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск багов\n"
            "/validate — проверка\n"
            "/super_scan — полный анализ\n"
            "/auto_fix — исправить ошибки\n"
            "/help — справка\n\n"
            "👇 Нажми кнопку СКАЧАТЬ", 
            parse_mode="Markdown",
            reply_markup=json.dumps(reply_markup))
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            reply_markup = {
                "inline_keyboard": [[{"text": "📥 СКАЧАТЬ", "callback_data": "download"}]]
            }
            send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown", reply_markup=json.dumps(reply_markup))
    
    elif text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для скачивания")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        send_file(chat_id, filename, f"✅ Готовый код! {len(code)} символов")
        os.remove(filename)
    
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        user_sessions[user_id]["history"] = []
        send_message(chat_id, "🧹 Код очищен!")
    
    elif text == "/order":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            user_sessions[user_id]["code"] = reorder_code(code)
            send_message(chat_id, "🔄 Код переставлен!")
    
    elif text == "/complexity":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            send_message(chat_id, analyze_complexity(code), parse_mode="Markdown")
    
    elif text == "/bugs":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            send_message(chat_id, find_bugs(code), parse_mode="Markdown")
    
    elif text == "/validate":
        code = user_sessions[user_id]["code"]
        if not code:
            send_message(chat_id, "📭 Нет кода")
        else:
            send_message(chat_id, validate_code(code), parse_mode="Markdown")
    
    elif text == "/super_scan":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для сканирования")
            return
        
        send_message(chat_id, "🔬 Запуск полного анализа...")
        result = hunter.hunt_all(code)
        user_sessions[user_id]["last_scan"] = result
        report = hunter.generate_report(result)
        
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🔧 АВТОИСПРАВЛЕНИЕ", "callback_data": "auto_fix"}],
                [{"text": "📥 СКАЧАТЬ", "callback_data": "download"}]
            ]
        }
        send_message(chat_id, report, parse_mode="Markdown", reply_markup=json.dumps(reply_markup))
    
    elif text == "/auto_fix":
        code = user_sessions[user_id]["code"]
        last_scan = user_sessions[user_id].get("last_scan")
        
        if not last_scan or last_scan.get("total_bugs", 0) == 0:
            send_message(chat_id, "📭 Сначала запустите `/super_scan`")
            return
        
        send_message(chat_id, "🔧 Исправляю ошибки...")
        fixed_code = auto_fix_with_ai(code, last_scan.get("bugs", []))
        user_sessions[user_id]["code"] = fixed_code
        
        reply_markup = {
            "inline_keyboard": [[{"text": "📥 СКАЧАТЬ ИСПРАВЛЕННЫЙ КОД", "callback_data": "download"}]]
        }
        send_message(chat_id, "✅ Ошибки исправлены! Нажми кнопку СКАЧАТЬ", parse_mode="Markdown", reply_markup=json.dumps(reply_markup))
    
    # Обработка кода
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует код...")
        
        if current:
            prompt = f"""Объедини код. Верни ТОЛЬКО итоговый код.

Текущий код:
{current}

Новая часть:
{text}

Итоговый код:"""
        else:
            prompt = f"""Верни ТОЛЬКО этот код:
{text}"""
        
        ai_response = call_deepseek(prompt)
        
        if ai_response:
            ai_response = ai_response.strip()
            if ai_response.startswith("```"):
                lines = ai_response.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                ai_response = '\n'.join(lines)
            new_code = ai_response
        else:
            new_code = current + "\n\n" + text if current else text
        
        user_sessions[user_id]["history"].append({
            "time": str(datetime.now()),
            "part": text[:200],
            "full_code": user_sessions[user_id]["code"]
        })
        user_sessions[user_id]["code"] = new_code
        
        # Кнопка скачать после обновления кода
        reply_markup = {
            "inline_keyboard": [[{"text": "📥 СКАЧАТЬ КОД", "callback_data": "download"}]]
        }
        send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {len(new_code)} символов\n\n👇 Нажми кнопку для скачивания", parse_mode="Markdown", reply_markup=json.dumps(reply_markup))

# ==================== ОБРАБОТКА НАЖАТИЙ КНОПОК ====================
def process_callback(callback):
    callback_id = callback["id"]
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]
    user_id = callback["from"]["id"]
    data = callback.get("data", "")
    
    if data == "download":
        code = user_sessions.get(user_id, {}).get("code", "")
        if not code.strip():
            answer_callback(callback_id, "❌ Нет кода для скачивания!", True)
            return
        
        filename = f"code_{user_id}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        send_file(chat_id, filename, f"✅ Готовый код! {len(code)} символов")
        os.remove(filename)
        answer_callback(callback_id, "✅ Файл отправлен!")
    
    elif data == "analyze":
        code = user_sessions.get(user_id, {}).get("code", "")
        if not code.strip():
            answer_callback(callback_id, "❌ Нет кода для анализа!", True)
            return
        
        result = hunter.hunt_all(code)
        report = hunter.generate_report(result)
        edit_message(chat_id, message_id, report)
        answer_callback(callback_id, "✅ Анализ завершён!")
    
    elif data == "bugs":
        code = user_sessions.get(user_id, {}).get("code", "")
        if not code.strip():
            answer_callback(callback_id, "❌ Нет кода!", True)
            return
        
        report = find_bugs(code)
        edit_message(chat_id, message_id, report)
        answer_callback(callback_id, "✅ Поиск багов завершён!")
    
    elif data == "complexity":
        code = user_sessions.get(user_id, {}).get("code", "")
        if not code.strip():
            answer_callback(callback_id, "❌ Нет кода!", True)
            return
        
        report = analyze_complexity(code)
        edit_message(chat_id, message_id, report)
        answer_callback(callback_id, "✅ Анализ сложности завершён!")
    
    elif data == "order":
        code = user_sessions.get(user_id, {}).get("code", "")
        if not code.strip():
            answer_callback(callback_id, "❌ Нет кода!", True)
            return
        
        user_sessions[user_id]["code"] = reorder_code(code)
        edit_message(chat_id, message_id, "🔄 Код переставлен!\n\n/show для просмотра")
        answer_callback(callback_id, "✅ Порядок изменён!")
    
    elif data == "auto_fix":
        code = user_sessions.get(user_id, {}).get("code", "")
        last_scan = user_sessions.get(user_id, {}).get("last_scan")
        
        if not code.strip():
            answer_callback(callback_id, "❌ Нет кода!", True)
            return
        
        send_message(chat_id, "🔧 Исправляю ошибки...")
        fixed_code = auto_fix_with_ai(code, last_scan.get("bugs", []) if last_scan else [])
        user_sessions[user_id]["code"] = fixed_code
        
        reply_markup = {
            "inline_keyboard": [[{"text": "📥 СКАЧАТЬ", "callback_data": "download"}]]
        }
        send_message(chat_id, "✅ Ошибки исправлены!", reply_markup=json.dumps(reply_markup))
        answer_callback(callback_id, "✅ Исправление завершено!")

# ==================== ЗАПУСК ====================
def run_bot():
    logger.info("🚀 Бот с КНОПКОЙ СКАЧАТЬ запущен!")
    last_update_id = 0
    while True:
        try:
            updates = get_updates(offset=last_update_id + 1 if last_update_id else None)
            for update in updates:
                last_update_id = update["update_id"]
                if "message" in update:
                    process_message(update["message"])
                elif "callback_query" in update:
                    process_callback(update["callback_query"])
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_bot()
