import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
from datetime import datetime
from flask import Flask, request, render_template_string, jsonify, session
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
app.secret_key = os.urandom(24)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()

# ==================== ВЕБ-РЕДАКТОР ДЛЯ ПРОВЕРКИ КОДА ====================
WEB_EDITOR_HTML = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Editor - Проверка кода онлайн</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            font-family: 'Segoe UI', 'Fira Code', monospace;
            min-height: 100vh;
            color: #e0e0e0;
        }
        
        .header {
            background: rgba(0, 0, 0, 0.4);
            backdrop-filter: blur(10px);
            padding: 15px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .logo-icon {
            font-size: 32px;
        }
        
        .logo-text {
            font-size: 20px;
            font-weight: bold;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .toolbar {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        button {
            padding: 8px 16px;
            background: #0e639c;
            color: white;
            border: none;
            cursor: pointer;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.2s;
        }
        
        button:hover {
            background: #1177bb;
            transform: translateY(-1px);
        }
        
        button.primary {
            background: linear-gradient(135deg, #667eea, #764ba2);
        }
        
        button.primary:hover {
            opacity: 0.9;
        }
        
        button.danger {
            background: #dc3545;
        }
        
        button.danger:hover {
            background: #c82333;
        }
        
        .main-container {
            display: flex;
            height: calc(100vh - 70px);
            gap: 1px;
            background: rgba(0,0,0,0.2);
        }
        
        .editor-section {
            flex: 2;
            display: flex;
            flex-direction: column;
        }
        
        .output-section {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: rgba(0,0,0,0.3);
        }
        
        .section-header {
            background: rgba(0,0,0,0.3);
            padding: 10px 15px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            font-size: 13px;
            font-weight: bold;
        }
        
        #editor {
            flex: 1;
            min-height: 0;
        }
        
        .output-tabs {
            display: flex;
            gap: 5px;
            padding: 8px 15px;
            background: rgba(0,0,0,0.3);
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .tab {
            padding: 6px 15px;
            cursor: pointer;
            border-radius: 20px;
            background: rgba(255,255,255,0.05);
            font-size: 12px;
            transition: all 0.2s;
        }
        
        .tab.active {
            background: linear-gradient(135deg, #667eea, #764ba2);
        }
        
        .tab:hover {
            background: rgba(255,255,255,0.15);
        }
        
        .output-content {
            flex: 1;
            padding: 15px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 13px;
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .output-success {
            color: #6a9955;
        }
        
        .output-error {
            color: #f48771;
        }
        
        .status-bar {
            background: rgba(0,0,0,0.5);
            padding: 5px 15px;
            font-size: 11px;
            color: #888;
            display: flex;
            justify-content: space-between;
        }
        
        ::-webkit-scrollbar {
            width: 6px;
        }
        
        ::-webkit-scrollbar-track {
            background: #1e1e1e;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #555;
            border-radius: 3px;
        }
        
        @media (max-width: 768px) {
            .main-container {
                flex-direction: column;
            }
            .editor-section {
                height: 50vh;
            }
            .toolbar button {
                padding: 6px 12px;
                font-size: 12px;
            }
        }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
    <div class="header">
        <div class="logo">
            <span class="logo-icon">🤖</span>
            <span class="logo-text">AI Code Editor</span>
        </div>
        <div class="toolbar">
            <button class="primary" onclick="runCode()">▶️ Запустить</button>
            <button onclick="analyzeCode()">📊 Анализ сложности</button>
            <button onclick="findBugs()">🐛 Поиск ошибок</button>
            <button onclick="fixCode()">🔧 Исправить</button>
            <button onclick="saveCode()">💾 Сохранить</button>
            <button onclick="downloadCode()">📥 Скачать</button>
            <button class="danger" onclick="clearCode()">🗑 Очистить</button>
        </div>
    </div>
    
    <div class="main-container">
        <div class="editor-section">
            <div class="section-header">📝 Редактор кода (Python)</div>
            <div id="editor"></div>
        </div>
        
        <div class="output-section">
            <div class="output-tabs">
                <div class="tab active" onclick="switchTab('output')">📄 Вывод</div>
                <div class="tab" onclick="switchTab('analysis')">📊 Анализ</div>
                <div class="tab" onclick="switchTab('bugs')">🐛 Ошибки</div>
            </div>
            <div class="output-content" id="outputContent">
                <span class="output-success">✅ Готов к работе</span>
            </div>
        </div>
    </div>
    
    <div class="status-bar">
        <span id="status">⚡ Готов</span>
        <span id="stats">📝 Символов: 0</span>
    </div>
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
    <script>
        let editor;
        let currentTab = 'output';
        const USER_ID = {{ user_id }};
        const API_URL = window.location.origin;
        
        require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], function() {
            editor = monaco.editor.create(document.getElementById('editor'), {
                value: {{ code | tojson }},
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
            
            updateStats();
        });
        
        function updateStats() {
            const len = editor?.getValue().length || 0;
            document.getElementById('stats').innerHTML = `📝 Символов: ${len}`;
        }
        
        function switchTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
        }
        
        function setOutput(text, isError = false) {
            const outputDiv = document.getElementById('outputContent');
            const className = isError ? 'output-error' : 'output-success';
            outputDiv.innerHTML = `<span class="${className}">${escapeHtml(text)}</span>`;
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        async function runCode() {
            const code = editor.getValue();
            if (!code.trim()) {
                setOutput('❌ Нет кода для выполнения', true);
                return;
            }
            
            setOutput('⏳ Выполнение...');
            document.getElementById('status').innerText = '🏃 Запуск...';
            
            try {
                const res = await fetch(API_URL + '/api/run', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code: code})
                });
                const data = await res.json();
                
                if (data.success) {
                    setOutput(data.output || '✅ Выполнение успешно! (нет вывода)');
                    document.getElementById('status').innerText = '✅ Выполнено';
                } else {
                    setOutput(data.error || '❌ Ошибка выполнения', true);
                    document.getElementById('status').innerText = '❌ Ошибка';
                }
            } catch(e) {
                setOutput('Ошибка соединения с сервером', true);
            }
            switchTab('output');
        }
        
        async function analyzeCode() {
            const code = editor.getValue();
            if (!code.trim()) {
                setOutput('❌ Нет кода для анализа', true);
                return;
            }
            
            setOutput('⏳ Анализ сложности...');
            const res = await fetch(API_URL + '/api/analyze', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code})
            });
            const data = await res.json();
            setOutput(data.report);
            document.getElementById('status').innerText = '📊 Анализ завершён';
            switchTab('analysis');
        }
        
        async function findBugs() {
            const code = editor.getValue();
            if (!code.trim()) {
                setOutput('❌ Нет кода для поиска ошибок', true);
                return;
            }
            
            setOutput('⏳ Поиск ошибок...');
            const res = await fetch(API_URL + '/api/bugs', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code})
            });
            const data = await res.json();
            setOutput(data.report);
            document.getElementById('status').innerText = '🐛 Поиск завершён';
            switchTab('bugs');
        }
        
        async function fixCode() {
            const code = editor.getValue();
            if (!code.trim()) {
                setOutput('❌ Нет кода для исправления', true);
                return;
            }
            
            setOutput('🔧 Исправление кода...');
            const res = await fetch(API_URL + '/api/fix', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code})
            });
            const data = await res.json();
            editor.setValue(data.code);
            setOutput(data.report);
            document.getElementById('status').innerText = '🔧 Исправлено';
            setTimeout(() => document.getElementById('status').innerText = '⚡ Готов', 2000);
        }
        
        async function saveCode() {
            const code = editor.getValue();
            await fetch(API_URL + '/api/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({user_id: USER_ID, code: code})
            });
            document.getElementById('status').innerText = '💾 Сохранено!';
            setTimeout(() => document.getElementById('status').innerText = '⚡ Готов', 1500);
        }
        
        function downloadCode() {
            const code = editor.getValue();
            const blob = new Blob([code], {type: 'text/plain'});
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'code.py';
            a.click();
            URL.revokeObjectURL(a.href);
            document.getElementById('status').innerText = '📥 Скачивание...';
            setTimeout(() => document.getElementById('status').innerText = '⚡ Готов', 1000);
        }
        
        function clearCode() {
            if (confirm('Очистить редактор? (несохранённые данные будут потеряны)')) {
                editor.setValue('# Ваш код здесь\n\ndef main():\n    print("Hello, World!")\n\nif __name__ == "__main__":\n    main()');
                setOutput('✅ Редактор очищен');
                document.getElementById('status').innerText = '🗑 Очищено';
                setTimeout(() => document.getElementById('status').innerText = '⚡ Готов', 1000);
            }
        }
        
        // Автосохранение каждые 30 секунд
        setInterval(() => {
            if (editor && editor.getValue()) {
                saveCode();
            }
        }, 30000);
    </script>
