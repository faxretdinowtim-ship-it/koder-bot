import os
import re
import json
import logging
import time
import tempfile
import subprocess
import threading
import uuid
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
running_websites = {}

# ==================== ФУНКЦИЯ РАЗБОРА МНОГОФАЙЛОВОГО КОДА ====================
def parse_multifile_code(code):
    """Разбирает код на несколько файлов по маркеру # file: filename"""
    files = {}
    current_file = None
    current_content = []
    
    lines = code.split('\n')
    
    for line in lines:
        # Ищем маркер # file: имя_файла
        match = re.match(r'#\s*file:\s*(.+)', line)
        if match:
            # Сохраняем предыдущий файл
            if current_file and current_content:
                files[current_file] = '\n'.join(current_content).strip()
            # Начинаем новый файл
            current_file = match.group(1).strip()
            current_content = []
        else:
            if current_file:
                current_content.append(line)
    
    # Сохраняем последний файл
    if current_file and current_content:
        files[current_file] = '\n'.join(current_content).strip()
    
    # Если не нашли ни одного маркера, возвращаем исходный код как один файл
    if not files and code.strip():
        # Определяем тип по содержанию
        if code.strip().startswith('<!DOCTYPE html>') or code.strip().startswith('<html'):
            files = {"index.html": code.strip()}
        elif code.strip().startswith('def ') or 'print(' in code or 'import ' in code:
            files = {"main.py": code.strip()}
        else:
            files = {"code.txt": code.strip()}
    
    return files

