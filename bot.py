import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
import zipfile
from io import BytesIO
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== ФУНКЦИЯ РАСПОЗНАВАНИЯ ФАЙЛОВ ====================
def parse_files_from_code(text):
    """Распознаёт множество файлов из одного сообщения"""
    files = {}
    
    # Паттерны для разных типов файлов
    patterns = {
        r'```dockerfile\n(.*?)```': 'Dockerfile',
        r'```python\n(.*?)```': None,  # Определяется по имени
        r'```\n(.*?)```': None,
    }
    
    # Ищем файлы по маркерам
    # Формат: ### Файл: app.py ```python ... ```
    file_pattern = r'###\s*Файл:\s*([^\s]+)\s*```(?:\w+)?\n(.*?)```'
    matches = re.findall(file_pattern, text, re.DOTALL | re.IGNORECASE)
    for filename, content in matches:
        files[filename.strip()] = content.strip()
    
    # Поиск по именам файлов в тексте
    known_files = [
        'app.py', 'bot.py', 'main.py', 'requirements.txt', 
        'Dockerfile', 'runtime.txt', '.dockerignore', 'docker-compose.yml',
        'index.html', 'style.css', 'script.js', 'README.md', '.env', 'config.json'
    ]
    
    for filename in known_files:
        # Ищем содержимое файла после имени
        escaped_name = re.escape(filename)
        pattern = rf'{escaped_name}\s*\n```(?:\w+)?\n(.*?)```'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            files[filename] = match.group(1).strip()
    
    return files

def detect_all_files_from_code(text):
    """Обнаруживает все возможные файлы в сообщении"""
    files = {}
    
    # Разделяем на блоки кода
    code_blocks = re.findall(r'```(\w*)\n(.*?)```', text, re.DOTALL)
    
    for lang, content in code_blocks:
        # Пытаемся определить имя файла по языку
        if lang == 'python' or lang == 'py':
            # Ищем имя файла перед блоком
            before = text[:text.find(f'```{lang}')]
            file_match = re.search(r'([\w\.]+\.py)', before)
            if file_match:
                files[file_match.group(1)] = content.strip()
            else:
                files[f'script_{len(files)}.py'] = content.strip()
        elif lang == 'dockerfile' or 'docker' in lang.lower():
            files['Dockerfile'] = content.strip()
        elif lang == 'txt' or 'requirements' in lang.lower():
            files['requirements.txt'] = content.strip()
        elif lang == 'html':
            files['index.html'] = content.strip()
        elif lang == 'css':
            files['style.css'] = content.strip()
        elif lang == 'js' or lang == 'javascript':
            files['script.js'] = content.strip()
        elif lang == 'json':
            files['config.json'] = content.strip()
        elif lang == 'md':
            files['README.md'] = content.strip()
        elif lang == 'ignore' or 'gitignore' in lang.lower():
            files['.dockerignore'] = content.strip()
        else:
            files[f'file_{len(files)}.txt'] = content.strip()
    
    return files

