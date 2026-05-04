import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
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

# ==================== AI ФУНКЦИИ ====================
def call_deepseek(prompt):
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
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

# ==================== НОВЫЕ ФУНКЦИИ ====================

def voice_to_code(description):
    prompt = f"""Преобразуй это текстовое описание в код на Python. Верни ТОЛЬКО код.

Описание: {description}

Код:"""
    return call_deepseek(prompt)

def convert_to_language(code, from_lang, to_lang):
    prompt = f"""Переведи код с {from_lang} на {to_lang}. Верни ТОЛЬКО код.

Код ({from_lang}):
{code}

Код на {to_lang}:"""
    return call_deepseek(prompt)

def generate_code_in_language(description, language):
    prompt = f"""Напиши код на {language} по описанию. Верни ТОЛЬКО код.

Описание: {description}

Код на {language}:"""
    return call_deepseek(prompt)

def create_pdf_export(code, filename="code.py", user_name="Пользователь"):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'''<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Экспорт кода</title>
<style>
body {{ font-family: monospace; padding: 40px; }}
pre {{ background: #f5f5f5; padding: 20px; overflow-x: auto; }}
.signature {{ margin-top: 40px; padding: 20px; background: #f0f0f0; text-align: center; }}
</style>
</head>
<body>
<h1>Экспорт кода</h1>
<p>Файл: {filename}</p>
<p>Дата: {datetime.now()}</p>
<p>Пользователь: {user_name}</p>
<pre>{escaped_code}</pre>
<div class="signature">
<p>🤖 Создано с помощью AI Code Bot</p>
<p>Подписано: AI Code Bot</p>
</div>
</body>
</html>'''

# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except:
        pass

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

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    rating = "Низкая" if complexity < 10 else "Средняя" if complexity < 20 else "Высокая"
    return f"Строк кода: {code_lines}\nФункций: {functions}\nСложность: {complexity:.1f}\nОценка: {rating}"

def smart_merge(parts):
    if not parts:
        return ""
    prompt = f"""Объедини части кода в один работающий файл. Верни ТОЛЬКО итоговый код.

Части:
{chr(10).join([f"--- ЧАСТЬ {i+1} ---\n{p}" for i, p in enumerate(parts)])}

Итоговый код:"""
    return call_deepseek(prompt)

