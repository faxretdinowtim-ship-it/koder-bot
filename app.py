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
user_html_pages = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
processed_ids = set()
last_update_id = 0

# ==================== ФУНКЦИЯ СОЗДАНИЯ HTML-СТРАНИЦЫ ====================
def generate_html_page(code, filename="code.py", page_title="Мой код"):
    """Создаёт красивую HTML-страницу с подсветкой кода"""
    
    # Экранируем код для HTML
    escaped_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Определяем язык для подсветки
    language = "python"
    if filename.endswith('.html'):
        language = "html"
    elif filename.endswith('.css'):
        language = "css"
    elif filename.endswith('.js'):
        language = "javascript"
    elif filename.endswith('.json'):
        language = "json"
    elif filename.endswith('.md'):
        language = "markdown"
    
    html_template = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title} - AI Code Bot</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            font-family: 'Segoe UI', monospace;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            background: rgba(0,0,0,0.5);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 20px 30px;
            margin-bottom: 30px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .header h1 {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .header p {{
            color: #888;
            font-size: 14px;
        }}
        .info {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            margin-top: 15px;
        }}
        .info-item {{
            background: rgba(255,255,255,0.1);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
        }}
        .code-block {{
            background: #1e1e1e;
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .code-header {{
            background: #2d2d2d;
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #444;
        }}
        .filename {{
            color: #667eea;
            font-weight: bold;
        }}
        .copy-btn {{
            background: #0e639c;
            border: none;
            color: white;
            padding: 5px 15px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
        }}
        .copy-btn:hover {{
            background: #1177bb;
        }}
        pre {{
            margin: 0;
            padding: 20px;
            overflow-x: auto;
        }}
        code {{
            font-family: 'Fira Code', monospace;
            font-size: 14px;
            line-height: 1.5;
        }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            color: #666;
            font-size: 12px;
        }}
        .badge {{
            display: inline-block;
            background: rgba(102,126,234,0.2);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            color: #667eea;
        }}
        @media (max-width: 768px) {{
            body {{ padding: 20px 15px; }}
            .header h1 {{ font-size: 22px; }}
            pre {{ padding: 15px; }}
            code {{ font-size: 12px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📄 {page_title}</h1>
            <p>Сгенерировано AI Code Bot • {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>
            <div class="info">
                <span class="info-item">📁 Файл: {filename}</span>
                <span class="info-item">🔤 Язык: {language.upper()}</span>
                <span class="info-item">📏 Строк: {len(code.splitlines())}</span>
                <span class="info-item">📦 Размер: {len(code)} символов</span>
            </div>
        </div>
        <div class="code-block">
            <div class="code-header">
                <span class="filename">📄 {filename}</span>
                <button class="copy-btn" onclick="copyCode()">📋 Копировать код</button>
            </div>
            <pre><code class="language-{language}">{escaped_code}</code></pre>
        </div>
        <div class="footer">
            <span class="badge">🤖 Создано с помощью AI Code Bot</span>
        </div>
    </div>
    <script>
        function copyCode() {{
            const code = document.querySelector('code').innerText;
            navigator.clipboard.writeText(code);
            const btn = document.querySelector('.copy-btn');
            btn.innerHTML = '✅ Скопировано!';
            setTimeout(() => btn.innerHTML = '📋 Копировать код', 2000);
        }}
    </script>
</body>
</html>'''
    
    return html_template

# ==================== ФУНКЦИЯ РАСПОЗНАВАНИЯ ФАЙЛОВ ====================
def detect_all_files_from_code(text):
    """Обнаруживает все возможные файлы в сообщении"""
    files = {}
    
    # Формат: ### Файл: app.py ```python ... ```
    file_pattern = r'###\s*Файл:\s*([^\s]+)\s*```(?:\w+)?\n(.*?)```'
    matches = re.findall(file_pattern, text, re.DOTALL | re.IGNORECASE)
    for filename, content in matches:
        files[filename.strip()] = content.strip()
    
    # Поиск по блокам кода
    code_blocks = re.findall(r'```(\w*)\n(.*?)```', text, re.DOTALL)
    known_files = ['app.py', 'main.py', 'requirements.txt', 'Dockerfile', 'index.html', 'style.css', 'script.js', 'README.md']
    
    for lang, content in code_blocks:
        if lang == 'python' or lang == 'py':
            # Ищем имя файла перед блоком
            before = text[:text.find(f'```{lang}')]
            file_match = re.search(r'([\w\.]+\.py)', before)
            if file_match:
                files[file_match.group(1)] = content.strip()
            else:
                files[f'script_{len(files)}.py'] = content.strip()
        elif lang == 'dockerfile':
            files['Dockerfile'] = content.strip()
        elif lang == 'html':
            files['index.html'] = content.strip()
        elif lang == 'css':
            files['style.css'] = content.strip()
        elif lang == 'js':
            files['script.js'] = content.strip()
    
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
        .actions { margin-top: 20px; display: flex; gap: 10px; }
        .btn { padding: 10px 20px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 8px; }
        .btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); }
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
        <button class="btn" onclick="downloadCurrent()">📥 Скачать</button>
        <button class="btn btn-primary" onclick="downloadAll()">📦 Скачать ZIP</button>
    </div>
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
        const first = Object.entries(data.files)[0];
        if (first) showFile(first[0], first[1]);
    } else {
        fileList.innerHTML = '<span style="color:#888;">Нет файлов</span>';
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
    const blob = new Blob([content], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = currentName;
    a.click();
}

async function downloadAll() {
    window.location = `${API_URL}/api/export_zip?user_id=${USER_ID}`;
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
        #editor { height: calc(100vh - 100px); }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 11px; border-top: 1px solid #333; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="header">
    <div class="logo">🤖 AI Code Editor</div>
    <select id="fileSelect" class="file-select" onchange="switchFile()"></select>
    <div class="toolbar">
        <button onclick="saveFile()">💾 Сохранить</button>
        <button onclick="runCode()">▶️ Запустить</button>
        <button onclick="analyzeCode()">📊 Анализ</button>
        <button onclick="findBugs()">🐛 Ошибки</button>
        <button onclick="fixCode()">🔧 Исправить</button>
        <button onclick="newFile()">➕ Новый</button>
        <button onclick="deleteFile()">🗑 Удалить</button>
    </div>
</div>
<div id="editor"></div>
<div class="status"><span id="status">⚡ Готов</span><span id="stats">📝 0</span></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor, currentFile = null;
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
    filesList = data.files || {'main.py': '# Ваш код'};
    
    const select = document.getElementById('fileSelect');
    select.innerHTML = '';
    for (const name in filesList) {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    }
    currentFile = select.value || Object.keys(filesList)[0];
    editor.setValue(filesList[currentFile] || '');
    setLanguage(currentFile);
}

function setLanguage(filename) {
    const ext = filename.split('.').pop();
    const langs = {py:'python', js:'javascript', html:'html', css:'css', json:'json'};
    monaco.editor.setModelLanguage(editor.getModel(), langs[ext] || 'python');
}

async function switchFile() {
    filesList[currentFile] = editor.getValue();
    currentFile = document.getElementById('fileSelect').value;
    editor.setValue(filesList[currentFile] || '');
    setLanguage(currentFile);
}

async function saveFile() {
    filesList[currentFile] = editor.getValue();
    await fetch(`${API_URL}/api/save_files`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, files: filesList})
    });
    document.getElementById('status').innerHTML = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerHTML = '⚡ Готов', 1500);
}

async function runCode() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/run`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    alert(data.success ? '✅ Выполнено!\n\n' + (data.output || '(нет вывода)') : '❌ Ошибка:\n\n' + data.error);
}

async function analyzeCode() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/analyze`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: code})});
    const data = await res.json();
    alert('📊 ' + data.report);
}

async function findBugs() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/bugs`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: code})});
    const data = await res.json();
    alert('🐛 ' + data.report);
}

async function fixCode() {
    const code = filesList['main.py'] || editor.getValue();
    const res = await fetch(`${API_URL}/api/fix`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: code})});
    const data = await res.json();
    filesList['main.py'] = data.code;
    editor.setValue(data.code);
    await saveFile();
    alert(data.report);
}

async function newFile() {
    const name = prompt('Имя файла (app.py, index.html):');
    if (name && !filesList[name]) {
        filesList[name] = '';
        await saveFile();
        loadFiles();
    }
}

async function deleteFile() {
    if (confirm('Удалить файл?')) {
        delete filesList[currentFile];
        await saveFile();
        loadFiles();
    }
}
</script>
</body>
</html>
'''

# ==================== КЛАВИАТУРА ====================
def get_keyboard():
    return {
        "keyboard": [
            ["📝 Показать код", "💾 Скачать код"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["🏃 Запустить", "📊 Анализ"],
            ["📁 Файлы", "➕ Добавить файл"],
            ["🌐 Веб-редактор", "🌍 Опубликовать сайт"],
            ["🗑 Очистить всё", "❓ Помощь"]
        ],
        "resize_keyboard": True
    }

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
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    return f"Строк: {code_lines} | Функций: {code.count('def ')}"

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
        
        elif parsed.path.startswith('/publish/'):
            page_id = parsed.path.split('/')[2]
            html = user_html_pages.get(page_id, "<h1>Страница не найдена</h1>")
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        
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
        user_sessions[uid] = {"files": {"main.py": '# Ваш код\nprint("Hello, World!")'}, "current_file": "main.py"}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    # Распознаём несколько файлов
    files_from_msg = detect_all_files_from_code(text)
    if files_from_msg:
        for filename, content in files_from_msg.items():
            user_sessions[uid]["files"][filename] = content
        send_message(chat_id, f"✅ Распознано {len(files_from_msg)} файлов:\n" + "\n".join(f"• {name}" for name in files_from_msg.keys()))
        return
    
    if text == "/start":
        send_message(chat_id, 
            "🤖 *AI Code Bot*\n\n"
            "Привет! Я помогаю писать и публиковать код!\n\n"
            "*Команды:*\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать код\n"
            "🔧 /fix — исправить ошибки\n"
            "🐛 /bugs — найти ошибки\n"
            "🏃 /run — выполнить код\n"
            "📊 /complexity — анализ сложности\n"
            "📁 /files — управление файлами\n"
            "➕ /add_file — добавить файл\n"
            "🌐 /web — веб-редактор\n"
            "🌍 /publish — ОПУБЛИКОВАТЬ САЙТ\n"
            "🗑 /reset — очистить всё\n"
            "❓ /help — помощь",
            parse_mode="Markdown",
            reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/web" or text == "🌐 Веб-редактор":
        send_message(chat_id, f"🎨 *Веб-редактор:*\n{bot_url}/web/{uid}", parse_mode="Markdown")
    
    elif text == "/publish" or text == "🌍 Опубликовать сайт":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        
        if not code.strip():
            send_message(chat_id, "❌ Нет кода для публикации!")
            return
        
        # Создаём HTML-страницу
        page_id = f"{uid}_{int(time.time())}"
        html_page = generate_html_page(code, current, f"Мой код - {current}")
        user_html_pages[page_id] = html_page
        
        send_message(chat_id, 
            f"✅ *Код опубликован!*\n\n"
            f"🔗 *Ссылка на сайт:*\n{bot_url}/publish/{page_id}\n\n"
            f"📄 Файл: `{current}`\n"
            f"📊 Размер: {len(code)} символов\n\n"
            f"💡 Эту ссылку можно отправить кому угодно!",
            parse_mode="Markdown")
    
    elif text == "📝 Показать код" or text == "/show":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        lang = "python" if current.endswith('.py') else "text"
        send_message(chat_id, f"📄 *{current}*\n```{lang}\n{code[:3000]}\n```", parse_mode="Markdown")
    
    elif text == "💾 Скачать код" or text == "/done":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, "❌ Нет кода")
            return
        with open(current, "w") as f:
            f.write(code)
        with open(current, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id}, files={"document": f})
        os.remove(current)
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            user_sessions[uid]["files"][current] = fixed
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже хороший")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        bugs = find_bugs(code)
        send_message(chat_id, "\n".join(bugs))
    
    elif text == "📊 Анализ" or text == "/complexity":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        send_message(chat_id, analyze_complexity(code))
    
    elif text == "🏃 Запустить" or text == "/run":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, "Нет кода")
            return
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:1000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:1000]}\n```", parse_mode="Markdown")
    
    elif text == "📁 Файлы" or text == "/files":
        files = user_sessions[uid].get("files", {})
        if not files:
            send_message(chat_id, "Нет файлов")
        else:
            file_list = "\n".join([f"• `{name}`" for name in files.keys()])
            send_message(chat_id, f"📁 *Файлы:*\n{file_list}\n\n🌍 /publish - опубликовать текущий файл", parse_mode="Markdown")
    
    elif text == "➕ Добавить файл":
        send_message(chat_id, "Введите имя файла (например: app.py, index.html):")
    
    elif text.startswith("➕ ") and len(text) > 2:
        filename = text[2:]
        user_sessions[uid]["files"][filename] = f"# Файл {filename}\n"
        send_message(chat_id, f"✅ Файл `{filename}` создан!", parse_mode="Markdown")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid]["files"] = {"main.py": '# Ваш код\nprint("Hello, World!")'}
        send_message(chat_id, "Очищено!")
    
    elif text == "❓ Помощь" or text == "/help":
        send_message(chat_id,
            "📚 *Команды:*\n\n"
            "🌍 /publish — ОПУБЛИКОВАТЬ КАК САЙТ\n"
            "📝 /show — показать код\n"
            "💾 /done — скачать\n"
            "🔧 /fix — исправить\n"
            "🐛 /bugs — ошибки\n"
            "🏃 /run — выполнить\n"
            "📊 /complexity — анализ\n"
            "🌐 /web — редактор\n"
            "📁 /files — файлы\n"
            "➕ Добавить файл — создать файл\n"
            "🗑 /reset — очистить",
            parse_mode="Markdown")
    
    elif text and not text.startswith("/") and not any(text.startswith(x) for x in ["📝", "💾", "🔧", "🐛", "📊", "🏃", "📁", "➕", "🗑", "🌐", "❓", "🌍"]):
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        old = files.get(current, "")
        new_code = old + "\n\n" + text if old else text
        user_sessions[uid]["files"][current] = new_code
        send_message(chat_id, f"✅ Код добавлен в `{current}`! {len(new_code)} символов", parse_mode="Markdown")

# ==================== ЗАПУСК ====================
def run_bot():
    global last_update_id
    logger.info("🤖 Бот запущен!")
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
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
