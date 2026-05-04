import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
from datetime import datetime
from flask import Flask, request, render_template_string, jsonify
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()

# ==================== ВЕБ-РЕДАКТОР HTML (С АВТОЗАГРУЗКОЙ) ====================
WEB_EDITOR_HTML = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Editor - Синхронизация с ботом</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; }
        #editor { height: 65vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; flex-wrap: wrap; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; font-size: 13px; }
        button:hover { background: #1177bb; }
        button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        .output { background: #1e1e1e; color: #d4d4d4; padding: 10px; height: 30vh; overflow: auto; font-family: monospace; white-space: pre-wrap; border-top: 1px solid #333; font-size: 13px; }
        .status-bar { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; display: flex; justify-content: space-between; border-top: 1px solid #333; }
        .success { color: #6a9955; }
        .error { color: #f48771; }
        .info { color: #569cd6; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="toolbar">
    <button class="primary" onclick="syncFromBot()">📥 Загрузить из бота</button>
    <button class="primary" onclick="syncToBot()">💾 Сохранить в бота</button>
    <button onclick="runCode()">▶️ Запустить</button>
    <button onclick="analyzeCode()">📊 Анализ</button>
    <button onclick="findBugs()">🐛 Ошибки</button>
    <button onclick="fixCode()">🔧 Исправить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
    <button onclick="clearCode()">🗑 Очистить</button>
</div>
<div id="editor"></div>
<div class="output" id="output">⚡ Готов к работе. Нажми "Загрузить из бота" чтобы получить код из Telegram.</div>
<div class="status-bar">
    <span id="status">⚡ Готов</span>
    <span id="stats">📝 Символов: 0</span>
    <span id="syncStatus"></span>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor;
const USER_ID = {{ user_id }};
const API_URL = window.location.origin;

require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '# Нажми "Загрузить из бота" чтобы получить код из Telegram\n# Или пиши код здесь',
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true },
        automaticLayout: true,
        fontFamily: 'Fira Code, monospace',
        fontLigatures: true
    });
    
    editor.onDidChangeModelContent(() => {
        const len = editor.getValue().length;
        document.getElementById('stats').innerHTML = `📝 Символов: ${len}`;
    });
});

function setOutput(text, type = 'info') {
    const outputDiv = document.getElementById('output');
    const className = type === 'error' ? 'error' : (type === 'success' ? 'success' : 'info');
    outputDiv.innerHTML = `<span class="${className}">${escapeHtml(text)}</span>`;
}

function setStatus(text, isError = false) {
    const statusEl = document.getElementById('status');
    statusEl.innerHTML = text;
    statusEl.style.color = isError ? '#f48771' : '#888';
}

function setSyncStatus(text) {
    document.getElementById('syncStatus').innerHTML = text;
    setTimeout(() => document.getElementById('syncStatus').innerHTML = '', 3000);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ========== ОСНОВНЫЕ ФУНКЦИИ ==========

async function syncFromBot() {
    setOutput('⏳ Загрузка кода из Telegram бота...');
    setStatus('📥 Загрузка...');
    try {
        const res = await fetch(`${API_URL}/api/load?user_id=${USER_ID}`);
        const data = await res.json();
        if (data.code && data.code !== '# Пусто') {
            editor.setValue(data.code);
            setOutput('✅ Код успешно загружен из Telegram бота!');
            setSyncStatus('✅ Загружено из бота');
            setStatus('✅ Загружено');
        } else {
            setOutput('📭 В боте нет кода. Отправь код в Telegram или напиши здесь.', 'error');
        }
    } catch(e) {
        setOutput('❌ Ошибка загрузки: ' + e, 'error');
        setStatus('❌ Ошибка', true);
    }
}

async function syncToBot() {
    const code = editor.getValue();
    if (!code.trim()) {
        setOutput('❌ Нет кода для сохранения', 'error');
        return;
    }
    setOutput('⏳ Сохранение в Telegram бота...');
    setStatus('💾 Сохранение...');
    try {
        await fetch(`${API_URL}/api/save`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: USER_ID, code: code})
        });
        setOutput('✅ Код сохранён в Telegram бота! Теперь в боте можно использовать /show');
        setSyncStatus('✅ Сохранено в бота');
        setStatus('✅ Сохранено');
    } catch(e) {
        setOutput('❌ Ошибка сохранения: ' + e, 'error');
        setStatus('❌ Ошибка', true);
    }
}

async function runCode() {
    const code = editor.getValue();
    if (!code.trim()) {
        setOutput('❌ Нет кода для выполнения', 'error');
        return;
    }
    setOutput('⏳ Выполнение...');
    setStatus('🏃 Запуск...');
    try {
        const res = await fetch(`${API_URL}/api/run`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({code: code})
        });
        const data = await res.json();
        if (data.success) {
            setOutput(data.output || '✅ Выполнение успешно! (нет вывода)', 'success');
            setStatus('✅ Выполнено');
        } else {
            setOutput(data.error || '❌ Ошибка выполнения', 'error');
            setStatus('❌ Ошибка', true);
        }
    } catch(e) {
        setOutput('❌ Ошибка соединения', 'error');
    }
}

async function analyzeCode() {
    const code = editor.getValue();
    if (!code.trim()) {
        setOutput('❌ Нет кода для анализа', 'error');
        return;
    }
    setOutput('⏳ Анализ...');
    const res = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    setOutput(data.report, 'success');
}

