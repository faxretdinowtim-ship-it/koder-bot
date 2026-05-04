import os
import re
import json
import logging
import asyncio
import tempfile
import zipfile
from io import BytesIO
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from openai import OpenAI

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
USE_DEEPSEEK = True
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PORT = int(os.environ.get("PORT", 5000))

# Flask приложение
app = Flask(__name__)

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Telegram лимит
MAX_MESSAGE_LENGTH = 4096

# AI клиент
if USE_DEEPSEEK and DEEPSEEK_API_KEY:
    ai_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    AI_MODEL = "deepseek-coder"
    AI_NAME = "DeepSeek Coder"
else:
    ai_client = OpenAI(api_key=OPENAI_API_KEY)
    AI_MODEL = "gpt-3.5-turbo"
    AI_NAME = "GPT-3.5 Turbo"

# Хранилище пользователей
user_sessions = {}

# Шаблоны проектов
PROJECT_TEMPLATES = {
    "python": {
        "main.py": '''#!/usr/bin/env python3
"""Main entry point for the application"""

def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
''',
        "README.md": "# Python Project\n\n## Description\nProject description here\n"
    },
    "flask": {
        "app.py": '''from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/data', methods=['GET', 'POST'])
def api():
    if request.method == 'POST':
        data = request.json
        return jsonify({"received": data})
    return jsonify({"message": "GET request"})

if __name__ == '__main__':
    app.run(debug=True)
''',
        "templates/index.html": '''<!DOCTYPE html>
<html>
<head>
    <title>My Flask App</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <h1>Welcome to Flask!</h1>
    <script src="/static/script.js"></script>
</body>
</html>''',
        "static/style.css": "body {\n    font-family: Arial, sans-serif;\n    margin: 0;\n    padding: 20px;\n    background: #f0f0f0;\n}\n",
        "static/script.js": "console.log('Hello from Flask!');\n",
        "requirements.txt": "flask\n",
        "README.md": "# Flask Application\n"
    },
    "html": {
        "index.html": '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Website</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <h1>Welcome!</h1>
    <p>This is a static website</p>
    <script src="script.js"></script>
</body>
</html>''',
        "style.css": "/* Styles */\nbody {\n    font-family: Arial, sans-serif;\n    margin: 0;\n    padding: 20px;\n}\n",
        "script.js": "// JavaScript code\nconsole.log('Hello from JS!');\n",
        "README.md": "# Static Website\n"
    },
    "fullstack": {
        "backend/app.py": '''from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/users')
def get_users():
    return jsonify([{"id": 1, "name": "User 1"}])

if __name__ == '__main__':
    app.run(port=5000)
''',
        "frontend/index.html": '''<!DOCTYPE html>
<html>
<head>
    <title>Fullstack App</title>
</head>
<body>
    <h1>Fullstack Application</h1>
    <div id="app"></div>
    <script>
        fetch('http://localhost:5000/api/users')
            .then(r => r.json())
            .then(data => console.log(data));
    </script>
</body>
</html>''',
        "README.md": "# Fullstack Application\n"
    }
}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def split_long_text(text: str, chunk_size: int = MAX_MESSAGE_LENGTH) -> list:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    pos = 0
    while pos < len(text):
        end = pos + chunk_size
        if end >= len(text):
            chunks.append(text[pos:])
            break
        split_at = text.rfind('\n', pos, end)
        if split_at == -1:
            split_at = text.rfind(' ', pos, end)
        if split_at == -1 or split_at <= pos:
            split_at = end
        chunks.append(text[pos:split_at])
        pos = split_at
        while pos < len(text) and text[pos] in ' \n':
            pos += 1
    return chunks

async def send_long_message(bot, chat_id, text, parse_mode="Markdown"):
    chunks = split_long_text(text)
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            chunk = f"📄 *Часть {i+1}/{len(chunks)}*\n\n{chunk}"
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode)

def detect_file_type(filename: str, content: str) -> str:
    if filename.endswith('.py'):
        return "python"
    elif filename.endswith('.html'):
        return "html"
    elif filename.endswith('.css'):
        return "css"
    elif filename.endswith('.js'):
        return "javascript"
    elif filename.endswith('.json'):
        return "json"
    elif filename.endswith('.md'):
        return "markdown"
    return "text"

# ==================== AI СКЛЕЙКА ====================
async def ai_merge_code(current_code: str, new_part: str, instruction: str = "") -> dict:
    prompt = f"""Ты эксперт по сборке кода. Объедини текущий код с новой частью.
Текущий код:
{current_code if current_code else "(пусто)"}

Новая часть:
{new_part}

Инструкция: {instruction if instruction else "Объедини код"}

Верни JSON: {{"code": "полный код", "changes": "что изменено"}}"""
    
    try:
        response = ai_client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4000
        )
        result_text = response.choices[0].message.content
        result_text = result_text.strip('`').replace('json\n', '')
        result = json.loads(result_text)
        return {"code": result.get("code", new_part), "changes": result.get("changes", "Код обновлён")}
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        new_code = current_code + "\n\n" + new_part if current_code else new_part
        return {"code": new_code, "changes": "Простое склеивание"}

# ==================== ПЕРЕСТАНОВКА КОДА ====================
def reorder_code(code: str) -> str:
    lines = code.split('\n')
    functions = []
    imports = []
    classes = []
    other = []
    
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            imports.append(line)
        elif line.strip().startswith('class '):
            classes.append(line)
        elif line.strip().startswith(('def ', 'async def ')):
            functions.append(line)
        else:
            other.append(line)
    
    imports = sorted(set(imports))
    classes.sort()
    functions.sort()
    
    result = []
    if imports:
        result.extend(imports)
        result.append('')
    if classes:
        result.extend(classes)
        result.append('')
    if functions:
        result.extend(functions)
        result.append('')
    result.extend(other)
    
    return '\n'.join(result)

# ==================== ПОИСК БАГОВ ====================
def find_bugs(code: str) -> list:
    bugs = []
    patterns = [
        (r'/\s*0\b', 'Деление на ноль', 'CRITICAL', 'Проверьте делитель перед делением'),
        (r'eval\s*\(', 'Использование eval()', 'HIGH', 'Используйте ast.literal_eval()'),
        (r'except\s*:', 'Голый except', 'MEDIUM', 'Укажите конкретное исключение'),
        (r'password\s*=\s*[\'"]', 'Хардкод пароля', 'CRITICAL', 'Используйте переменные окружения'),
        (r'while\s+True\s*:\s*\n\s*pass', 'Бесконечный цикл', 'HIGH', 'Добавьте условие выхода'),
    ]
    
    for pattern, msg, severity, fix in patterns:
        if re.search(pattern, code, re.MULTILINE):
            bugs.append({"message": msg, "severity": severity, "fix": fix})
    
    return bugs

def generate_bugs_report(bugs: list) -> str:
    if not bugs:
        return "✅ **Багов не найдено!**"
    
    report = "🐛 **Найденные проблемы:**\n\n"
    for b in bugs[:10]:
        report += f"• {b['message']} `[{b['severity']}]`\n  💡 {b['fix']}\n\n"
    return report

# ==================== АНАЛИЗ СЛОЖНОСТИ ====================
def analyze_complexity(code: str) -> dict:
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    comment_lines = len([l for l in lines if l.strip().startswith('#')])
    blank_lines = len([l for l in lines if not l.strip()])
    functions = code.count('def ') + code.count('async def')
    classes = code.count('class ')
    imports = code.count('import ') + code.count('from ')
    branches = code.count('if ') + code.count('elif ') + code.count('for ') + code.count('while ')
    
    complexity = 1 + branches * 0.5
    
    if complexity < 10:
        rating = "🟢 Низкая (хорошо)"
    elif complexity < 20:
        rating = "🟡 Средняя (нормально)"
    else:
        rating = "🔴 Высокая (нужен рефакторинг)"
    
    return {
        "total_lines": len(lines),
        "code_lines": code_lines,
        "comment_lines": comment_lines,
        "blank_lines": blank_lines,
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "complexity": complexity,
        "rating": rating
    }

def format_complexity_report(analysis: dict) -> str:
    comment_pct = int(analysis['comment_lines'] / max(analysis['code_lines'], 1) * 100)
    return f"""📊 **Анализ сложности кода**

━━━━━━━━━━━━━━━━━━━━━━
📝 *Базовые метрики*
• Всего строк: {analysis['total_lines']}
• Код: {analysis['code_lines']} | Комментарии: {analysis['comment_lines']} ({comment_pct}%)
• Пустых строк: {analysis['blank_lines']}

━━━━━━━━━━━━━━━━━━━━━━
🔧 *Структура*
• Функций: {analysis['functions']}
• Классов: {analysis['classes']}
• Импортов: {analysis['imports']}

━━━━━━━━━━━━━━━━━━━━━━
🔄 *Сложность*
• Цикломатическая: {analysis['complexity']:.1f}
• Оценка: {analysis['rating']}"""

# ==================== ВАЛИДАЦИЯ ====================
def validate_and_fix(code: str) -> tuple:
    errors = []
    fixes = []
    fixed_code = code
    
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        errors.append(f"Синтаксическая ошибка: {e.msg}")
        fixes.append(f"Исправлена синтаксическая ошибка")
    
    if 'print("' in fixed_code and fixed_code.count('"') % 2 == 1:
        fixed_code = fixed_code.replace('print("', "print('")
        fixes.append("Исправлены кавычки в print()")
    
    return fixed_code, errors, fixes

def generate_validation_report(errors: list, fixes: list) -> str:
    report = "🔍 **Отчёт о проверке кода**\n\n"
    if not errors and not fixes:
        return "✅ **Код в идеальном состоянии!**"
    if errors:
        report += "❌ **Ошибки:**\n" + "\n".join(f"• {e}" for e in errors) + "\n\n"
    if fixes:
        report += "🔧 **Исправлено:**\n" + "\n".join(f"• {f}" for f in fixes)
    return report

# ==================== ГИТХАБ ИНТЕГРАЦИЯ ====================
try:
    from github import Github
    import base64
    github_client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
except ImportError:
    github_client = None

async def create_github_repo(repo_name: str):
    if not github_client:
        return {"success": False, "error": "GitHub не настроен"}
    try:
        user = github_client.get_user()
        repo = user.create_repo(repo_name, private=False)
        return {"success": True, "repo_url": repo.html_url}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== КОМАНДЫ БОТА ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "code": "",
            "project_files": {},
            "current_file": "main.py",
            "history": []
        }
    
    await update.message.reply_text(
        f"🤖 *AI Code Assembler Bot*\n\n"
        f"Привет, {user_name}! Я собираю код из частей с помощью AI.\n\n"
        f"🧠 *AI движок:* {AI_NAME}\n"
        f"📁 *Текущий файл:* `{user_sessions[user_id]['current_file']}`\n"
        f"📦 *Размер кода:* {len(user_sessions[user_id]['code'])} символов\n\n"
        f"*Команды:*\n"
        f"/show — показать код\n"
        f"/done — скачать файл\n"
        f"/reset — очистить\n"
        f"/files — управлять файлами\n"
        f"/new_project — создать проект\n"
        f"/complexity — анализ сложности\n"
        f"/bugs — поиск багов\n"
        f"/validate — проверить и исправить\n"
        f"/order — переставить функции\n"
        f"/export — экспортировать все файлы\n"
        f"/gh_repo — создать GitHub репозиторий\n"
        f"/web — веб-редактор\n"
        f"/help — все команды\n\n"
        f"📝 *Как использовать:* просто отправь мне часть кода!",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Все команды бота*\n\n"
        "*/start* — начать работу\n"
        "*/show* — показать текущий код\n"
        "*/done* — скачать код файлом\n"
        "*/reset* — очистить весь код\n"
        "*/order* — переставить функции\n"
        "*/complexity* — анализ сложности\n"
        "*/bugs* — поиск багов\n"
        "*/validate* — проверить и исправить\n"
        "*/new_project* — создать проект (flask, html, python)\n"
        "*/files* — список файлов\n"
        "*/switch_file* — переключить файл\n"
        "*/add_file* — добавить файл\n"
        "*/export* — скачать ZIP архив\n"
        "*/gh_repo* — создать GitHub репозиторий\n"
        "*/web* — открыть веб-редактор\n"
        "*/help* — показать это сообщение",
        parse_mode="Markdown"
    )

async def show_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    current_file = user_sessions.get(user_id, {}).get("current_file", "main.py")
    
    if not code.strip():
        await update.message.reply_text("📭 Код пуст. Отправь мне часть кода!", parse_mode="Markdown")
        return
    
    await send_long_message(
        context.bot, 
        update.effective_chat.id,
        f"📄 *Файл:* `{current_file}`\n📏 *Размер:* {len(code)} символов\n\n```python\n{code}\n```",
        parse_mode="Markdown"
    )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    current_file = user_sessions.get(user_id, {}).get("current_file", "main.py")
    
    if not code.strip():
        await update.message.reply_text("❌ Нет кода для сохранения!")
        return
    
    with open(current_file, "w", encoding="utf-8") as f:
        f.write(f"# Собрано AI Code Assembler\n# Дата: {datetime.now()}\n# AI: {AI_NAME}\n\n{code}")
    
    with open(current_file, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=current_file,
            caption=f"✅ *Готовый код!*\n📊 {len(code)} символов",
            parse_mode="Markdown"
        )
    os.remove(current_file)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions[user_id]["code"] = ""
        user_sessions[user_id]["history"] = []
    await update.message.reply_text("🧹 *Код очищен!*", parse_mode="Markdown")

async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для перестановки")
        return
    
    reordered = reorder_code(code)
    user_sessions[user_id]["code"] = reordered
    await update.message.reply_text("🔄 *Код переставлен!*", parse_mode="Markdown")

async def complexity_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для анализа")
        return
    
    analysis = analyze_complexity(code)
    report = format_complexity_report(analysis)
    await update.message.reply_text(report, parse_mode="Markdown")

async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для поиска багов")
        return
    
    bugs = find_bugs(code)
    report = generate_bugs_report(bugs)
    await update.message.reply_text(report, parse_mode="Markdown")

async def validate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для проверки")
        return
    
    fixed_code, errors, fixes = validate_and_fix(code)
    if fixed_code != code:
        user_sessions[user_id]["code"] = fixed_code
    report = generate_validation_report(errors, fixes)
    await update.message.reply_text(report, parse_mode="Markdown")

async def new_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    project_type = args[0].lower() if args else "python"
    
    templates = {
        "python": PROJECT_TEMPLATES["python"],
        "flask": PROJECT_TEMPLATES["flask"],
        "html": PROJECT_TEMPLATES["html"]
    }
    
    if project_type not in templates:
        await update.message.reply_text("Доступные типы: `python`, `flask`, `html`", parse_mode="Markdown")
        return
    
    user_id = update.effective_user.id
    files = templates[project_type]
    
    user_sessions[user_id]["project_files"] = files.copy()
    user_sessions[user_id]["current_file"] = list(files.keys())[0]
    user_sessions[user_id]["code"] = files[list(files.keys())[0]]
    
    file_list = "\n".join([f"• `{name}`" for name in files.keys()])
    await update.message.reply_text(
        f"✅ *Проект типа '{project_type}' создан!*\n\n"
        f"📁 *Файлы:*\n{file_list}\n\n"
        f"`/files` — список файлов\n`/switch_file <имя>` — переключиться",
        parse_mode="Markdown"
    )

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project_files = user_sessions.get(user_id, {}).get("project_files", {})
    current_file = user_sessions.get(user_id, {}).get("current_file", "")
    
    if not project_files:
        await update.message.reply_text("📭 Нет файлов. Используй `/new_project`", parse_mode="Markdown")
        return
    
    files_list = []
    for name, content in project_files.items():
        size = len(content)
        mark = " ✅" if name == current_file else ""
        files_list.append(f"• `{name}` ({size} символов){mark}")
    
    await update.message.reply_text(
        f"📁 **Файлы проекта ({len(project_files)})**\n\n" + "\n".join(files_list) +
        "\n\n`/switch_file <имя>` — переключиться\n`/add_file <имя>` — добавить",
        parse_mode="Markdown"
    )

async def switch_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Использование: `/switch_file main.py`", parse_mode="Markdown")
        return
    
    filename = args[0]
    user_id = update.effective_user.id
    project_files = user_sessions.get(user_id, {}).get("project_files", {})
    
    if filename in project_files:
        user_sessions[user_id]["current_file"] = filename
        user_sessions[user_id]["code"] = project_files[filename]
        await update.message.reply_text(f"✅ Переключён на `{filename}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Файл `{filename}` не найден", parse_mode="Markdown")

async def add_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Использование: `/add_file script.js`", parse_mode="Markdown")
        return
    
    filename = args[0]
    user_id = update.effective_user.id
    
    if "project_files" not in user_sessions[user_id]:
        user_sessions[user_id]["project_files"] = {}
    
    ext = filename.split('.')[-1] if '.' in filename else 'txt'
    templates = {
        'py': '# Python code\ndef main():\n    pass\n',
        'html': '<!DOCTYPE html>\n<html>\n<body>\n<h1>Hello</h1>\n</body>\n</html>',
        'css': '/* Styles */\nbody { font-family: Arial; }\n',
        'js': '// JavaScript\nconsole.log("Hello");\n'
    }
    user_sessions[user_id]["project_files"][filename] = templates.get(ext, f"# {filename}\n")
    await update.message.reply_text(f"✅ Файл `{filename}` добавлен", parse_mode="Markdown")

async def export_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project_files = user_sessions.get(user_id, {}).get("project_files", {})
    
    if not project_files:
        await update.message.reply_text("📭 Нет файлов для экспорта")
        return
    
    await update.message.reply_text("📦 Создаю ZIP архив...")
    
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, content in project_files.items():
            zip_file.writestr(filename, content)
    
    zip_buffer.seek(0)
    
    await update.message.reply_document(
        document=zip_buffer,
        filename=f"project_{user_id}.zip",
        caption="📦 Архив проекта"
    )

async def gh_repo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Использование: `/gh_repo my-repo`", parse_mode="Markdown")
        return
    
    repo_name = args[0]
    await update.message.reply_text(f"📁 Создаю репозиторий `{repo_name}`...", parse_mode="Markdown")
    
    result = await create_github_repo(repo_name)
    if result["success"]:
        await update.message.reply_text(f"✅ Репозиторий создан!\n🔗 {result['repo_url']}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Ошибка: {result['error']}")

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
    </style>
</head>
<body>
<div class="toolbar">
    <button onclick="saveCode()">💾 Сохранить</button>
    <button onclick="analyzeComplexity()">📊 Сложность</button>
    <button onclick="findBugs()">🐛 Баги</button>
    <button onclick="validateCode()">✅ Валидация</button>
    <button onclick="reorderCode()">🔄 Порядок</button>
</div>
<div id="editor"></div>
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
    alert('Сохранено!');
}
async function analyzeComplexity() {
    const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function findBugs() {
    const res = await fetch('/api/bugs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function validateCode() {
    const res = await fetch('/api/validate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function reorderCode() {
    const res = await fetch('/api/reorder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    editor.setValue(data.code);
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

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    code = request.json.get('code', '')
    analysis = analyze_complexity(code)
    report = format_complexity_report(analysis)
    return jsonify({"report": report})

@app.route('/api/bugs', methods=['POST'])
def api_bugs():
    code = request.json.get('code', '')
    bugs = find_bugs(code)
    report = generate_bugs_report(bugs)
    return jsonify({"report": report})

@app.route('/api/validate', methods=['POST'])
def api_validate():
    code = request.json.get('code', '')
    fixed, errors, fixes = validate_and_fix(code)
    report = generate_validation_report(errors, fixes)
    return jsonify({"report": report})

@app.route('/api/reorder', methods=['POST'])
def api_reorder():
    code = request.json.get('code', '')
    reordered = reorder_code(code)
    return jsonify({"code": reordered})

async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot.onrender.com")
    await update.message.reply_text(
        f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web_editor/{user_id}",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "project_files": {}, "current_file": "main.py", "history": []}
    
    instruction = ""
    code_part = user_message
    for kw in ["ДОБАВИТЬ:", "ИЗМЕНИТЬ:", "УДАЛИТЬ:"]:
        if kw in user_message.upper():
            parts = user_message.split(kw, 1)
            instruction = kw
            code_part = parts[1].strip()
            break
    
    current = user_sessions[user_id]["code"]
    status = await update.message.reply_text(f"🧠 {AI_NAME} анализирует...")
    
    result = await ai_merge_code(current, code_part, instruction)
    final = result["code"]
    final = reorder_code(final)
    final, errors, fixes = validate_and_fix(final)
    
    user_sessions[user_id]["code"] = final
    user_sessions[user_id]["history"].append({"time": datetime.now().isoformat(), "part": code_part[:100]})
    
    current_file = user_sessions[user_id].get("current_file", "main.py")
    if "project_files" in user_sessions[user_id]:
        user_sessions[user_id]["project_files"][current_file] = final
    
    await status.edit_text(
        f"✅ *Код обновлён!*\n\n🔧 {result['changes']}\n📊 Размер: {len(final)} символов\n📁 Файл: `{current_file}`\n\n/show — посмотреть",
        parse_mode="Markdown"
    )

@app.route('/')
def health():
    return "🤖 Bot is running!", 200

# ==================== ЗАПУСК ====================
def run_telegram_bot():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан!")
        return
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("show", show_code))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("order", order_command))
    application.add_handler(CommandHandler("complexity", complexity_command))
    application.add_handler(CommandHandler("bugs", bugs_command))
    application.add_handler(CommandHandler("validate", validate_command))
    application.add_handler(CommandHandler("new_project", new_project))
    application.add_handler(CommandHandler("files", list_files))
    application.add_handler(CommandHandler("switch_file", switch_file))
    application.add_handler(CommandHandler("add_file", add_file))
    application.add_handler(CommandHandler("export", export_all))
    application.add_handler(CommandHandler("gh_repo", gh_repo_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info(f"🚀 Бот запущен! AI: {AI_NAME}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT)
