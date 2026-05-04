import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
from datetime import datetime
from flask import Flask, request, render_template_string
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()

# ==================== HTML5 ИГРА ====================
GAME_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>🎮 Кликер Игра</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; user-select: none; }
        body { background: linear-gradient(135deg, #1a1a2e, #16213e); min-height: 100vh; display: flex; justify-content: center; align-items: center; font-family: monospace; padding: 20px; }
        .game-container { background: rgba(0,0,0,0.5); backdrop-filter: blur(10px); border-radius: 40px; padding: 25px; text-align: center; max-width: 400px; width: 100%; }
        h1 { font-size: 28px; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .score { font-size: 56px; font-weight: bold; color: #ffd700; margin: 20px 0; }
        .click-btn { width: 200px; height: 200px; border-radius: 50%; background: linear-gradient(135deg, #667eea, #764ba2); border: none; cursor: pointer; font-size: 70px; margin: 20px auto; display: block; }
        .click-btn:active { transform: scale(0.95); }
        .upgrade-btn { background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 16px; padding: 12px; margin: 10px 0; width: 100%; cursor: pointer; color: white; display: flex; justify-content: space-between; }
        .upgrade-cost { color: #ffd700; font-weight: bold; }
        .stats { margin-top: 20px; padding: 15px; background: rgba(0,0,0,0.3); border-radius: 20px; display: flex; justify-content: space-around; }
        .stat-value { font-size: 20px; font-weight: bold; color: #ffd700; }
    </style>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
</head>
<body>
    <div class="game-container">
        <h1>🎮 КЛИКЕР</h1>
        <div class="score" id="score">0</div>
        <button class="click-btn" id="clickBtn">💰</button>
        <button class="upgrade-btn" id="autoClicker"><span>🤖 Автокликер</span><span class="upgrade-cost" id="autoCost">50</span></button>
        <button class="upgrade-btn" id="doubleClick"><span>⚡ Двойной клик</span><span class="upgrade-cost" id="doubleCost">100</span></button>
        <button class="upgrade-btn" id="bonusClick"><span>🎁 Бонус</span><span class="upgrade-cost" id="bonusCost">200</span></button>
        <div class="stats"><div>🤖 <span id="autoCount">0</span></div><div>⚡ <span id="multiplier">1x</span></div><div>💪 <span id="clickPower">1</span></div></div>
    </div>
    <script>
        let tg = window.Telegram?.WebApp; if (tg) { tg.ready(); tg.expand(); }
        let score = 0, auto = 0, mult = 1, power = 1, autoCost = 50, doubleCost = 100, bonusCost = 200, intervals = [];
        function updateUI() {
            document.getElementById('score').innerText = Math.floor(score);
            document.getElementById('autoCount').innerText = auto;
            document.getElementById('multiplier').innerText = mult + 'x';
            document.getElementById('clickPower').innerText = power;
            document.getElementById('autoCost').innerText = autoCost;
            document.getElementById('doubleCost').innerText = doubleCost;
            document.getElementById('bonusCost').innerText = bonusCost;
        }
        function save() { if (tg?.initDataUnsafe?.user) fetch('/api/game_save', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: tg.initDataUnsafe.user.id, score, autoClickers: auto, multiplier: mult, clickPower: power, autoCost, doubleCost, bonusCost }) }); }
        function load() { if (tg?.initDataUnsafe?.user) fetch(`/api/game_load?user_id=${tg.initDataUnsafe.user.id}`).then(r=>r.json()).then(d=>{ if(d.score!==undefined){ score=d.score; auto=d.autoClickers||0; mult=d.multiplier||1; power=d.clickPower||1; autoCost=d.autoCost||50; doubleCost=d.doubleCost||100; bonusCost=d.bonusCost||200; updateUI(); } }); }
        document.getElementById('clickBtn').onclick = () => { score += power; updateUI(); };
        document.getElementById('autoClicker').onclick = () => { if(score>=autoCost){ score-=autoCost; auto++; autoCost=Math.floor(autoCost*1.5); updateUI(); intervals.push(setInterval(()=>{ score+=mult; updateUI(); },1000)); } };
        document.getElementById('doubleClick').onclick = () => { if(score>=doubleCost){ score-=doubleCost; mult*=2; power=mult; doubleCost=Math.floor(doubleCost*2); updateUI(); } };
        document.getElementById('bonusClick').onclick = () => { if(score>=bonusCost){ score-=bonusCost; power+=5; bonusCost=Math.floor(bonusCost*1.8); updateUI(); } };
        window.onbeforeunload = () => { save(); intervals.forEach(i=>clearInterval(i)); };
        load(); updateUI();
    </script>
</body>
</html>'''

# ==================== ФУНКЦИИ БОТА ====================
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

def send_webapp_button(chat_id, text, url):
    rm = {"inline_keyboard": [[{"text": text, "web_app": {"url": url}}]]}
    send_message(chat_id, "🎮 Нажми на кнопку!", reply_markup=json.dumps(rm))

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
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
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код готов")

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль")
    if 'eval(' in code:
        bugs.append("❌ eval()")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ {e.msg}")
    return bugs if bugs else ["✅ Ошибок нет"]

def analyze_complexity(code):
    lines = [l for l in code.split('\n') if l.strip() and not l.strip().startswith('#')]
    return f"📊 Строк: {len(lines)}\nФункций: {code.count('def ')}\nВетвлений: {code.count('if ')}"

def reorder_code(code):
    lines = code.split('\n')
    imports = [l for l in lines if l.strip().startswith(('import', 'from'))]
    funcs = [l for l in lines if l.strip().startswith('def')]
    other = [l for l in lines if l not in imports and l not in funcs]
    return '\n'.join(imports + [''] + funcs + [''] + other)

# ==================== FLASK МАРШРУТЫ ====================
@app.route('/')
def index():
    return "Bot is running!", 200

@app.route('/game')
def game():
    return render_template_string(GAME_HTML)

@app.route('/api/game_save', methods=['POST'])
def game_save():
    data = request.json
    uid = data.get('user_id')
    if uid:
        with open(f'save_{uid}.json', 'w') as f:
            json.dump(data, f)
    return {"ok": True}

@app.route('/api/game_load', methods=['GET'])
def game_load():
    uid = request.args.get('user_id')
    if uid and os.path.exists(f'save_{uid}.json'):
        with open(f'save_{uid}.json') as f:
            return json.load(f)
    return {}

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["📊 Анализ", "🔄 Порядок"],
            ["🗑 Удалить последний", "✅ Проверить"],
            ["🎮 ИГРА", "🗑 Очистить всё"]
        ],
        "resize_keyboard": True
    }

# ==================== ОБРАБОТКА ====================
def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": []}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    if text == "/start":
        send_message(chat_id, "🤖 AI Code Bot\n\nПришли код - исправлю ошибки!\n🎮 /game - открыть игру", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/game" or text == "🎮 ИГРА":
        send_webapp_button(chat_id, "🎮 ОТКРЫТЬ ИГРУ", f"{bot_url}/game")
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[uid]["code"]
        send_message(chat_id, f"```python\n{code[:3000] if code else '# Пусто'}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        with open(f"code_{uid}.py", "w") as f:
            f.write(code)
        with open(f"code_{uid}.py", "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id}, files={"document": f})
        os.remove(f"code_{uid}.py")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "Очищено!")
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "Код уже хороший")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        bugs = find_bugs(user_sessions[uid]["code"])
        send_message(chat_id, "\n".join(bugs))
    
    elif text == "📊 Анализ" or text == "/complexity":
        send_message(chat_id, analyze_complexity(user_sessions[uid]["code"]))
    
    elif text == "🔄 Порядок" or text == "/order":
        user_sessions[uid]["code"] = reorder_code(user_sessions[uid]["code"])
        send_message(chat_id, "Порядок исправлен!")
    
    elif text == "✅ Проверить" or text == "/validate":
        try:
            compile(user_sessions[uid]["code"], '<string>', 'exec')
            send_message(chat_id, "✅ Синтаксис верен!")
        except SyntaxError as e:
            send_message(chat_id, f"❌ {e.msg}")
    
    elif text == "🗑 Удалить последний" or text == "/undo":
        hist = user_sessions[uid].get("history", [])
        if not hist:
            send_message(chat_id, "Нет частей")
        else:
            hist.pop()
            user_sessions[uid]["history"] = hist
            full = "\n\n".join([h["part"] for h in hist])
            user_sessions[uid]["code"] = full
            send_message(chat_id, f"Удалено! Осталось: {len(hist)} частей")
    
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🔄", "✅", "🗑", "🎮"]):
        hist = user_sessions[uid].get("history", [])
        hist.append({"time": str(datetime.now()), "part": text})
        user_sessions[uid]["history"] = hist
        current = user_sessions[uid]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        send_message(chat_id, f"✅ Часть сохранена! Всего: {len(hist)} частей, {len(new_code)} символов")

# ==================== ЗАПУСК ====================
def run_bot():
    logger.info("Бот запущен!")
    last_id = 0
    while True:
        try:
            updates = get_updates(offset=last_id + 1 if last_id else None)
            for upd in updates:
                if upd["update_id"] in processed_ids:
                    continue
                processed_ids.add(upd["update_id"])
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                if "message" in upd:
                    process_message(upd["message"])
                last_id = upd["update_id"]
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
