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

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
user_html_pages = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

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

# 1. ГОЛОСОВОЙ ВВОД КОДА (преобразование текста в код)
def voice_to_code(description):
    prompt = f"""Преобразуй это текстовое описание в код на Python. Верни ТОЛЬКО код, без объяснений.

Описание: {description}

Код:"""
    return call_deepseek(prompt)

# 2. ПОДДЕРЖКА ДРУГИХ ЯЗЫКОВ
def convert_to_language(code, from_lang, to_lang):
    prompt = f"""Переведи этот код с {from_lang} на {to_lang}. Верни ТОЛЬКО код.

Исходный код ({from_lang}):
{code}

Код на {to_lang}:"""
    return call_deepseek(prompt)

def generate_code_in_language(description, language):
    prompt = f"""Напиши код на {language} по описанию. Верни ТОЛЬКО код.

Описание: {description}

Код на {language}:"""
    return call_deepseek(prompt)

# 3. ЭКСПОРТ В PDF (создание HTML страницы для печати в PDF)
def create_pdf_export(code, filename="code.py", user_name="Пользователь"):
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('—', '-')
    
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Экспорт кода - AI Code Bot</title>
    <style>
        @media print {{
            body {{ margin: 2cm; }}
            .page-break {{ page-break-before: always; }}
        }}
        body {{ font-family: 'Courier New', monospace; background: white; padding: 40px; }}
        .header {{ text-align: center; margin-bottom: 30px; border-bottom: 2px solid #333; padding-bottom: 20px; }}
        .file-info {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .file-name {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
        .file-meta {{ color: #7f8c8d; font-size: 12px; margin-top: 5px; }}
        .code-block {{ background: #f8f8f8; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }}
        .code-header {{ background: #2c3e50; color: white; padding: 10px 15px; font-family: monospace; }}
        pre {{ margin: 0; padding: 20px; overflow-x: auto; font-size: 12px; line-height: 1.5; }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 10px; color: #999; border-top: 1px solid #eee; padding-top: 20px; }}
        .signature {{ margin-top: 40px; padding: 20px; background: #f0f0f0; border-radius: 8px; text-align: center; }}
        h1 {{ color: #2c3e50; }}
        .badge {{ display: inline-block; background: #3498db; color: white; padding: 2px 8px; border-radius: 4px; font-size: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Code Bot - Экспорт кода</h1>
        <p>Сгенерировано: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}</p>
        <p>Пользователь: {user_name}</p>
    </div>
    
    <div class="file-info">
        <div class="file-name">📄 {filename}</div>
        <div class="file-meta">
            <span class="badge">Язык: Python</span>
            <span class="badge">Символов: {len(code)}</span>
            <span class="badge">Строк: {len(code.splitlines())}</span>
        </div>
    </div>
    
    <div class="code-block">
        <div class="code-header">📝 Код</div>
        <pre><code>{escaped_code}</code></pre>
    </div>
    
    <div class="signature">
        <p>🤖 Создано с помощью <strong>AI Code Bot</strong></p>
        <p>Telegram бот для работы с кодом</p>
        <p style="font-size: 10px; margin-top: 10px;">Лицензия: MIT | Подписано AI Code Bot</p>
    </div>
    
    <div class="footer">
        <p>Этот документ создан автоматически. Для проверки кода используйте бота в Telegram.</p>
    </div>
</body>
</html>'''

def create_multi_file_pdf(files, user_name="Пользователь"):
    """Создаёт PDF с несколькими файлами"""
    files_html = ""
    for filename, code in files.items():
        escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        files_html += f'''
    <div class="file-info" style="page-break-before: avoid;">
        <div class="file-name">📄 {filename}</div>
        <div class="file-meta">
            <span class="badge">Символов: {len(code)}</span>
            <span class="badge">Строк: {len(code.splitlines())}</span>
        </div>
    </div>
    <div class="code-block">
        <div class="code-header">📝 {filename}</div>
        <pre><code>{escaped_code}</code></pre>
    </div>
    <div style="height: 30px;"></div>
'''
    
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Экспорт кода - {len(files)} файлов</title>
    <style>
        @media print {{
            body {{ margin: 2cm; }}
        }}
        body {{ font-family: 'Courier New', monospace; background: white; padding: 40px; }}
        .header {{ text-align: center; margin-bottom: 30px; border-bottom: 2px solid #333; padding-bottom: 20px; }}
        .file-info {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .file-name {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
        .file-meta {{ color: #7f8c8d; font-size: 12px; margin-top: 5px; }}
        .code-block {{ background: #f8f8f8; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; margin-bottom: 20px; }}
        .code-header {{ background: #2c3e50; color: white; padding: 10px 15px; font-family: monospace; }}
        pre {{ margin: 0; padding: 20px; overflow-x: auto; font-size: 12px; line-height: 1.5; }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 10px; color: #999; border-top: 1px solid #eee; padding-top: 20px; }}
        .signature {{ margin-top: 40px; padding: 20px; background: #f0f0f0; border-radius: 8px; text-align: center; }}
        .badge {{ display: inline-block; background: #3498db; color: white; padding: 2px 8px; border-radius: 4px; font-size: 10px; }}
        h1 {{ color: #2c3e50; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 AI Code Bot - Экспорт кода</h1>
        <p>Сгенерировано: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}</p>
        <p>Пользователь: {user_name}</p>
        <p>Всего файлов: {len(files)}</p>
    </div>
    {files_html}
    <div class="signature">
        <p>🤖 Создано с помощью <strong>AI Code Bot</strong></p>
        <p>Telegram бот для работы с кодом</p>
        <p style="font-size: 10px; margin-top: 10px;">Подписано: AI Code Bot | Лицензия: MIT</p>
    </div>
    <div class="footer">
        <p>Этот документ создан автоматически. Для проверки кода используйте бота в Telegram.</p>
    </div>
</body>
</html>'''

# ==================== ОСТАЛЬНЫЕ ФУНКЦИИ ====================
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

def send_voice_message(chat_id, voice_file):
    try:
        with open(voice_file, "rb") as f:
            requests.post(f"{API_URL}/sendVoice", data={"chat_id": chat_id}, files={"voice": f}, timeout=30)
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

def run_code_safe(code, language="python"):
    ext_map = {"python": "py", "javascript": "js", "java": "java", "cpp": "cpp", "go": "go", "rust": "rs"}
    ext = ext_map.get(language, "py")
    with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{ext}', delete=False, encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name
    try:
        if language == "python":
            process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        else:
            process = subprocess.run(["cat", temp_file], capture_output=True, text=True, timeout=2)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Превышено время выполнения"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}
    finally:
        os.unlink(temp_file)

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    classes = code.count('class ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "Низкая"
    elif complexity < 20:
        rating = "Средняя"
    else:
        rating = "Высокая"
    return f"Строк кода: {code_lines}\nФункций: {functions}\nКлассов: {classes}\nСложность: {complexity:.1f}\nОценка: {rating}"

def smart_merge(parts):
    if not parts:
        return ""
    prompt = f"""Объедини эти части кода в один работающий файл. Верни ТОЛЬКО итоговый код.

Части:
{chr(10).join([f"--- ЧАСТЬ {i+1} ---\n{p}" for i, p in enumerate(parts)])}

Итоговый код:"""
    return call_deepseek(prompt)

def fix_code(code):
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.

Код:
{code}

Исправленный код:"""
    return call_deepseek(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Верни JSON: {{"bugs": [{{"message": "...", "severity": "...", "line": номер}}]}}

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
    header = f"# AI Code Bot\n# {datetime.now()}\n\n"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(header + content)
    return filename

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

def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": [], "parts": [], "language": "python"}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    # НОВАЯ ФУНКЦИЯ: ГОЛОСОВОЙ ВВОД
    if text == "/voice" or text == "🎤 ГОЛОСОВОЙ ВВОД":
        send_message(chat_id, "🎤 *Голосовой ввод кода*\n\nОтправь голосовое сообщение с описанием кода, который нужно сгенерировать.\n\nНапример: 'создай функцию для сортировки списка'", parse_mode="Markdown")
        user_sessions[uid]["waiting_for"] = "voice"
        return
    
    # Обработка голосового сообщения
    if "voice" in msg and user_sessions[uid].get("waiting_for") == "voice":
        voice = msg["voice"]
        file_id = voice["file_id"]
        user_sessions[uid]["waiting_for"] = None
        send_message(chat_id, "🎤 Распознаю голосовое сообщение и генерирую код...\n⏳ Обычно 5-10 секунд")
        
        # Здесь должна быть интеграция с распознаванием речи
        # Для демонстрации используем заглушку
        send_message(chat_id, "🎤 *Демо-режим:* Отправь текстовое описание, и я сгенерирую код.\n\nПример: 'напиши калькулятор на Python'", parse_mode="Markdown")
        return
    
    # НОВАЯ ФУНКЦИЯ: ДРУГИЕ ЯЗЫКИ
    if text == "/languages" or text == "🌐 ДРУГИЕ ЯЗЫКИ":
        send_message(chat_id, 
            "🌐 *Поддерживаемые языки программирования:*\n\n"
            "• Python 🐍\n"
            "• JavaScript 📜\n"
            "• Java ☕\n"
            "• C++ ⚡\n"
            "• Go 🚀\n"
            "• Rust 🦀\n\n"
            "*Команды:*\n"
            "/set_language python — выбрать язык\n"
            "/convert_js — преобразовать код в JavaScript\n"
            "/convert_java — преобразовать в Java\n"
            "/convert_cpp — преобразовать в C++\n"
            "/convert_go — преобразовать в Go\n"
            "/convert_rust — преобразовать в Rust",
            parse_mode="Markdown")
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
        
        send_message(chat_id, f"🔄 Преобразую код в {target_lang}...\n⏳ 10-15 секунд")
        converted = convert_to_language(code, "Python", target_lang)
        if converted:
            user_sessions[uid]["code"] = converted
            send_message(chat_id, f"✅ *Код на {target_lang}:*\n\n```{target_lang}\n{converted[:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Не удалось преобразовать код")
        return
    
    # НОВАЯ ФУНКЦИЯ: ЭКСПОРТ PDF
    elif text == "/pdf" or text == "📄 ЭКСПОРТ PDF":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для экспорта в PDF")
            return
        
        send_message(chat_id, "📄 Создаю PDF файл...")
        html_content = create_pdf_export(code, "code.py", f"User_{uid}")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            html_file = f.name
        pdf_file = html_file.replace('.html', '.pdf')
        
        # Конвертируем HTML в PDF с помощью weasyprint (если установлен)
        try:
            from weasyprint import HTML
            HTML(html_file).write_pdf(pdf_file)
            send_document(chat_id, pdf_file, "📄 Экспорт кода в PDF")
            os.remove(pdf_file)
        except:
            # Fallback: отправляем HTML
            send_document(chat_id, html_file, "📄 Экспорт кода (HTML для печати в PDF)")
        os.remove(html_file)
        return
    
    elif text == "/generate" or text == "✨ ГЕНЕРАЦИЯ":
        send_message(chat_id, "📝 *Опиши, какой код нужно сгенерировать:*\n\nНапример:\n- 'калькулятор на Python'\n- 'функция для сортировки списка'", parse_mode="Markdown")
        user_sessions[uid]["waiting_for"] = "generate"
        return
    
    elif user_sessions[uid].get("waiting_for") == "generate":
        user_sessions[uid]["waiting_for"] = None
        lang = user_sessions[uid].get("language", "python")
        send_message(chat_id, f"✨ AI генерирует код на {lang}...\n⏳ 10-15 секунд")
        generated = generate_code_in_language(text, lang)
        if generated:
            user_sessions[uid]["code"] = generated
            send_message(chat_id, f"✅ *Сгенерированный код:*\n\n```{lang}\n{generated[:3000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Не удалось сгенерировать код")
        return
    
    # ОСТАЛЬНЫЕ КОМАНДЫ
    elif text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot - ПОЛНАЯ ВЕРСИЯ*\n\n"
            "✨ /generate — создать код по описанию\n"
            "🎤 /voice — голосовой ввод\n"
            "🌐 /languages — другие языки программирования\n"
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
            parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
        return
    
    elif text == "/help" or text == "❓ Помощь":
        send_message(chat_id, 
            "📚 *ВСЕ КОМАНДЫ БОТА:*\n\n"
            "*🤖 AI ФУНКЦИИ:*\n"
            "✨ /generate — генерация кода\n"
            "🎤 /voice — голосовой ввод\n"
            "🌐 /languages — другие языки\n"
            "📄 /pdf — экспорт в PDF\n\n"
            "*🧠 УМНЫЕ ФУНКЦИИ:*\n"
            "🧠 /smart_merge — умная склейка\n"
            "🔧 /smart_fix — исправление\n"
            "🐛 /smart_bugs — поиск ошибок\n\n"
            "*📊 АНАЛИЗ:*\n"
            "📊 /complexity — сложность\n\n"
            "*📁 ФАЙЛЫ:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🗑 /undo — удалить последнюю часть\n"
            "📜 /history — история\n"
            "🗑 /reset — очистить всё",
            parse_mode="Markdown")
        return
    
    elif text == "/smart_merge" or text == "🧠 УМНАЯ СКЛЕЙКА":
        parts = user_sessions[uid].get("parts", [])
        if not parts:
            send_message(chat_id, "📭 Нет частей для склейки")
            return
        send_message(chat_id, "🧠 AI склеивает код...\n⏳ 5-10 секунд")
        merged = smart_merge(parts)
        if merged:
            user_sessions[uid]["code"] = merged
            send_message(chat_id, f"✅ *Код склеен!*\n📊 Размер: {len(merged)} символов\n\n📝 /show — посмотреть", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибка склейки")
        return
    
    elif text == "/smart_fix" or text == "🔧 ИСПРАВИТЬ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        send_message(chat_id, "🔧 AI исправляет код...\n⏳ 5-10 секунд")
        fixed = fix_code(code)
        if fixed:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, f"✅ *Код исправлен!*\n\n```python\n{fixed[:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибка исправления")
        return
    
    elif text == "/smart_bugs" or text == "🐛 НАЙТИ ОШИБКИ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для проверки")
            return
        send_message(chat_id, "🐛 AI ищет ошибки...\n⏳ 3-5 секунд")
        bugs = find_bugs_ai(code)
        if bugs:
            report = "🔍 *Найденные ошибки:*\n\n"
            for b in bugs[:10]:
                icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}.get(b.get("severity"), "⚪")
                report += f"{icon} **{b.get('severity', 'UNKNOWN')}**"
                if b.get("line"):
                    report += f" (строка {b['line']})"
                report += f"\n   {b.get('message', '')}\n\n"
            send_message(chat_id, report, parse_mode="Markdown")
        else:
            send_message(chat_id, "✅ *Ошибок не найдено!*", parse_mode="Markdown")
        return
    
    elif text == "/complexity" or text == "📊 Анализ":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для анализа")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, f"📊 *Анализ сложности:*\n\n{analysis}", parse_mode="Markdown")
        return
    
    elif text == "/show" or text == "📝 Показать код":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "📭 Код пуст")
        else:
            if len(code) > 4000:
                for i in range(0, len(code), 4000):
                    send_message(chat_id, f"```python\n{code[i:i+4000]}\n```", parse_mode="Markdown")
            else:
                send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
        return
    
    elif text == "/done" or text == "💾 Скачать код":
        code = user_sessions[uid].get("code", "")
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        filename = save_code_file(uid, code)
        send_document(chat_id, filename, "✅ Готовый код")
        os.remove(filename)
        return
    
    elif text == "/undo" or text == "🗑 Удалить последний":
        parts = user_sessions[uid].get("parts", [])
        if not parts:
            send_message(chat_id, "📭 Нет частей для удаления")
        else:
            parts.pop()
            user_sessions[uid]["parts"] = parts
            send_message(chat_id, f"🗑 Удалена последняя часть. Осталось: {len(parts)}")
        return
    
    elif text == "/history" or text == "📜 История":
        history = user_sessions[uid].get("history", [])
        if not history:
            send_message(chat_id, "📭 История пуста")
        else:
            msg = "📜 *История:*\n\n"
            for i, h in enumerate(history[-15:], 1):
                msg += f"{i}. [{h.get('time', '')[:16]}] {h.get('action', 'Действие')}\n"
            send_message(chat_id, msg, parse_mode="Markdown")
        return
    
    elif text == "/reset" or text == "🗑 Очистить всё":
        user_sessions[uid] = {"code": "", "history": [], "parts": [], "language": "python"}
        send_message(chat_id, "🧹 Всё очищено!", reply_markup=json.dumps(get_keyboard()))
        return
    
    # Сохранение частей кода
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🧠", "🔧", "🐛", "📊", "✨", "🎤", "🌐", "📄", "🗑", "📜", "❓"]):
        parts = user_sessions[uid].get("parts", [])
        parts.append(text)
        user_sessions[uid]["parts"] = parts
        send_message(chat_id, f"✅ *Часть {len(parts)} сохранена!*\n\n🧠 /smart_merge — склеить", parse_mode="Markdown")
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

def run_bot():
    global last_update_id
    logger.info("🤖 AI Telegram бот запущен!")
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
                elif "callback_query" in upd:
                    pass
                last_update_id = uid
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