def fix_code(code):
    prompt = f"""Исправь все ошибки в коде. Верни ТОЛЬКО исправленный код.

Код:
{code}

Исправленный код:"""
    return call_deepseek(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в коде. Верни JSON: {{"bugs": [{{"message": "описание", "severity": "CRITICAL/HIGH/MEDIUM/LOW", "line": номер}}]}}

Код:
{code}"""
    response = call_deepseek(prompt)
    if response:
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group()).get("bugs", [])
        except:
            pass
    return []

def save_code_file(user_id, content):
    filename = f"code_{user_id}_bot.py"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# AI Code Bot\n# {datetime.now()}\n\n{content}")
    return filename

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🧠 УМНАЯ СКЛЕЙКА", "🔧 ИСПРАВИТЬ"],
            ["🐛 НАЙТИ ОШИБКИ", "📊 Анализ"],
            ["✨ ГЕНЕРАЦИЯ", "🎤 ГОЛОСОВОЙ ВВОД"],
            ["🌐 ДРУГИЕ ЯЗЫКИ", "📄 ЭКСПОРТ PDF"],
            ["🗑 Удалить последний", "📜 История"],
            ["🗑 Очистить всё", "❓ Помощь"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def process_message(chat_id, uid, text):
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": [], "parts": [], "language": "python"}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    # Команды
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
            "✨ /generate — создать код по описанию\n"
            "🎤 /voice — голосовой ввод\n"
            "🌐 /languages — другие языки\n"
            "📄 /pdf — экспорт в PDF\n"
            "🧠 /smart_merge — умная склейка\n"
            "🔧 /smart_fix — исправить ошибки\n"
            "🐛 /smart_bugs — найти ошибки\n"
            "📊 /complexity — анализ сложности\n"
            "💾 /done — скачать код\n"
            "📝 /show — показать код\n"
            "🗑 /undo — удалить последнюю часть\n"
            "📜 /history — история\n"
            "🗑 /reset — очистить всё",
            reply_markup=json.dumps(get_keyboard()))
        return
    
    elif text == "/help":
        send_message(chat_id, 
            "📚 *ВСЕ КОМАНДЫ:*\n\n"
            "✨ /generate — генерация кода\n"
            "🎤 /voice — голосовой ввод\n"
            "🌐 /languages — другие языки\n"
            "📄 /pdf — экспорт в PDF\n"
            "🧠 /smart_merge — умная склейка\n"
            "🔧 /smart_fix — исправление\n"
            "🐛 /smart_bugs — поиск ошибок\n"
            "📊 /complexity — анализ\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🗑 /undo — удалить последнее\n"
            "📜 /history — история\n"
            "🗑 /reset — очистить всё")
        return
    
    elif text == "/show":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            if len(code) > 4000:
                for i in range(0, len(code), 4000):
                    send_message(chat_id, f"```python\n{code[i:i+4000]}\n```")
            else:
                send_message(chat_id, f"```python\n{code}\n```")
        return
    
    elif text == "/done":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = save_code_file(uid, code)
        send_document(chat_id, filename, "✅ Готовый код")
        os.remove(filename)
        return
    
    elif text == "/smart_merge":
        parts = user_sessions[uid].get("parts", [])
        if not parts:
            send_message(chat_id, "📭 Нет частей для склейки")
            return
        send_message(chat_id, "🧠 AI склеивает код... (5-10 сек)")
        merged = smart_merge(parts)
        if merged:
            user_sessions[uid]["code"] = merged
            send_message(chat_id, f"✅ *Код склеен!*\nРазмер: {len(merged)} символов\n\n/show — посмотреть")
        else:
            send_message(chat_id, "❌ Ошибка склейки")
        return
    
    elif text == "/smart_fix":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        send_message(chat_id, "🔧 AI исправляет код... (5-10 сек)")
        fixed = fix_code(code)
        if fixed:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, f"✅ *Код исправлен!*\n\n```python\n{fixed[:2000]}\n```")
        else:
            send_message(chat_id, "❌ Ошибка исправления")
        return
    
    elif text == "/smart_bugs":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для проверки")
            return
        send_message(chat_id, "🐛 AI ищет ошибки... (3-5 сек)")
        bugs = find_bugs_ai(code)
        if bugs:
            report = "🔍 *Найденные ошибки:*\n\n"
            for b in bugs[:10]:
                icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(b.get("severity"), "⚪")
                report += f"{icon} **{b.get('severity', 'UNKNOWN')}**"
                if b.get("line"):
                    report += f" (строка {b['line']})"
                report += f"\n   {b.get('message', '')}\n\n"
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ *Ошибок не найдено!*")
        return
    
    elif text == "/complexity":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для анализа")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, f"📊 *Анализ сложности:*\n\n{analysis}")
        return
    
    elif text == "/generate":
        send_message(chat_id, "📝 *Опиши, какой код сгенерировать:*\n\nНапример: 'калькулятор на Python'")
        user_sessions[uid]["waiting_for"] = "generate"
        return
    
    elif text == "/languages":
        send_message(chat_id, 
            "🌐 *Доступные языки:*\n\n"
            "• Python\n• JavaScript\n• Java\n• C++\n• Go\n• Rust\n\n"
            "Команды:\n/set_language python\n/convert_js - в JavaScript\n/convert_java - в Java\n/convert_cpp - в C++")
        return
    
    elif text == "/pdf":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для экспорта")
            return
        html = create_pdf_export(code, "code.py", f"User_{uid}")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html)
            html_file = f.name
        send_document(chat_id, html_file, "📄 Экспорт кода (HTML)")
        os.remove(html_file)
        return
    
    elif text == "/undo":
        parts = user_sessions[uid].get("parts", [])
        if not parts:
            send_message(chat_id, "📭 Нет частей для удаления")
        else:
            parts.pop()
            send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
        return
    
    elif text == "/history":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 История пуста")
        else:
            msg = "📜 *История:*\n\n"
            for i, h in enumerate(history[-15:], 1):
                msg += f"{i}. [{h.get('time', '')[:16]}] {h.get('action', 'Действие')}\n"
            send_message(chat_id, msg)
        return
    
    elif text == "/reset":
        user_sessions[uid] = {"code": "", "history": [], "parts": [], "language": "python"}
        send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
        return
    
    elif text.startswith("/set_language"):
        lang = text.split()[1] if len(text.split()) > 1 else "python"
        user_sessions[uid]["language"] = lang
        send_message(chat_id, f"✅ Язык установлен: {lang}")
        return
    
    elif text.startswith("/convert_"):
        target = text.replace("/convert_", "")
        lang_map = {"js": "JavaScript", "java": "Java", "cpp": "C++", "go": "Go", "rust": "Rust"}
        target_lang = lang_map.get(target, target)
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для преобразования")
            return
        send_message(chat_id, f"🔄 Преобразую в {target_lang}... (10-15 сек)")
        converted = convert_to_language(code, "Python", target_lang)
        if converted:
            user_sessions[uid]["code"] = converted
            send_message(chat_id, f"✅ *Код на {target_lang}:*\n\n```{target_lang}\n{converted[:2000]}\n```")
        else:
            send_message(chat_id, "❌ Ошибка преобразования")
        return
    
    elif user_sessions[uid].get("waiting_for") == "generate":
        user_sessions[uid]["waiting_for"] = None
        lang = user_sessions[uid].get("language", "python")
        send_message(chat_id, f"✨ AI генерирует код на {lang}... (10-15 сек)")
        generated = generate_code_in_language(text, lang)
        if generated:
            user_sessions[uid]["code"] = generated
            send_message(chat_id, f"✅ *Сгенерированный код:*\n\n```{lang}\n{generated[:3000]}\n```")
        else:
            send_message(chat_id, "❌ Ошибка генерации")
        return
    
    # Сохранение частей кода
    elif not text.startswith("/"):
        parts = user_sessions[uid].get("parts", [])
        parts.append(text)
        user_sessions[uid]["parts"] = parts
        send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n🧠 /smart_merge — склеить")
        return

# ==================== ВЕБХУК ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Получено: {data}")
        
        if data and "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            uid = msg["from"]["id"]
            text = msg.get("text", "")
            process_message(chat_id, uid, text)
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return jsonify({"ok": False}), 500

@app.route('/')
def health():
    return "Bot is running!", 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=PORT)
