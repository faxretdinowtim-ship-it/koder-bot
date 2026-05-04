import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
import random
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
processed_update_ids = set()  # ← ЗАЩИТА ОТ ДУБЛИРОВАНИЯ
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== HTML5 ИГРА ====================
GAME_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>🎮 Кликер Игра</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; user-select: none; -webkit-tap-highlight-color: transparent; }
        body { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; font-family: 'Segoe UI', sans-serif; padding: 20px; }
        .game-container { background: rgba(0,0,0,0.5); backdrop-filter: blur(10px); border-radius: 40px; padding: 25px; text-align: center; max-width: 400px; width: 100%; border: 1px solid rgba(255,255,255,0.1); }
        h1 { font-size: 24px; margin-bottom: 10px; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .score { font-size: 48px; font-weight: bold; color: #ffd700; margin: 20px 0; text-shadow: 0 0 10px rgba(255,215,0,0.5); }
        .click-btn { width: 200px; height: 200px; border-radius: 50%; background: linear-gradient(135deg, #667eea, #764ba2); border: none; cursor: pointer; font-size: 60px; transition: transform 0.1s; box-shadow: 0 10px 30px rgba(0,0,0,0.3); margin: 20px auto; display: block; }
        .click-btn:active { transform: scale(0.95); }
        .upgrades { margin-top: 20px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.1); }
        .upgrade-btn { background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 15px; padding: 12px; margin: 8px 0; width: 100%; cursor: pointer; transition: all 0.2s; color: white; }
        .upgrade-btn:active { transform: scale(0.98); background: rgba(255,255,255,0.2); }
        .upgrade-name { font-weight: bold; }
        .upgrade-cost { font-size: 12px; color: #ffd700; }
        .stats { margin-top: 20px; font-size: 12px; color: rgba(255,255,255,0.5); }
        @media (max-width: 480px) { .click-btn { width: 150px; height: 150px; font-size: 50px; } .score { font-size: 36px; } }
    </style>
</head>
<body>
    <div class="game-container">
        <h1>🎮 Кликер</h1>
        <div class="score" id="score">0</div>
        <button class="click-btn" id="clickBtn">👆</button>
        <div class="upgrades">
            <button class="upgrade-btn" id="autoClicker"><div class="upgrade-name">🤖 Автокликер</div><div class="upgrade-cost">💰 Стоимость: <span id="autoCost">50</span></div></button>
            <button class="upgrade-btn" id="doubleClick"><div class="upgrade-name">⚡ Двойной клик</div><div class="upgrade-cost">💰 Стоимость: <span id="doubleCost">100</span></div></button>
            <button class="upgrade-btn" id="bonusClick"><div class="upgrade-name">🎁 Бонусный клик</div><div class="upgrade-cost">💰 Стоимость: <span id="bonusCost">200</span></div></button>
        </div>
        <div class="stats"><div>🤖 Автокликеров: <span id="autoCount">0</span></div><div>⚡ Множитель: <span id="multiplier">1</span>x</div><div>🎉 Сила клика: <span id="clickPower">1</span></div></div>
    </div>
    <script>
        let score = 0, autoClickers = 0, multiplier = 1, clickPower = 1, autoCost = 50, doubleCost = 100, bonusCost = 200;
        function updateUI() {
            document.getElementById('score').innerText = Math.floor(score);
            document.getElementById('autoCount').innerText = autoClickers;
            document.getElementById('multiplier').innerText = multiplier;
            document.getElementById('clickPower').innerText = clickPower;
            document.getElementById('autoCost').innerText = autoCost;
            document.getElementById('doubleCost').innerText = doubleCost;
            document.getElementById('bonusCost').innerText = bonusCost;
        }
        function clickGame() { let gain = clickPower; score += gain; updateUI(); showFloatingNumber(gain); }
        function showFloatingNumber(value) {
            const btn = document.getElementById('clickBtn');
            const rect = btn.getBoundingClientRect();
            const floatDiv = document.createElement('div');
            floatDiv.innerText = `+${value}`;
            floatDiv.style.position = 'fixed';
            floatDiv.style.left = `${rect.left + rect.width/2}px`;
            floatDiv.style.top = `${rect.top}px`;
            floatDiv.style.color = '#ffd700';
            floatDiv.style.fontWeight = 'bold';
            floatDiv.style.fontSize = '20px';
            floatDiv.style.pointerEvents = 'none';
            document.body.appendChild(floatDiv);
            let top = rect.top, opacity = 1;
            const interval = setInterval(() => { top -= 3; opacity -= 0.03; floatDiv.style.top = `${top}px`; floatDiv.style.opacity = opacity; if (opacity <= 0) { clearInterval(interval); floatDiv.remove(); } }, 20);
        }
        function buyAutoClicker() { if (score >= autoCost) { score -= autoCost; autoClickers++; autoCost = Math.floor(autoCost * 1.5); updateUI(); setInterval(() => { score += 1 * multiplier; updateUI(); }, 1000); } else showNotEnough(); }
        function buyDoubleClick() { if (score >= doubleCost) { score -= doubleCost; multiplier *= 2; clickPower = multiplier; doubleCost = Math.floor(doubleCost * 2); updateUI(); } else showNotEnough(); }
        function buyBonusClick() { if (score >= bonusCost) { score -= bonusCost; clickPower += 5; bonusCost = Math.floor(bonusCost * 1.8); updateUI(); } else showNotEnough(); }
        function showNotEnough() { const msg = document.createElement('div'); msg.innerText = '💰 Не хватает монет!'; msg.style.position = 'fixed'; msg.style.bottom = '30px'; msg.style.left = '50%'; msg.style.transform = 'translateX(-50%)'; msg.style.background = 'rgba(0,0,0,0.8)'; msg.style.color = '#ff6666'; msg.style.padding = '10px 20px'; msg.style.borderRadius = '20px'; document.body.appendChild(msg); setTimeout(() => msg.remove(), 1500); }
        document.getElementById('clickBtn').addEventListener('click', clickGame);
        document.getElementById('autoClicker').addEventListener('click', buyAutoClicker);
        document.getElementById('doubleClick').addEventListener('click', buyDoubleClick);
        document.getElementById('bonusClick').addEventListener('click', buyBonusClick);
        updateUI();
        const tg = window.Telegram?.WebApp;
        if (tg) { tg.ready(); tg.expand(); }
        window.addEventListener('beforeunload', () => {
            if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) {
                fetch('/api/game_save', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: tg.initDataUnsafe.user.id, score: score, autoClickers: autoClickers, multiplier: multiplier, clickPower: clickPower, autoCost: autoCost, doubleCost: doubleCost, bonusCost: bonusCost }) });
            }
        });
    </script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