# ==================== ВЕБ-СТРАНИЦА ДЛЯ ПРОСМОТРА КОДА ====================
VIEW_CODE_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📄 Просмотр кода - AI Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: #2d2d2d; padding: 15px; border-radius: 10px; margin-bottom: 20px; }
        h1 { color: #667eea; font-size: 24px; }
        .file-list { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
        .file-btn { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 8px; }
        .file-btn.active { background: linear-gradient(135deg, #667eea, #764ba2); }
        .code-block { background: #1e1e1e; border: 1px solid #333; border-radius: 10px; overflow: hidden; }
        .code-header { background: #2d2d2d; padding: 10px 15px; font-size: 14px; border-bottom: 1px solid #333; }
        pre { margin: 0; padding: 15px; overflow-x: auto; font-size: 13px; }
        code { font-family: monospace; }
        .actions { margin-top: 20px; display: flex; gap: 10px; }
        .btn { padding: 10px 20px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 8px; text-decoration: none; display: inline-block; }
        .btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        .status { background: #2d2d2d; padding: 10px; border-radius: 8px; margin-top: 20px; text-align: center; color: #888; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📄 Просмотр кода</h1>
        <p>Ваши файлы из Telegram бота</p>
    </div>
    <div class="file-list" id="fileList"></div>
    <div class="code-block">
        <div class="code-header" id="currentFile">Выберите файл</div>
        <pre><code id="codeContent"></code></pre>
    </div>
    <div class="actions">
        <button class="btn" onclick="downloadCurrent()">📥 Скачать текущий файл</button>
        <button class="btn btn-primary" onclick="downloadAll()">📦 Скачать все файлы (ZIP)</button>
    </div>
    <div class="status" id="status">⚡ Готов к работе</div>
</div>
<script>
const USER_ID = {{ user_id }};
const API_URL = window.location.origin;

async function loadFiles() {
    const res = await fetch(`${API_URL}/api/files?user_id=${USER_ID}`);
    const data = await res.json();
    const fileList = document.getElementById('fileList');
    fileList.innerHTML = '';
    if (data.files && Object.keys(data.files).length > 0) {
        for (const [name, content] of Object.entries(data.files)) {
            const btn = document.createElement('button');
            btn.className = 'file-btn';
            btn.textContent = name;
            btn.onclick = () => showFile(name, content);
            fileList.appendChild(btn);
        }
        // Показываем первый файл
        const first = Object.entries(data.files)[0];
        if (first) showFile(first[0], first[1]);
    } else {
        fileList.innerHTML = '<span style="color:#888;">Нет файлов. Отправьте код в Telegram бота!</span>';
        document.getElementById('codeContent').innerHTML = '# Нет файлов';
    }
}

function showFile(name, content) {
    document.getElementById('currentFile').innerHTML = `📄 ${name}`;
    document.getElementById('codeContent').innerHTML = escapeHtml(content);
}

function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function downloadCurrent() {
    const currentName = document.getElementById('currentFile').innerText.replace('📄 ', '');
    const res = await fetch(`${API_URL}/api/files?user_id=${USER_ID}`);
    const data = await res.json();
    const content = data.files[currentName];
    if (content) {
        const blob = new Blob([content], {type: 'text/plain'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = currentName;
        a.click();
        URL.revokeObjectURL(a.href);
        document.getElementById('status').innerHTML = '✅ Файл скачан!';
        setTimeout(() => document.getElementById('status').innerHTML = '⚡ Готов к работе', 2000);
    }
}

async function downloadAll() {
    const res = await fetch(`${API_URL}/api/export_zip?user_id=${USER_ID}`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `project_${USER_ID}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
    document.getElementById('status').innerHTML = '📦 ZIP архив скачан!';
    setTimeout(() => document.getElementById('status').innerHTML = '⚡ Готов к работе', 2000);
}

loadFiles();
</script>
</body>
</html>
'''

# ==================== ВЕБ-РЕДАКТОР HTML ====================
WEB_EDITOR_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Editor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; }
        .header { background: #2d2d2d; padding: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .logo { font-size: 18px; font-weight: bold; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .file-select { background: #0e639c; padding: 5px 10px; border-radius: 5px; border: none; color: white; cursor: pointer; }
        .toolbar { display: flex; gap: 5px; flex-wrap: wrap; }
        button { padding: 6px 12px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; font-size: 12px; }
        button:hover { background: #1177bb; }
        button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        button.danger { background: #dc3545; }
        #editor { height: calc(100vh - 120px); }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 11px; display: flex; justify-content: space-between; border-top: 1px solid #333; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="header">
    <div class="logo">🤖 AI Code Editor</div>
    <select id="fileSelect" class="file-select" onchange="switchFile()"></select>
    <div class="toolbar">
        <button onclick="saveCurrentFile()">💾 Сохранить</button>
        <button onclick="runCode()">▶️ Запустить</button>
        <button onclick="analyzeCode()">📊 Анализ</button>
        <button onclick="findBugs()">🐛 Ошибки</button>
        <button onclick="fixCode()">🔧 Исправить</button>
        <button onclick="newFile()">➕ Новый файл</button>
        <button onclick="deleteFile()" class="danger">🗑 Удалить файл</button>
        <button onclick="downloadCurrent()">📥 Скачать</button>
    </div>
</div>
<div id="editor"></div>
<div class="status"><span id="status">⚡ Готов</span><span id="stats">📝 0</span></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor;
let currentFile = null;
let filesList = {};
const USER_ID = {{ user_id }};
const API_URL = window.location.origin;

require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '# Загрузка...',
        language: 'python',
        theme: 'vs-dark',
        fontSize: 13,
        minimap: { enabled: true },
        automaticLayout: true
    });
    editor.onDidChangeModelContent(() => {
        document.getElementById('stats').innerHTML = `📝 ${editor.getValue().length}`;
    });
    loadFiles();
});

async function loadFiles() {
    const res = await fetch(`${API_URL}/api/files?user_id=${USER_ID}`);
    const data = await res.json();
    filesList = data.files || {};
    
    const select = document.getElementById('fileSelect');
    select.innerHTML = '';
    for (const name in filesList) {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    }
    
    if (Object.keys(filesList).length === 0) {
        filesList = {'main.py': '# Напишите свой код здесь\nprint("Hello, World!")'};
        await saveAllFiles();
        loadFiles();
    }
    
    currentFile = select.value || Object.keys(filesList)[0];
    editor.setValue(filesList[currentFile] || '');
    setLanguage(currentFile);
}

function setLanguage(filename) {
    const ext = filename.split('.').pop();
    const langs = {py:'python', js:'javascript', html:'html', css:'css', json:'json', md:'markdown', txt:'text'};
    monaco.editor.setModelLanguage(editor.getModel(), langs[ext] || 'python');
}

async function switchFile() {
    const select = document.getElementById('fileSelect');
    filesList[currentFile] = editor.getValue();
    currentFile = select.value;
    editor.setValue(filesList[currentFile] || '');
    setLanguage(currentFile);
    document.getElementById('stats').innerHTML = `📝 ${editor.getValue().length}`;
}

async function saveCurrentFile() {
    filesList[currentFile] = editor.getValue();
    await saveAllFiles();
    document.getElementById('status').innerHTML = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerHTML = '⚡ Готов', 1500);
}

async function saveAllFiles() {
    await fetch(`${API_URL}/api/save_files`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, files: filesList})
    });
}

async function runCode() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/run`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    if (data.success) {
        alert('✅ Выполнено!\n\n' + (data.output || '(нет вывода)'));
    } else {
        alert('❌ Ошибка:\n\n' + data.error);
    }
}

async function analyzeCode() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert('📊 ' + data.report);
}

async function findBugs() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/bugs`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert('🐛 ' + data.report);
}

async function fixCode() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/fix`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    filesList['main.py'] = data.code;
    editor.setValue(data.code);
    await saveAllFiles();
    alert(data.report);
}

async function newFile() {
    const name = prompt('Введите имя файла (например: app.py, index.html):');
    if (name && !filesList[name]) {
        filesList[name] = '# Новый файл';
        await saveAllFiles();
        loadFiles();
        document.getElementById('fileSelect').value = name;
        currentFile = name;
        editor.setValue(filesList[name]);
    } else if (filesList[name]) {
        alert('Файл уже существует!');
    }
}

async function deleteFile() {
    if (confirm(`Удалить файл ${currentFile}?`)) {
        delete filesList[currentFile];
        await saveAllFiles();
        loadFiles();
    }
}

function downloadCurrent() {
    const content = filesList[currentFile];
    const blob = new Blob([content], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = currentFile;
    a.click();
    URL.revokeObjectURL(a.href);
}
</script>
</body>
</html>
'''

# ==================== КЛАВИАТУРА ====================
def get_main_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "📊 Анализ"],
            ["📁 Файлы", "➕ Добавить файл"],
            ["🌐 Веб-редактор", "🗑 Очистить всё"],
            ["❓ Помощь"]
        ],
        "resize_keyboard": True
    }

def get_files_keyboard(files):
    keyboard = []
    row = []
    for name in list(files.keys())[:8]:
        row.append({"text": f"📄 {name[:20]}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([{"text": "📦 Экспорт ZIP"}, {"text": "🔙 Главное меню"}])
    keyboard.append([{"text": "➕ Добавить файл"}, {"text": "🗑 Удалить файл"}])
    return {"inline_keyboard": keyboard}

# ==================== ФУНКЦИИ ====================
def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_web_button(chat_id, user_id):
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    rm = {"inline_keyboard": [[{"text": "🌐 ОТКРЫТЬ РЕДАКТОР", "web_app": {"url": f"{bot_url}/web/{user_id}"}}]]}
    send_message(chat_id, "🌐 Нажми на кнопку, чтобы открыть редактор!", reply_markup=json.dumps(rm))

def send_view_button(chat_id, user_id):
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    send_message(chat_id, f"🌐 *Просмотр кода в браузере:*\n{bot_url}/view/{user_id}", parse_mode="Markdown")

def get_updates():
    global last_update_id
    params = {"timeout": 30}
    if last_update_id:
        params["offset"] = last_update_id + 1
    try:
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        logger.error(f"Ошибка getUpdates: {e}")
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
        bugs.append("❌ Деление на ноль [КРИТИЧЕСКАЯ]")
    if 'eval(' in code:
        bugs.append("❌ Использование eval() [ВЫСОКАЯ]")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg} [КРИТИЧЕСКАЯ]")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    return f"Строк кода: {code_lines} | Функций: {functions}"

def run_code_safe(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code); temp_file = f.name
    try:
        process = subprocess.run(["python3", temp_file], capture_output=True, text=True, timeout=5)
        return {"success": process.returncode == 0, "output": process.stdout, "error": process.stderr}
    except:
        return {"success": False, "output": "", "error": "Timeout"}
    finally:
        os.unlink(temp_file)

# ==================== HTTP СЕРВЕР ====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path.startswith('/web/'):
            user_id = int(parsed.path.split('/')[2])
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(WEB_EDITOR_HTML.replace('{{ user_id }}', str(user_id)).encode('utf-8'))
        
        elif parsed.path.startswith('/view/'):
            user_id = int(parsed.path.split('/')[2])
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(VIEW_CODE_HTML.replace('{{ user_id }}', str(user_id)).encode('utf-8'))
        
        elif parsed.path == '/' or parsed.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        
        elif parsed.path.startswith('/api/files'):
            query = parse_qs(parsed.query)
            user_id = int(query.get('user_id', [0])[0])
            files = user_sessions.get(user_id, {}).get('files', {})
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"files": files}).encode())
        
        elif parsed.path.startswith('/api/export_zip'):
            query = parse_qs(parsed.query)
            user_id = int(query.get('user_id', [0])[0])
            files = user_sessions.get(user_id, {}).get('files', {})
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for name, content in files.items():
                    zf.writestr(name, content)
            zip_buffer.seek(0)
            self.send_response(200)
            self.send_header('Content-type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename=project_{user_id}.zip')
            self.end_headers()
            self.wfile.write(zip_buffer.getvalue())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        data = json.loads(body) if body else {}
        
        if self.path == '/api/save_files':
            user_id = data.get('user_id')
            files = data.get('files', {})
            if user_id not in user_sessions:
                user_sessions[user_id] = {}
            user_sessions[user_id]['files'] = files
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
        
        elif self.path == '/api/run':
            result = run_code_safe(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        
        elif self.path == '/api/analyze':
            result = analyze_complexity(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"report": result}).encode())
        
        elif self.path == '/api/bugs':
            bugs = find_bugs(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"report": "\n".join(bugs)}).encode())
        
        elif self.path == '/api/fix':
            fixed, report = auto_fix_code(data.get('code', ''))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"code": fixed, "report": report}).encode())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

# ==================== TELEGRAM БОТ ====================
def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"files": {"main.py": '# Код пуст\nprint("Hello, World!")'}, "current_file": "main.py"}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    # Распознаём несколько файлов из сообщения
    files_from_msg = detect_all_files_from_code(text)
    if files_from_msg:
        for filename, content in files_from_msg.items():
            user_sessions[uid]["files"][filename] = content
        user_sessions[uid]["current_file"] = list(files_from_msg.keys())[0]
        send_message(chat_id, f"✅ Распознано {len(files_from_msg)} файлов:\n" + "\n".join(f"• {name}" for name in files_from_msg.keys()))
        return
    
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю писать и исправлять код!\n\n"
            "*Основные команды:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "📁 /files — управление файлами\n"
            "➕ /add_file — добавить файл\n"
            "🗑 /delete_file — удалить файл\n"
            "🌐 /web — веб-редактор\n"
            "🌍 /view — просмотр кода в браузере\n"
            "❓ /help — помощь",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "/web" or text == "🌐 Веб-редактор":
        send_web_button(chat_id, uid)
    
    elif text == "/view" or text == "🌍 Просмотр":
        send_view_button(chat_id, uid)
    
    elif text == "📁 Файлы" or text == "/files":
        files = user_sessions[uid].get("files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов. Отправьте код или используйте /add_file")
        else:
            file_list = "\n".join([f"• `{name}`" for name in files.keys()])
            send_message(chat_id, f"📁 *Ваши файлы:*\n{file_list}\n\n📄 Текущий: `{user_sessions[uid].get('current_file', 'main.py')}`", parse_mode="Markdown")
            send_message(chat_id, "Выберите файл для редактирования:", reply_markup=json.dumps(get_files_keyboard(files)))
    
    elif text == "➕ Добавить файл" or text == "/add_file":
        send_message(chat_id, "📝 Введите имя файла для добавления (например: `app.py`, `index.html`):", parse_mode="Markdown")
    
    elif text == "🗑 Удалить файл" or text == "/delete_file":
        files = user_sessions[uid].get("files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов для удаления")
        else:
            send_message(chat_id, "🗑 Выберите файл для удаления:", reply_markup=json.dumps(get_files_keyboard(files)))
    
    elif text.startswith("/switch_file "):
        filename = text.split(" ", 1)[1]
        files = user_sessions[uid].get("files", {})
        if filename in files:
            user_sessions[uid]["current_file"] = filename
            send_message(chat_id, f"✅ Переключён на файл: `{filename}`", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Файл `{filename}` не найден", parse_mode="Markdown")
    
    elif text == "📦 Экспорт ZIP":
        files = user_sessions[uid].get("files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов для экспорта")
            return
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        zip_buffer.seek(0)
        with open(f"project_{uid}.zip", "wb") as f:
            f.write(zip_buffer.getvalue())
        with open(f"project_{uid}.zip", "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": "📦 Архив всех файлов"}, files={"document": f})
        os.remove(f"project_{uid}.zip")
    
    elif text == "🔙 Главное меню":
        send_message(chat_id, "🔙 Возврат в главное меню", reply_markup=json.dumps(get_main_keyboard()))
    
    elif text.startswith("📄 "):
        filename = text.replace("📄 ", "")
        files = user_sessions[uid].get("files", {})
        if filename in files:
            user_sessions[uid]["current_file"] = filename
            code = files[filename]
            lang = "python" if filename.endswith('.py') else "text"
            send_message(chat_id, f"📄 *Файл:* `{filename}`\n```{lang}\n{code[:3000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Файл не найден")
    
    elif text.startswith("➕ ") and len(text) > 2:
        filename = text[2:]
        if uid not in user_sessions:
            user_sessions[uid] = {"files": {}}
        user_sessions[uid]["files"][filename] = f"# Файл {filename}\n"
        user_sessions[uid]["current_file"] = filename
        send_message(chat_id, f"✅ Файл `{filename}` создан!", parse_mode="Markdown")
    
    elif text == "📝 Показать код" or text == "/show":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, f"📭 Файл `{current}` пуст. Отправьте код или используйте /add_file", parse_mode="Markdown")
        else:
            lang = "python" if current.endswith('.py') else "text"
            send_message(chat_id, f"📄 *Файл:* `{current}`\n```{lang}\n{code[:3500]}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, f"❌ Файл `{current}` пуст", parse_mode="Markdown")
            return
        with open(current, "w") as f:
            f.write(code)
        with open(current, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": f"✅ {current}"}, files={"document": f})
        os.remove(current)
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, f"📭 Нет кода в файле `{current}`", parse_mode="Markdown")
            return
        send_message(chat_id, "🔧 Исправляю код...")
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["files"][current] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, f"📭 Нет кода в файле `{current}`", parse_mode="Markdown")
            return
        bugs = find_bugs(code)
        send_message(chat_id, "🔍 *Результаты проверки:*\n\n" + "\n".join(bugs), parse_mode="Markdown")
    
    elif text == "📊 Анализ" or text == "/complexity":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, f"📭 Нет кода в файле `{current}`", parse_mode="Markdown")
            return
        analysis = analyze_complexity(code)
        send_message(chat_id, f"📊 *Анализ файла `{current}`:*\n{analysis}", parse_mode="Markdown")
    
    elif text == "🏃 Запустить" or text == "/run":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, f"📭 Нет кода в файле `{current}` для запуска", parse_mode="Markdown")
            return
        send_message(chat_id, "🏃 Запускаю код...")
        result = run_code_safe(code)
        if result["success"]:
            output = result["output"][:3000] if result["output"] else "(нет вывода)"
            send_message(chat_id, f"✅ *Выполнение успешно!*\n```\n{output}\n```", parse_mode="Markdown")
        else:
            error = result["error"][:2000] if result["error"] else "Неизвестная ошибка"
            send_message(chat_id, f"❌ *Ошибка выполнения:*\n```\n{error}\n```", parse_mode="Markdown")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid]["files"] = {"main.py": '# Код пуст\nprint("Hello, World!")'}
        user_sessions[uid]["current_file"] = "main.py"
        send_message(chat_id, "🧹 Все файлы очищены!", reply_markup=json.dumps(get_main_keyboard()))
    
    elif text == "❓ Помощь" or text == "/help":
        send_message(chat_id,
            "📚 *Команды бота:*\n\n"
            "📝 /show — показать текущий файл\n"
            "💾 /done — скачать текущий файл\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "📁 /files — список файлов\n"
            "➕ /add_file — добавить файл\n"
            "🗑 /delete_file — удалить файл\n"
            "🌐 /web — веб-редактор\n"
            "🌍 /view — просмотр кода в браузере\n"
            "🗑 /reset — очистить всё\n"
            "❓ /help — эта справка\n\n"
            "💡 *Отправьте несколько файлов сразу:*\n"
            "```\n### Файл: app.py\n```python\nprint('Hello')\n```\n### Файл: requirements.txt\n```\nflask\n```\n```",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_main_keyboard()))
    
    elif text and not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🏃", "📁", "➕", "🗑", "🌐", "❓", "🔙", "📄", "🌍"]):
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        old_code = files.get(current, "")
        new_code = old_code + "\n\n" + text if old_code else text
        user_sessions[uid]["files"][current] = new_code
        send_message(chat_id, f"✅ *Код добавлен в файл `{current}`!*\n📊 Размер: {len(new_code)} символов", parse_mode="Markdown")

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 Telegram бот запущен!")
    while True:
        try:
            updates = get_updates()
            for upd in updates:
                if upd["update_id"] in processed_ids:
                    continue
                processed_ids.add(upd["update_id"])
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                if "message" in upd:
                    process_message(upd["message"])
                last_update_id = upd["update_id"]
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка бота: {e}")
            time.sleep(5)

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
