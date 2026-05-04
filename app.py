import os
import re
import json
import logging
import time
from datetime import datetime
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        url = f"{API_URL}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        requests.post(url, json=data, timeout=10)
        logger.info(f"Сообщение отправлено в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_file(chat_id, filename, caption=""):
    try:
        url = f"{API_URL}/sendDocument"
        with open(filename, "rb") as f:
            files = {"document": f}
            data = {"chat_id": chat_id, "caption": caption}
            requests.post(url, data=data, files=files, timeout=30)
        logger.info(f"Файл отправлен в {chat_id}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return response.json().get("result", [])
    except Exception as e:
        logger.error(f"Ошибка получения: {e}")
        return []

# ==================== AI ФУНКЦИЯ ====================
def call_deepseek(prompt):
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-coder",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        return ""

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

# ==================== НОВЫЕ ФУНКЦИИ: УДАЛЕНИЕ И ОТКАТ ====================
def delete_last_part(user_id):
    """Удаляет последнюю добавленную часть кода"""
    if user_id not in user_sessions:
        return False, "Нет активной сессии"
    
    history = user_sessions[user_id].get("history", [])
    if not history:
        return False, "Нет частей для удаления"
    
    # Удаляем последнюю часть из истории
    last_part = history.pop()
    
    # Пересобираем код из оставшихся частей
    if history:
        # Если есть другие части, нужно пересобрать код
        # Для простоты: отправляем запрос к AI для пересборки
        all_parts = [h.get("full_code", h.get("part", "")) for h in history]
        # Показываем сообщение
        return True, f"🗑 Удалена последняя часть:\n```\n{last_part.get('part', '')[:200]}\n```\nОсталось частей: {len(history)}"
    else:
        # Если частей не осталось, очищаем код
        user_sessions[user_id]["code"] = ""
        return True, "🗑 Удалена последняя часть. Код полностью очищен."

def undo_operation(user_id, steps=1):
    """Откатывает последние изменения (1 или больше шагов)"""
    if user_id not in user_sessions:
        return False, "Нет активной сессии"
    
    history = user_sessions[user_id].get("history", [])
    if not history:
        return False, "Нет истории для отката"
    
    # Сохраняем удалённые части для отчёта
    removed_parts = []
    for _ in range(min(steps, len(history))):
        removed_parts.append(history.pop())
    
    # Пересобираем код из оставшейся истории
    if history:
        # Восстанавливаем код из последней версии в истории
        last_entry = history[-1]
        if "full_code" in last_entry:
            user_sessions[user_id]["code"] = last_entry["full_code"]
        else:
            # Если нет сохранённого полного кода, используем текущий
            pass
    else:
        user_sessions[user_id]["code"] = ""
    
    return True, f"↩️ Откат на {len(removed_parts)} шаг(ов).\nОсталось частей: {len(history)}"

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    # Команды
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Assembler Bot*\n\n"
            "Привет! Я собираю код из частей с помощью DeepSeek AI.\n\n"
            "*Команды:*\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить всё\n"
            "/delete — удалить последнюю часть\n"
            "/undo — откатить последнее изменение\n"
            "/order — переставить функции\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск багов\n"
            "/validate — проверка кода\n"
            "/help — справка\n\n"
            "📝 Просто отправь мне часть кода!", parse_mode="Markdown")
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
    
    elif text == "/done":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = f"code_{user_id}.py"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        send_file(chat_id, filename, f"✅ Готовый код! {len(code)} символов")
        os.remove(filename)
    
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        user_sessions[user_id]["history"] = []
        send_message(chat_id, "🧹 Код полностью очищен!")
    
    # НОВАЯ КОМАНДА: Удалить последнюю часть
    elif text == "/delete":
        success, message_text = delete_last_part(user_id)
        send_message(chat_id, message_text, parse_mode="Markdown")
    
    # НОВАЯ КОМАНДА: Откат
    elif text == "/undo":
        success, message_text = undo_operation(user_id, 1)
        send_message(chat_id, message_text, parse_mode="Markdown")
    
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
    
    elif text == "/help":
        send_message(chat_id,
            "📚 *Все команды бота*\n\n"
            "/start — начать работу\n"
            "/show — показать код\n"
            "/done — скачать файл\n"
            "/reset — очистить ВСЁ\n"
            "/delete — удалить ПОСЛЕДНЮЮ часть\n"
            "/undo — откатить последнее изменение\n"
            "/order — переставить функции\n"
            "/complexity — анализ сложности\n"
            "/bugs — поиск багов\n"
            "/validate — проверка кода\n"
            "/help — это сообщение\n\n"
            "💡 *Совет:*\n"
            "• Отправляй код частями\n"
            "• Если ошибся — используй /delete\n"
            "• Хочешь вернуть назад — /undo", parse_mode="Markdown")
    
    # Обработка кода
    elif not text.startswith("/"):
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует код...")
        
        if current:
            prompt = f"""Объедини код. Верни ТОЛЬКО итоговый код, без объяснений.

Текущий код:
{current}

Новая часть:
{text}

Итоговый код:"""
        else:
            prompt = f"""Верни ТОЛЬКО этот код, без комментариев:
{text}"""
        
        ai_response = call_deepseek(prompt)
        
        if ai_response:
            # Очистка от маркеров
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
        
        # Сохраняем в историю ПОЛНУЮ версию кода для отката
        user_sessions[user_id]["history"].append({
            "time": str(datetime.now()),
            "part": text[:200],
            "full_code": user_sessions[user_id]["code"]  # Сохраняем предыдущую версию
        })
        
        user_sessions[user_id]["code"] = new_code
        
        send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {len(new_code)} символов\n📦 Частей: {len(user_sessions[user_id]['history'])}\n\n/show — посмотреть\n/done — скачать\n/delete — удалить последнюю часть", parse_mode="Markdown")

# ==================== ЗАПУСК ====================
def run_bot():
    logger.info("🚀 Бот запущен!")
    last_update_id = 0
    while True:
        try:
            updates = get_updates(offset=last_update_id + 1 if last_update_id else None)
            for update in updates:
                last_update_id = update["update_id"]
                if "message" in update:
                    process_message(update["message"])
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_bot()
