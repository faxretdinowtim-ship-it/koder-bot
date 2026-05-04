import os
import json
import logging
import time
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

# Простая реализация Telegram API без библиотек
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AI клиент (через requests)
def call_deepseek(prompt: str) -> str:
    """Вызов DeepSeek API"""
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
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        return ""

# Хранилище пользователей
user_sessions = {}

# Базовый URL для API
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    """Отправка сообщения в Telegram"""
    url = f"{API_URL}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

def send_file(chat_id, filename, caption=""):
    """Отправка файла в Telegram"""
    url = f"{API_URL}/sendDocument"
    with open(filename, "rb") as f:
        files = {"document": f}
        data = {"chat_id": chat_id, "caption": caption}
        requests.post(url, data=data, files=files, timeout=30)

def get_updates(offset=None):
    """Получение обновлений от Telegram"""
    url = f"{API_URL}/getUpdates"
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json().get("result", [])
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return []

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def process_message(message):
    """Обработка входящего сообщения"""
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    # Обработка команд
    if text.startswith("/"):
        if text == "/start":
            send_message(chat_id, 
                f"🤖 *AI Code Assembler Bot*\n\n"
                f"Привет! Я собираю код из частей.\n\n"
                f"*Команды:*\n"
                f"/show — показать код\n"
                f"/done — скачать файл\n"
                f"/reset — очистить\n"
                f"/web — веб-редактор\n\n"
                f"📝 Просто отправь мне часть кода!",
                parse_mode="Markdown")
        
        elif text == "/show":
            code = user_sessions[user_id]["code"]
            if not code.strip():
                send_message(chat_id, "📭 Код пуст. Отправь мне часть кода!")
            else:
                send_message(chat_id, f"```python\n{code}\n```", parse_mode="Markdown")
        
        elif text == "/done":
            code = user_sessions[user_id]["code"]
            if not code.strip():
                send_message(chat_id, "❌ Нет кода для сохранения!")
                return
            
            filename = f"code_{user_id}.py"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(code)
            send_file(chat_id, filename, "✅ Готовый код!")
            os.remove(filename)
        
        elif text == "/reset":
            user_sessions[user_id]["code"] = ""
            send_message(chat_id, "🧹 Код очищен!")
        
        elif text == "/web":
            bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
            send_message(chat_id, f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web_editor/{user_id}", parse_mode="Markdown")
        
        else:
            send_message(chat_id, "Неизвестная команда. Используй /start")
        return
    
    # Обработка кода (не команда)
    current = user_sessions[user_id]["code"]
    
    send_message(chat_id, f"🧠 Анализирую и объединяю код...")
    
    # AI склейка
    prompt = f"""Ты эксперт по сборке кода. Объедини текущий код с новой частью.
    Верни ТОЛЬКО итоговый код, без объяснений.
    
    Текущий код:
    {current if current else "(пусто)"}
    
    Новая часть:
    {text}
    
    Итоговый код:"""
    
    ai_response = call_deepseek(prompt)
    
    if ai_response:
        # Очистка ответа от маркеров
        ai_response = ai_response.strip()
        if ai_response.startswith("```"):
            ai_response = ai_response.split("```")[1]
            if ai_response.startswith("python"):
                ai_response = ai_response[6:]
        user_sessions[user_id]["code"] = ai_response
    else:
        # Fallback: простое склеивание
        new_code = current + "\n\n" + text if current else text
        user_sessions[user_id]["code"] = new_code
    
    user_sessions[user_id]["history"].append({
        "time": str(datetime.now()),
        "part": text[:100]
    })
    
    code_len = len(user_sessions[user_id]["code"])
    send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {code_len} символов\n\n/show — посмотреть\n/done — скачать", parse_mode="Markdown")

# ==================== ПОЛЛИНГ БОТА ====================
def run_bot():
    """Запуск polling бота"""
    logger.info("🚀 Бот запущен и слушает сообщения...")
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
            logger.error(f"Ошибка в цикле бота: {e}")
            time.sleep(5)

# ==================== ВЕБ-РЕДАКТОР ====================
WEB_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>🤖 AI Code Editor</title>
    <script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
    <style>
        body { margin: 0; padding: 0; background: #1e1e1e; font-family: monospace; }
        #editor { height: 85vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #1177bb; }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; }
    </style>
</head>
<body>
<div class="toolbar">
    <button onclick="saveCode()">💾 Сохранить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
</div>
<div id="editor"></div>
<div class="status" id="status">Готов к работе</div>
<script>
let editor;
require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: {{ code | tojson }},
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true }
    });
});
async function saveCode() {
    const code = editor.getValue();
    await fetch('/api/save_code', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: {{ user_id }}, code: code})
    });
    document.getElementById('status').innerText = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов к работе', 2000);
}
function downloadCode() {
    const code = editor.getValue();
    const blob = new Blob([code], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'code.py';
    a.click();
    URL.revokeObjectURL(a.href);
}
</script>
</body>
</html>
"""

@app.route('/web_editor/<int:user_id>')
def web_editor(user_id):
    code = user_sessions.get(user_id, {}).get("code", "")
    return render_template_string(WEB_HTML, user_id=user_id, code=code)

@app.route('/api/save_code', methods=['POST'])
def api_save_code():
    data = request.json
    user_id = data.get('user_id')
    code = data.get('code', '')
    if user_id in user_sessions:
        user_sessions[user_id]["code"] = code
    return jsonify({"success": True})

@app.route('/')
def health():
    return "🤖 Bot is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask сервер
    app.run(host='0.0.0.0', port=PORT)
