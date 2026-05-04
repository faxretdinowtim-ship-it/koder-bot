import os
import re
import json
import logging
import tempfile
import subprocess
import time
from datetime import datetime
from flask import Flask, request, jsonify
import requests

TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"https://bot-koder.onrender.com/webhook"

def call_deepseek(prompt):
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000
        }
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code != 200:
            return ""
        result = response.json()
        if "choices" not in result or not result["choices"]:
            return ""
        content = result["choices"][0]["message"]["content"]
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content.strip()
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        return ""

def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_document(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except:
        pass

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except:
        return {"success": False, "output": "", "error": "Timeout"}
    finally:
        os.unlink(temp_file)

def auto_fix_code(code):
    prompt = f"""Исправь все ошибки в этом коде. Верни ТОЛЬКО исправленный код.

Код:
{code}

Исправленный код:"""
    return call_deepseek(prompt)

def find_bugs_ai(code):
    prompt = f"""Найди все ошибки в этом коде. Верни JSON: {{"bugs": [{{"message": "...", "severity": "CRITICAL/HIGH/MEDIUM/LOW", "line": 0}}]}}

Код:
{code}"""
    response = call_deepseek(prompt)
    if response:
        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group()).get("bugs", [])
        except:
            pass
    return []

def analyze_complexity(code):
    lines = code.split("\n")
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
    functions = code.count("def ")
    return f"📊 Анализ:\nСтрок кода: {code_lines}\nФункций: {functions}"

def generate_code(description):
    prompt = f"""Напиши код на Python по описанию. Верни ТОЛЬКО код.

Описание: {description}

Код:"""
    return call_deepseek(prompt)

def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 ОШИБКИ"],
            ["📊 АНАЛИЗ", "🏃 ЗАПУСТИТЬ"],
            ["✨ ГЕНЕРАЦИЯ", "🗑 ОЧИСТИТЬ"],
            ["❓ ПОМОЩЬ"]
        ],
        "resize_keyboard": True
    }

def set_webhook():
    try:
        url = f"{API_URL}/setWebhook?url={WEBHOOK_URL}"
        response = requests.get(url, timeout=10)
        result = response.json()
        if result.get("ok"):
            logger.info(f"Webhook установлен: {WEBHOOK_URL}")
        return result
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Получено: {data}")
        
        if data and "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")
            
            if user_id not in user_sessions:
                user_sessions[user_id] = {"code": ""}
            
            if text == "/start":
                send_message(chat_id, "🤖 AI Code Bot\n\nПришли код или используй команды:\n/show — показать\n/run — выполнить\n/fix — исправить\n/generate — создать", reply_markup=json.dumps(get_keyboard()))
            elif text == "/show":
                code = user_sessions[user_id].get("code", "")
                send_message(chat_id, f"```python\n{code[:3000] if code else '# Код пуст'}\n```")
            elif text == "/done":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    filename = f"code_{user_id}.py"
                    with open(filename, "w") as f:
                        f.write(code)
                    send_document(chat_id, filename, "Код")
                    os.remove(filename)
                else:
                    send_message(chat_id, "Нет кода")
            elif text == "/fix":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "Исправляю...")
                    fixed = auto_fix_code(code)
                    if fixed:
                        user_sessions[user_id]["code"] = fixed
                        send_message(chat_id, f"Исправлено:\n```python\n{fixed[:1500]}\n```")
                else:
                    send_message(chat_id, "Нет кода")
            elif text == "/bugs":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    bugs = find_bugs_ai(code)
                    if bugs:
                        report = "Ошибки:\n"
                        for b in bugs[:5]:
                            report += f"- {b.get('message', '')}\n"
                        send_message(chat_id, report)
                    else:
                        send_message(chat_id, "Ошибок не найдено")
                else:
                    send_message(chat_id, "Нет кода")
            elif text == "/complexity":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, analyze_complexity(code))
                else:
                    send_message(chat_id, "Нет кода")
            elif text == "/run":
                code = user_sessions[user_id].get("code", "")
                if code.strip():
                    send_message(chat_id, "Запуск...")
                    result = run_code_safe(code)
                    if result["success"]:
                        send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1500]}\n```")
                    else:
                        send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:500]}\n```")
                else:
                    send_message(chat_id, "Нет кода")
            elif text == "/generate":
                send_message(chat_id, "Опиши код для генерации:")
                user_sessions[user_id]["waiting_for"] = "generate"
            elif text == "/reset":
                user_sessions[user_id] = {"code": ""}
                send_message(chat_id, "Очищено", reply_markup=json.dumps(get_keyboard()))
            elif user_sessions[user_id].get("waiting_for") == "generate":
                user_sessions[user_id]["waiting_for"] = None
                send_message(chat_id, "Генерация...")
                generated = generate_code(text)
                if generated:
                    user_sessions[user_id]["code"] = generated
                    send_message(chat_id, f"Сгенерировано:\n```python\n{generated[:2000]}\n```")
                else:
                    send_message(chat_id, "Ошибка генерации")
            else:
                user_sessions[user_id]["code"] = text
                send_message(chat_id, f"Код сохранён ({len(text)} символов)\n/show — показать\n/run — выполнить")
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({"ok": False}), 500

@app.route("/")
def health():
    return "Bot is running!", 200

if __name__ == "__main__":
    time.sleep(2)
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)