</body>
</html>
'''

# ==================== TELEGRAM ФУНКЦИИ ====================
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

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С КОДОМ ====================
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
    # Удаляем дубликаты импортов
    lines = fixed.split('\n')
    seen = set()
    new_lines = []
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            if line.strip() not in seen:
                seen.add(line.strip())
                new_lines.append(line)
        else:
            new_lines.append(line)
    if len(new_lines) != len(lines):
        fixes.append("дубликаты импортов")
    fixed = '\n'.join(new_lines)
    return (fixed, f"✅ Исправлено: {', '.join(fixes)}") if fixes else (fixed, "✅ Код уже в хорошем состоянии")

def find_bugs(code):
    bugs = []
    if '/ 0' in code or '/0' in code:
        bugs.append("❌ Деление на ноль [КРИТИЧЕСКАЯ]")
    if 'eval(' in code:
        bugs.append("❌ Использование eval() [ВЫСОКАЯ]")
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except [СРЕДНЯЯ]")
    if re.search(r'password\s*=\s*[\'"]', code, re.IGNORECASE):
        bugs.append("❌ Хардкод пароля [КРИТИЧЕСКАЯ]")
    if 'print(' in code:
        bugs.append("⚠️ Отладочный print() [НИЗКАЯ]")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg} [КРИТИЧЕСКАЯ]")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    if complexity < 10:
        rating = "Низкая (хорошо)"
    elif complexity < 20:
        rating = "Средняя (нормально)"
    else:
        rating = "Высокая (нужен рефакторинг)"
    return f"📊 **Анализ сложности кода**\n\n• Строк кода: {code_lines}\n• Функций: {functions}\n• Ветвлений: {branches}\n• Цикломатическая сложность: {complexity:.1f}\n• Оценка: {rating}"

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
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

# ==================== FLASK МАРШРУТЫ ====================
@app.route('/')
def index():
    return "🤖 AI Code Bot is running! Use /web/<user_id> to open editor", 200

@app.route('/web/<int:user_id>')
def web_editor(user_id):
    """Веб-редактор для проверки кода"""
    code = user_sessions.get(user_id, {}).get("code", "# Ваш код здесь\n\ndef main():\n    print('Hello, World!')\n\nif __name__ == '__main__':\n    main()")
    return render_template_string(WEB_EDITOR_HTML, user_id=user_id, code=code)

@app.route('/api/run', methods=['POST'])
def api_run():
    code = request.json.get('code', '')
    result = run_code_safe(code)
    return jsonify(result)

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    code = request.json.get('code', '')
    result = analyze_complexity(code)
    return jsonify({"report": result})

@app.route('/api/bugs', methods=['POST'])
def api_bugs():
    code = request.json.get('code', '')
    bugs = find_bugs(code)
    return jsonify({"report": "\n".join(bugs)})

@app.route('/api/fix', methods=['POST'])
def api_fix():
    code = request.json.get('code', '')
    fixed_code, report = auto_fix_code(code)
    return jsonify({"code": fixed_code, "report": report})

@app.route('/api/save', methods=['POST'])
def api_save():
    data = request.json
    user_id = data.get('user_id')
    code = data.get('code', '')
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    user_sessions[user_id]['code'] = code
    return jsonify({"success": True})

@app.route('/api/load', methods=['GET'])
def api_load():
    user_id = request.args.get('user_id', type=int)
    code = user_sessions.get(user_id, {}).get('code', '')
    return jsonify({"code": code})

# ==================== TELEGRAM БОТ ====================
def get_keyboard():
    return {
        "keyboard": [
            ["🌐 Веб-редактор", "📝 Показать код"],
            ["💾 Скачать код", "🔧 ИСПРАВИТЬ"],
            ["🐛 Ошибки", "📊 Анализ"],
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
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Я помогаю писать, проверять и исправлять код!\n\n"
            "🌐 *Веб-редактор:* Отправь /web\n"
            "📝 *Код:* Пришли часть кода - я соберу\n"
            "🔧 *Исправление:* Нажми /fix\n\n"
            "👇 Используй кнопки ниже!",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/web" or text == "🌐 Веб-редактор":
        send_webapp_button(chat_id, "🌐 ОТКРЫТЬ РЕДАКТОР", f"{bot_url}/web/{uid}")
    
    elif text == "📝 Показать код" or text == "/show":
        code = user_sessions[uid]["code"]
        send_message(chat_id, f"```python\n{code[:3000] if code else '# Код пуст'}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для скачивания")
            return
        filename = f"code_{uid}.py"
        with open(filename, "w") as f:
            f.write(code)
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id}, files={"document": f})
        os.remove(filename)
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для исправления")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["code"] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "Код уже в хорошем состоянии")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        bugs = find_bugs(user_sessions[uid]["code"])
        send_message(chat_id, "\n".join(bugs))
    
    elif text == "📊 Анализ" or text == "/complexity":
        send_message(chat_id, analyze_complexity(user_sessions[uid]["code"]))
    
    elif text == "🏃 Запустить" or text == "/run":
        code = user_sessions[uid]["code"]
        if not code.strip():
            send_message(chat_id, "Нет кода для запуска")
            return
        send_message(chat_id, "🏃 Запуск...")
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid] = {"code": "", "history": []}
        send_message(chat_id, "Код очищен!")
    
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["🌐", "📝", "💾", "🔧", "🐛", "📊", "🏃", "🗑"]):
        hist = user_sessions[uid].get("history", [])
        hist.append({"time": str(datetime.now()), "part": text})
        user_sessions[uid]["history"] = hist
        current = user_sessions[uid]["code"]
        new_code = current + "\n\n" + text if current else text
        user_sessions[uid]["code"] = new_code
        send_message(chat_id, f"✅ Часть сохранена! Всего: {len(hist)} частей, {len(new_code)} символов")

# ==================== ЗАПУСК ====================
def run_bot():
    logger.info("Telegram бот запущен!")
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