# ==================== HTML СТРАНИЦА (ВЕБ-РЕДАКТОР) ====================
WEB_EDITOR_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 AI Code Editor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e1e; font-family: monospace; }
        .header { background: #2d2d2d; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .logo { font-size: 20px; font-weight: bold; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .file-select { background: #2d2d2d; padding: 8px 15px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; border-top: 1px solid #444; border-bottom: 1px solid #444; }
        .file-select select { background: #1e1e1e; color: white; padding: 6px 12px; border: 1px solid #555; border-radius: 6px; }
        .file-select button { padding: 6px 12px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 6px; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 6px; }
        button:hover { background: #1177bb; }
        button.primary { background: linear-gradient(135deg, #667eea, #764ba2); }
        button.success { background: #28a745; }
        #editor { height: 55vh; }
        .output { background: #1e1e1e; color: #d4d4d4; padding: 15px; height: 22vh; overflow: auto; font-family: monospace; white-space: pre-wrap; border-top: 1px solid #333; font-size: 12px; }
        .status { background: #1e1e1e; color: #888; padding: 5px 15px; font-size: 12px; text-align: center; }
        .success { color: #6a9955; }
        .error { color: #f48771; }
        .info { color: #569cd6; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/editor/editor.main.min.css">
</head>
<body>
<div class="header">
    <div class="logo">🤖 AI Code Editor</div>
</div>
<div class="file-select">
    <span>📁 Файл:</span>
    <select id="fileSelect" onchange="switchFile()"></select>
    <button onclick="addNewFile()">➕ Новый файл</button>
    <button onclick="exportZip()">📦 Экспорт ZIP</button>
</div>
<div class="toolbar">
    <button class="primary" onclick="syncFromBot()">📥 Загрузить из бота</button>
    <button class="primary" onclick="syncToBot()">💾 Сохранить в бота</button>
    <button class="success" onclick="runWebsite()">🌐 Запустить сайт</button>
    <button onclick="runPython()">▶️ Запустить Python</button>
    <button onclick="analyzeCode()">📊 Анализ</button>
    <button onclick="findBugs()">🐛 Ошибки</button>
    <button onclick="fixCode()">🔧 Исправить</button>
    <button onclick="downloadCode()">📥 Скачать</button>
</div>
<div id="editor"></div>
<div class="output" id="output">⚡ Готов к работе</div>
<div class="status" id="status">⚡ Готов</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.js"></script>
<script>
let editor;
let currentFiles = {};
let currentFileName = "main.py";
const USER_ID = window.location.pathname.split('/')[2];
const API_URL = window.location.origin;

function setOutput(text, type = 'info') {
    const out = document.getElementById('output');
    const cls = type === 'error' ? 'error' : (type === 'success' ? 'success' : 'info');
    out.innerHTML = `<span class="${cls}">${escapeHtml(text)}</span>`;
}

function escapeHtml(t) { return t.replace(/[&<>]/g, function(m) { return {'&':'&amp;','<':'&lt;','>':'&gt;'}[m]; }).replace(/\n/g, '<br>'); }

function updateFileSelect() {
    const select = document.getElementById('fileSelect');
    select.innerHTML = '';
    for (const name in currentFiles) {
        const option = document.createElement('option');
        option.value = name;
        const ext = name.split('.').pop();
        const emoji = ext === 'html' ? '🌐' : (ext === 'py' ? '🐍' : (ext === 'css' ? '🎨' : (ext === 'js' ? '📜' : '📄')));
        option.textContent = `${emoji} ${name}${name === currentFileName ? ' ✅' : ''}`;
        if (name === currentFileName) option.selected = true;
        select.appendChild(option);
    }
}

async function switchFile() {
    const select = document.getElementById('fileSelect');
    currentFileName = select.value;
    editor.setValue(currentFiles[currentFileName] || '# Новый файл');
    setOutput(`📁 Переключён на: ${currentFileName}`, 'success');
}

async function addNewFile() {
    const newName = prompt('Введите имя файла:', 'new_file.py');
    if (!newName) return;
    if (currentFiles[newName]) {
        setOutput('❌ Файл уже существует!', 'error');
        return;
    }
    const ext = newName.split('.').pop();
    const templates = {
        'py': '# Python code\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n',
        'html': '<!DOCTYPE html>\n<html>\n<head><title>My Page</title></head>\n<body>\n<h1>Hello!</h1>\n</body>\n</html>',
        'css': '/* Styles */\nbody { font-family: Arial; margin: 20px; }\n',
        'js': '// JavaScript\nconsole.log("Hello");\n'
    };
    currentFiles[newName] = templates[ext] || '# New file\n';
    currentFileName = newName;
    editor.setValue(currentFiles[currentFileName]);
    updateFileSelect();
    setOutput(`✅ Создан файл: ${newName}`, 'success');
}

async function exportZip() {
    setOutput('📦 Создание ZIP архива...');
    const res = await fetch(API_URL + '/api/export_zip', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, files: currentFiles})
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `project_${USER_ID}.zip`;
    a.click();
    URL.revokeObjectURL(url);
    setOutput('✅ ZIP архив скачан!', 'success');
}

require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '# Загрузка...',
        language: 'python',
        theme: 'vs-dark',
        fontSize: 13,
        minimap: { enabled: true },
        automaticLayout: true,
        fontFamily: 'Fira Code, monospace',
        fontLigatures: true
    });
    syncFromBot();
});

async function syncFromBot() {
    setOutput('⏳ Загрузка...');
    try {
        const res = await fetch(API_URL + '/api/load_all?user_id=' + USER_ID);
        const data = await res.json();
        if (data.files && Object.keys(data.files).length > 0) {
            currentFiles = data.files;
            currentFileName = data.current_file || Object.keys(data.files)[0];
            editor.setValue(currentFiles[currentFileName]);
            updateFileSelect();
            setOutput(`✅ Загружено ${Object.keys(currentFiles).length} файлов`, 'success');
        } else {
            currentFiles = {"main.py": '# Напиши свой код здесь\nprint("Hello, World!")'};
            currentFileName = "main.py";
            editor.setValue(currentFiles[currentFileName]);
            updateFileSelect();
            setOutput('📭 Новый проект создан', 'info');
        }
    } catch(e) { setOutput('❌ Ошибка загрузки', 'error'); }
}

async function syncToBot() {
    currentFiles[currentFileName] = editor.getValue();
    setOutput('⏳ Сохранение...');
    await fetch(API_URL + '/api/save_all', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, files: currentFiles, current_file: currentFileName})
    });
    setOutput(`✅ Сохранено ${Object.keys(currentFiles).length} файлов`, 'success');
}

async function runWebsite() {
    const code = editor.getValue();
    const ext = currentFileName.split('.').pop();
    if (ext === 'html') {
        const res = await fetch(API_URL + '/api/run_website', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({code: code})
        });
        const data = await res.json();
        if (data.url) {
            setOutput(`🌐 Сайт запущен: ${data.url}\n\nОткрывай в браузере!`, 'success');
            window.open(data.url, '_blank');
        } else {
            setOutput('❌ Ошибка запуска', 'error');
        }
    } else {
        setOutput('⚠️ Это не HTML файл. Создай .html файл для запуска сайта.', 'error');
    }
}

async function runPython() {
    const code = editor.getValue();
    if (!code.trim()) { setOutput('❌ Нет кода', 'error'); return; }
    setOutput('⏳ Выполнение...');
    const res = await fetch(API_URL + '/api/run', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    if (data.success) {
        setOutput(data.output || '✅ Выполнено!', 'success');
    } else {
        setOutput('❌ ' + (data.error || 'Ошибка'), 'error');
    }
}

async function analyzeCode() {
    const code = editor.getValue();
    const res = await fetch(API_URL + '/api/analyze', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    setOutput('📊 ' + data.report, 'info');
}

async function findBugs() {
    const code = editor.getValue();
    const res = await fetch(API_URL + '/api/bugs', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    setOutput('🐛 ' + data.report, data.report.includes('✅') ? 'success' : 'error');
}

async function fixCode() {
    const code = editor.getValue();
    setOutput('🔧 Исправление...');
    const res = await fetch(API_URL + '/api/fix', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: code})
    });
    const data = await res.json();
    editor.setValue(data.code);
    currentFiles[currentFileName] = data.code;
    setOutput(data.report, 'success');
}

function downloadCode() {
    const code = editor.getValue();
    const blob = new Blob([code], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = currentFileName;
    a.click();
}
</script>
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
    if re.search(r'except\s*:', code):
        bugs.append("❌ Голый except")
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        bugs.append(f"❌ Синтаксис: {e.msg}")
    return bugs if bugs else ["✅ Ошибок не найдено!"]

def analyze_complexity(code):
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    return f"Строк кода: {code_lines} | Функций: {functions} | Ветвлений: {branches}"

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

# ==================== HTTP СЕРВЕР ====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path.startswith('/web/'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(WEB_EDITOR_HTML.encode('utf-8'))
        
        elif parsed.path.startswith('/run/'):
            site_id = parsed.path.split('/')[2]
            if site_id in running_websites:
                html_content = running_websites[site_id]
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Site not found')
        
        elif parsed.path == '/' or parsed.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running!')
        
        elif parsed.path.startswith('/api/load_all'):
            query = parse_qs(parsed.query)
            user_id = int(query.get('user_id', [0])[0])
            data = user_sessions.get(user_id, {})
            files = data.get('files', {"main.py": '# Напиши свой код здесь\nprint("Hello, World!")'})
            current_file = data.get('current_file', 'main.py')
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"files": files, "current_file": current_file}).encode())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        data = json.loads(body) if body else {}
        
        if self.path == '/api/save_all':
            user_id = data.get('user_id')
            files = data.get('files', {})
            current_file = data.get('current_file', 'main.py')
            if user_id not in user_sessions:
                user_sessions[user_id] = {}
            user_sessions[user_id]['files'] = files
            user_sessions[user_id]['current_file'] = current_file
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode())
        
        elif self.path == '/api/run_website':
            code = data.get('code', '')
            site_id = str(uuid.uuid4())[:8]
            running_websites[site_id] = code
            bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"url": f"{bot_url}/run/{site_id}"}).encode())
        
        elif self.path == '/api/export_zip':
            files = data.get('files', {})
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for name, content in files.items():
                    zf.writestr(name, content)
            zip_buffer.seek(0)
            self.send_response(200)
            self.send_header('Content-type', 'application/zip')
            self.end_headers()
            self.wfile.write(zip_buffer.getvalue())
        
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
def get_keyboard():
    return {
        "keyboard": [
            ["🌐 Открыть сайт", "📝 Показать код"],
            ["📁 Файлы", "📦 Экспорт ZIP"],
            ["🌐 Запустить сайт", "▶️ Запустить Python"],
            ["🔧 ИСПРАВИТЬ", "🐛 Ошибки"],
            ["📊 Анализ", "🗑 Очистить всё"]
        ],
        "resize_keyboard": True
    }