async function findBugs() {
    const code = editor.getValue();
    if (!code.trim()) {
        setOutput('❌ Нет кода для поиска ошибок', 'error');
        return;
    }
    setOutput('⏳ Поиск ошибок...');
    const res = await fetch(`${API_URL}/api/bugs`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    setOutput(data.report, data.report.includes('✅') ? 'success' : 'error');
}

async function fixCode() {
    const code = editor.getValue();
    if (!code.trim()) {
        setOutput('❌ Нет кода для исправления', 'error');
        return;
    }
    setOutput('🔧 Исправление...');
    const res = await fetch(`${API_URL}/api/fix`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    editor.setValue(data.code);
    setOutput(data.report, 'success');
}

function downloadCode() {
    const code = editor.getValue();
    const blob = new Blob([code], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'code.py';
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus('📥 Скачивание...');
    setTimeout(() => setStatus('⚡ Готов'), 1000);
}

function clearCode() {
    if (confirm('Очистить редактор? (несохранённые данные будут потеряны)')) {
        editor.setValue('');
        setOutput('✅ Редактор очищен');
    }
}
</script>
</body>
</html>
'''

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

def send_web_button(chat_id, user_id):
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    rm = {"inline_keyboard": [[{"text": "🌐 ОТКРЫТЬ РЕДАКТОР", "web_app": {"url": f"{bot_url}/web/{user_id}"}}]]}
    send_message(chat_id, "🌐 Нажми на кнопку, чтобы открыть редактор!", reply_markup=json.dumps(rm))

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
    if re.search(r'print\(["\'][^"\']*["\']$', fixed, re.MULTILINE):
        fixed = re.sub(r'(print\(["\'][^"\']*["\'])$', r'\1)', fixed, flags=re.MULTILINE)
        fixes.append("print()")
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код готов")

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

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    return f"📊 Строк кода: {code_lines}\n📦 Функций: {functions}"

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except:
        return {"success": False, "output": "", "error": "Timeout"}
    finally:
        os.unlink(temp_file)

# ==================== FLASK МАРШРУТЫ ====================
@app.route('/')
def index():
    return "🤖 Bot is running! Use /web/<user_id>", 200

@app.route('/web/<int:user_id>')
def web_editor(user_id):
    return render_template_string(WEB_EDITOR_HTML, user_id=user_id)

@app.route('/api/load', methods=['GET'])
def api_load():
    user_id = request.args.get('user_id', type=int)
    code = user_sessions.get(user_id, {}).get('code', '')
    return jsonify({"code": code})

@app.route('/api/save', methods=['POST'])
def api_save():
    data = request.json
    uid = data.get('user_id')
    code = data.get('code', '')
    if uid not in user_sessions:
        user_sessions[uid] = {}
    user_sessions[uid]['code'] = code
    return jsonify({"success": True})

@app.route('/api/run', methods=['POST'])
def api_run():
    result = run_code_safe(request.json.get('code', ''))
    return jsonify(result)

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    return jsonify({"report": analyze_complexity(request.json.get('code', ''))})

@app.route('/api/bugs', methods=['POST'])
def api_bugs():
    bugs = find_bugs(request.json.get('code', ''))
    return jsonify({"report": "\n".join(bugs)})

@app.route('/api/fix', methods=['POST'])
def api_fix():
    code = request.json.get('code', '')
    fixed, report = auto_fix_code(code)
    return jsonify({"code": fixed, "report": report})

# ==================== TELEGRAM БОТ ====================
def get_keyboard():
    return {
        "keyboard": [
            ["🌐 Веб-редактор", "📝 Показать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "🗑 Очистить всё"]
        ],
        "resize_keyboard": True
    }

def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"code": "", "history": []}
    
    if text == "/start":
        send_message(chat_id, "🤖 *AI Code Bot*\n\nПришли код - я соберу и исправлю!\n\n🌐 /web - открыть редактор\n🔧 /fix - исправить код\n🐛 /bugs - найти ошибки\n🏃 /run - выполнить код", parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/web" or text == "🌐 Веб-редактор":
        send_web_button(chat_id, uid)
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[uid]["code"]
        send_message(chat_id, f"```python\n{code[:3000] if code else '# Код пуст'}\n```", parse_mode="Markdown")
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для исправления")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        bugs = find_bugs(user_sessions[uid]["code"])
        send_message(chat_id, "🔍 Результаты проверки:\n" + "\n".join(bugs))
    
    elif text == "🏃 Запустить" or text == "/run":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для запуска")
            return
        send_message(chat_id, "⏳ Выполнение...")
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "🧹 Код очищен!")
    
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["🌐", "📝", "🔧", "🐛", "🏃", "🗑"]):
        hist = user_sessions[uid].get("history", [])
        hist.append({"time": str(datetime.now()), "part": text})
        user_sessions[uid]["history"] = hist
        current = user_sessions[uid]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        send_message(chat_id, f"✅ Часть сохранена! Всего частей: {len(hist)}\n📊 Всего символов: {len(new_code)}\n\n🌐 /web - открыть редактор\n🔧 /fix - исправить ошибки")

# ==================== ЗАПУСК ====================
def run_bot():
    logger.info("🤖 Telegram бот запущен!")
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