</body>
</html>'''

# ==================== ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except:
        pass

def send_webapp_button(chat_id, text, webapp_url):
    reply_markup = {"inline_keyboard": [[{"text": text, "web_app": {"url": webapp_url}}]]}
    send_message(chat_id, "🎮 Нажми на кнопку, чтобы открыть игру!", reply_markup=json.dumps(reply_markup))

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return response.json().get("result", [])
    except:
        return []

def auto_fix_code(code):
    if not code.strip():
        return code, "Нет кода"
    fixed = code
    fixes = []
    if re.search(r'^def\s+\w+\([^)]*\)\s*$', fixed, re.MULTILINE):
        fixed = re.sub(r'^(def\s+\w+\([^)]*\))\s*$', r'\1:', fixed, flags=re.MULTILINE)
        fixes.append("двоеточия")
    if '/ 0' in fixed or '/0' in fixed:
        fixed = fixed.replace('/ 0', '/ 1').replace('/0', '/1')
        fixes.append("деление на ноль")
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код уже в хорошем состоянии")

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ Использование eval()")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg}")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

# ==================== FLASK МАРШРУТЫ ====================
@app.route('/')
def health():
    return "🎮 Bot with Game is running!", 200

@app.route('/game')
def game():
    return render_template_string(GAME_HTML)

@app.route('/api/game_save', methods=['POST'])
def game_save():
    data = request.json
    user_id = data.get('user_id')
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]['game'] = data
    return jsonify({"status": "ok"})

# ==================== ОБРАБОТКА TELEGRAM ====================
def process_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    if text == "/start":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_message(chat_id, "🤖 *AI Code Bot + Игры*\n\nПришли код - я исправлю ошибки!\n\n🎮 *Игра:* Нажми на кнопку ниже", parse_mode="Markdown")
        send_webapp_button(chat_id, "🎮 ОТКРЫТЬ ИГРУ", f"{bot_url}/game")
    
    elif text == "/game":
        bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
        send_webapp_button(chat_id, "🎮 ИГРАТЬ", f"{bot_url}/game")
    
    elif text == "/fix":
        code = user_sessions[user_id]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        fixed_code, report = auto_fix_code(code)
        if fixed_code != code:
            user_sessions[user_id]["code"] = fixed_code
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
    
    elif text == "/show":
        code = user_sessions[user_id]["code"]
        send_message(chat_id, f"```python\n{code[:3000] if code else '# Код пуст'}\n```", parse_mode="Markdown")
    
    elif text == "/bugs":
        bugs = find_bugs(user_sessions[user_id]["code"])
        send_message(chat_id, "🐛 Ошибки:\n" + "\n".join(bugs), parse_mode="Markdown")
    
    elif not text.startswith("/"):
        history = user_sessions[user_id].get("history", [])
        history.append({"time": str(datetime.now()), "part": text})
        user_sessions[user_id]["history"] = history
        current = user_sessions[user_id]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[user_id]["code"] = new_code
        send_message(chat_id, f"✅ Часть сохранена! Всего: {len(new_code)} символов\n\n/fix - исправить ошибки\n/game - поиграть")

# ==================== TELEGRAM БОТ ====================
def run_telegram_bot():
    logger.info("Telegram бот запущен!")
    last_id = 0
    while True:
        try:
            updates = get_updates(offset=last_id + 1 if last_id else None)
            for update in updates:
                update_id = update["update_id"]
                # ЗАЩИТА ОТ ДУБЛИРОВАНИЯ
                if update_id in processed_update_ids:
                    continue
                processed_update_ids.add(update_id)
                # Ограничиваем размер множества
                if len(processed_update_ids) > 1000:
                    processed_update_ids.clear()
                
                if "message" in update:
                    process_message(update["message"])
                last_id = update_id
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