def process_message(msg):
    chat_id = msg["chat"]["id"]
    uid = msg["from"]["id"]
    text = msg.get("text", "")
    
    if uid not in user_sessions:
        user_sessions[uid] = {"files": {"main.py": '# Напиши свой код здесь\nprint("Hello, World!")'}, "current_file": "main.py"}
    
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    
    if text == "/start":
        send_message(chat_id, "🤖 *AI Code Bot*\n\nПришли код - я сохраню!\n\n📁 /files - список файлов\n🌐 /run_website - запустить HTML как сайт\n📦 /export - скачать ZIP\n\n💡 *Отправь код с маркерами:*\n```\n# file: index.html\n<!DOCTYPE html>...\n\n# file: style.css\nbody {...}\n```", parse_mode="Markdown", reply_markup=json.dumps(get_keyboard()))
    
    elif text == "/site" or text == "🌐 Открыть сайт":
        send_message(chat_id, f"🌐 *Твой код в редакторе:*\n{bot_url}/web/{uid}", parse_mode="Markdown")
    
    elif text == "📁 Файлы" or text == "/files":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        if not files:
            send_message(chat_id, "📭 Нет файлов")
        else:
            file_list = "\n".join([f"• `{name}` ✅" if name == current else f"• `{name}`" for name in files.keys()])
            send_message(chat_id, f"📁 *Файлы проекта ({len(files)}):*\n{file_list}\n\n/switch_file <имя> - переключиться\n/add_file <имя> - добавить", parse_mode="Markdown")
    
    elif text.startswith("/switch_file"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "📝 Использование: `/switch_file main.py`", parse_mode="Markdown")
        else:
            filename = parts[1]
            files = user_sessions[uid].get("files", {})
            if filename in files:
                user_sessions[uid]["current_file"] = filename
                send_message(chat_id, f"✅ Переключён на `{filename}`", parse_mode="Markdown")
            else:
                send_message(chat_id, f"❌ Файл `{filename}` не найден")
    
    elif text.startswith("/add_file"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "📝 Использование: `/add_file index.html`", parse_mode="Markdown")
        else:
            filename = parts[1]
            files = user_sessions[uid].get("files", {})
            if filename in files:
                send_message(chat_id, f"❌ Файл `{filename}` уже существует")
            else:
                ext = filename.split('.')[-1] if '.' in filename else 'txt'
                templates = {
                    'py': '# Python code\ndef main():\n    pass\n',
                    'html': '<!DOCTYPE html>\n<html>\n<head><title>My Page</title></head>\n<body>\n<h1>Hello!</h1>\n</body>\n</html>',
                    'css': '/* Styles */\nbody { font-family: Arial; }\n',
                    'js': '// JavaScript\nconsole.log("Hello");\n'
                }
                files[filename] = templates.get(ext, f'# {filename}\n')
                user_sessions[uid]["files"] = files
                send_message(chat_id, f"✅ Файл `{filename}` создан!\n/switch_file {filename} - начать редактировать")
    
    elif text == "📦 Экспорт ZIP" or text == "/export":
        files = user_sessions[uid].get("files", {})
        if not files:
            send_message(chat_id, "📭 Нет файлов для экспорта")
            return
        
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        zip_buffer.seek(0)
        
        # Отправляем ZIP файл
        import requests as req
        req.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": "📦 Архив проекта"}, files={"document": zip_buffer})
        send_message(chat_id, "✅ ZIP архив отправлен!")
    
    elif text == "📝 Показать код" or text == "/show":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        send_message(chat_id, f"```{code[:3000] if code else '# Пусто'}\n```", parse_mode="Markdown")
    
    elif text == "🌐 Запустить сайт" or text == "/run_website":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        
        if current.endswith('.html'):
            site_id = str(uuid.uuid4())[:8]
            running_websites[site_id] = code
            send_message(chat_id, f"🌐 *Твой сайт запущен!*\n\nОткрывай в браузере:\n{bot_url}/run/{site_id}", parse_mode="Markdown")
        else:
            send_message(chat_id, "⚠️ Это не HTML файл. Создай .html файл командой `/add_file index.html`", parse_mode="Markdown")
    
    elif text == "▶️ Запустить Python" or text == "/run":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода для запуска")
            return
        send_message(chat_id, "⏳ Выполнение...")
        result = run_code_safe(code)
        if result["success"]:
            send_message(chat_id, f"✅ Выполнено!\n```\n{result['output'][:2000]}\n```", parse_mode="Markdown")
        else:
            send_message(chat_id, f"❌ Ошибка:\n```\n{result['error'][:2000]}\n```", parse_mode="Markdown")
    
    elif text == "🔧 ИСПРАВИТЬ" or text == "/fix":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        code = files.get(current, "")
        if not code.strip():
            send_message(chat_id, "📭 Нет кода")
            return
        fixed, report = auto_fix_code(code)
        if fixed != code:
            files[current] = fixed
            user_sessions[uid]["files"] = files
            send_message(chat_id, report)
        else:
            send_message(chat_id, "✅ Код уже в хорошем состоянии!")
    
    elif text == "🐛 Ошибки" or text == "/bugs":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        bugs = find_bugs(files.get(current, ""))
        send_message(chat_id, "\n".join(bugs))
    
    elif text == "📊 Анализ" or text == "/complexity":
        files = user_sessions[uid].get("files", {})
        current = user_sessions[uid].get("current_file", "main.py")
        analysis = analyze_complexity(files.get(current, ""))
        send_message(chat_id, f"📊 {analysis}")
    
    elif text == "🗑 Очистить всё" or text == "/reset":
        user_sessions[uid] = {"files": {"main.py": '# Напиши свой код здесь\nprint("Hello, World!")'}, "current_file": "main.py"}
        send_message(chat_id, "🧹 Всё очищено!")
    
    elif not text.startswith("/") and not any(text.startswith(x) for x in ["🌐", "📝", "📁", "📦", "🔧", "🐛", "🗑", "▶️", "📊"]):
        send_message(chat_id, "🧠 Анализирую код...")
        
        # Пробуем разобрать на несколько файлов
        parsed_files = parse_multifile_code(text)
        
        if len(parsed_files) > 1:
            # Сохраняем все файлы
            user_sessions[uid]["files"] = parsed_files
            user_sessions[uid]["current_file"] = list(parsed_files.keys())[0]
            file_list = ", ".join(parsed_files.keys())
            send_message(chat_id, f"✅ Разобрано {len(parsed_files)} файлов: {file_list}\n\n📁 /files - посмотреть все\n🌐 Запустить сайт - открыть HTML", parse_mode="Markdown")
        else:
            # Обычный код - добавляем в текущий файл
            files = user_sessions[uid].get("files", {})
            current = user_sessions[uid].get("current_file", "main.py")
            if current not in files:
                files[current] = ""
            old_code = files[current]
            new_code = old_code + "\n\n" + text if old_code else text
            files[current] = new_code
            user_sessions[uid]["files"] = files
            send_message(chat_id, f"✅ Сохранено в `{current}`! {len(new_code)} символов\n\n📁 /files - список файлов\n🔧 /fix - исправить ошибки", parse_mode="Markdown")

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

def run_web():
    server = HTTPServer(('0.0.0.0', PORT), WebHandler)
    logger.info(f"🌐 Веб-сервер на порту {PORT}")
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
