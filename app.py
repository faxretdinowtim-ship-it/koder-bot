import os
import json
import logging
import time
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import requests

# ==================== КОНФИГУРАЦИЯ (твои данные) ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Хранилище пользователей
user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_file(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        return requests.get(f"{API_URL}/getUpdates", params=params, timeout=35).json().get("result", [])
    except:
        return []

# ==================== AI ====================
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

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    if text == "/start":
        send_message(chat_id, "🤖 *AI Code Assembler Bot*\n\nПривет! Я собираю код из частей.\n\n*Команды:*\n/show — показать код\n/done — скачать файл\n/reset — очистить\n/web — веб-редактор\n\n📝 Просто отправь мне часть кода!", parse_mode="Markdown")
    
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
        send_file(chat_id, filename, "✅ Готовый код!")
        os.remove(filename)
    
    elif text == "/reset":
        user_sessions[user_id]["code"] = ""
        send_message(chat_id, "🧹 Код очищен!")
    
    elif text == "/web":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web_editor/{user_id}", parse_mode="Markdown")
    
    elif text.startswith("/"):
        send_message(chat_id, "Неизвестная команда. Используй /start")
    
    else:
        current = user_sessions[user_id]["code"]
        send_message(chat_id, "🧠 AI анализирует...")
        
        # Формируем промпт
        if current:
            prompt = f"""Объедини код. Верни ТОЛЬКО итоговый код.

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
            user_sessions[user_id]["code"] = ai_response
        else:
            new_code = current + "\n\n" + text if current else text
            user_sessions[user_id]["code"] = new_code
        
        user_sessions[user_id]["history"].append({"time": str(datetime.now()), "part": text[:100]})
        send_message(chat_id, f"✅ *Код обновлён!*\n📊 Размер: {len(user_sessions[user_id]['code'])} символов\n\n/show — посмотреть\n/done — скачать", parse_mode="Markdown")

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
    return jsonify({"success": False})

@app.route('/')
def health():
    return "🤖 AI Code Assembler Bot is running!", 200

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT)
