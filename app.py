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
from flask import Flask, request, jsonify, render_template_string, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from openai import OpenAI

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
USE_DEEPSEEK = os.environ.get("USE_DEEPSEEK", "false").lower() == "true"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
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
    """Определяет тип файла"""
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
    elif filename.endswith('.txt'):
        return "text"
    return "unknown"

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
        (r'__import__\(', 'Динамический импорт', 'MEDIUM', 'Используйте обычный import'),
        (r'open\([^)]+\)(?!\s+as)', 'Незакрытый файл', 'MEDIUM', 'Используйте with open() as f:'),
    ]
    
    for pattern, msg, severity, fix in patterns:
        if re.search(pattern, code, re.MULTILINE):
            bugs.append({"message": msg, "severity": severity, "fix": fix})
    
    # Проверка на неиспользуемые импорты
    imports = re.findall(r'^(?:import|from) (\w+)', code, re.MULTILINE)
    for imp in imports:
        if imp not in code.replace(f'import {imp}', ''):
            bugs.append({"message": f"Неиспользуемый импорт: {imp}", "severity": "LOW", "fix": f"Удалите 'import {imp}'"})
    
    return bugs

def generate_bugs_report(bugs: list) -> str:
    if not bugs:
        return "✅ **Багов не найдено!**"
    
    report = "🐛 **Найденные проблемы:**\n\n"
    for b in bugs[:10]:
        report += f"• {b['message']} `[{b['severity']}]`\n  💡 {b['fix']}\n\n"
    
    if len(bugs) > 10:
        report += f"\n_и еще {len(bugs)-10} проблем_"
    
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

# ==================== ВАЛИДАЦИЯ И ИСПРАВЛЕНИЕ ====================
def validate_and_fix(code: str, language: str = "python") -> tuple:
    errors = []
    fixes = []
    fixed_code = code
    
    # Проверка синтаксиса для Python
    if language == "python":
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            errors.append(f"Синтаксическая ошибка: {e.msg} в строке {e.lineno}")
            
            # Исправление частых ошибок
            lines = code.split('\n')
            if e.lineno and e.lineno <= len(lines):
                line = lines[e.lineno - 1]
                
                # Незакрытая скобка
                if '(' in line and line.count('(') > line.count(')'):
                    line += ')'
                    fixes.append(f"Добавлена закрывающая скобка в строке {e.lineno}")
                
                # Незакрытая кавычка
                if line.count('"') % 2 == 1:
                    line += '"'
                    fixes.append(f"Добавлена закрывающая кавычка в строке {e.lineno}")
                
                lines[e.lineno - 1] = line
                fixed_code = '\n'.join(lines)
    
    # Исправление кавычек
    if 'print("' in fixed_code and fixed_code.count('"') % 2 == 1:
        fixed_code = fixed_code.replace('print("', "print('")
        fixes.append("Исправлены кавычки в print()")
    
    # Добавление shebang для Python скриптов
    if language == "python" and not fixed_code.startswith('#!'):
        if 'if __name__ == "__main__"' in fixed_code:
            fixed_code = '#!/usr/bin/env python3\n\n' + fixed_code
            fixes.append("Добавлен shebang #!/usr/bin/env python3")
    
    return fixed_code, errors, fixes

def generate_validation_report(errors: list, fixes: list) -> str:
    report = "🔍 **Отчёт о проверке кода**\n\n"
    
    if not errors and not fixes:
        return "✅ **Код в идеальном состоянии!**\n\nНикаких ошибок не найдено."
    
    if errors:
        report += "❌ **Найденные ошибки:**\n"
        for e in errors:
            report += f"• {e}\n"
        report += "\n"
    
    if fixes:
        report += "🔧 **Автоматически исправлено:**\n"
        for f in fixes:
            report += f"• {f}\n"
    
    return report

# ==================== GITHUB ИНТЕГРАЦИЯ ====================
try:
    from github import Github
    import base64
    github_client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
except ImportError:
    github_client = None

async def create_github_repo(repo_name: str, description: str = ""):
    if not github_client:
        return {"success": False, "error": "GitHub не настроен (требуется GITHUB_TOKEN)"}
    try:
        user = github_client.get_user()
        repo = user.create_repo(repo_name, description=description or "Created via Telegram bot", private=False)
        return {"success": True, "repo_url": repo.html_url, "name": repo.name}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def push_to_github(repo_name: str, file_path: str, content: str, commit_message: str = "Add code from Telegram"):
    if not github_client:
        return {"success": False, "error": "GitHub не настроен"}
    try:
        user = github_client.get_user()
        repo = user.get_repo(repo_name)
        
        encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        
        try:
            file = repo.get_contents(file_path)
            repo.update_file(file_path, commit_message, content, file.sha)
        except:
            repo.create_file(file_path, commit_message, content)
        
        return {"success": True, "file_url": f"https://github.com/{repo.full_name}/blob/main/{file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def create_gist(filename: str, content: str, description: str = ""):
    if not github_client:
        return {"success": False, "error": "GitHub не настроен"}
    try:
        user = github_client.get_user()
        gist = user.create_gist(
            public=False,
            description=description or "Code from Telegram bot",
            files={filename: {"content": content}}
        )
        return {"success": True, "gist_url": gist.html_url, "raw_url": gist.raw_url}
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
            "history": [],
            "project_type": None
        }
    
    keyboard = [
        [InlineKeyboardButton("📝 Показать код", callback_data="show")],
        [InlineKeyboardButton("📥 Скачать код", callback_data="download")],
        [InlineKeyboardButton("🗑 Очистить", callback_data="reset")],
        [InlineKeyboardButton("📁 Управление файлами", callback_data="files")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
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
        f"/gh_push — загрузить на GitHub\n"
        f"/gh_gist — создать Gist\n"
        f"/stats — статистика\n"
        f"/web — веб-редактор\n"
        f"/help — все команды\n\n"
        f"📝 *Как использовать:* просто отправь мне часть кода! AI сам решит — добавить, изменить или удалить.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Все команды бота*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*📝 Основные*\n"
        "*/start* — начать работу\n"
        "*/show* — показать текущий код\n"
        "*/done* — скачать код файлом\n"
        "*/reset* — очистить весь код\n"
        "*/stats* — статистика сессии\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*🔧 Анализ и исправление*\n"
        "*/order* — переставить функции в правильном порядке\n"
        "*/complexity* — анализ сложности кода\n"
        "*/bugs* — поиск багов и уязвимостей\n"
        "*/validate* — проверить и автоматически исправить ошибки\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*📁 Проекты и файлы*\n"
        "*/new_project* — создать новый проект (flask, html, python)\n"
        "*/files* — список всех файлов проекта\n"
        "*/switch_file* — переключиться на другой файл\n"
        "*/add_file* — добавить новый файл\n"
        "*/export* — экспортировать все файлы (ZIP)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*🔗 GitHub*\n"
        "*/gh_repo* — создать репозиторий\n"
        "*/gh_push* — загрузить текущий файл\n"
        "*/gh_gist* — создать Gist\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*🌐 Другое*\n"
        "*/web* — открыть веб-редактор\n"
        "*/help* — показать это сообщение\n\n"
        "💡 *Совет:* При отправке кода можно добавить команду:\n"
        "`ДОБАВИТЬ: ...` или `ИЗМЕНИТЬ: ...` или `УДАЛИТЬ: ...`",
        parse_mode="Markdown"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = user_sessions.get(user_id, {})
    code = data.get("code", "")
    history = data.get("history", [])
    project_files = data.get("project_files", {})
    
    await update.message.reply_text(
        f"📊 *Статистика сессии*\n\n"
        f"• Размер текущего кода: `{len(code)}` символов\n"
        f"• Получено частей: `{len(history)}`\n"
        f"• Файлов в проекте: `{len(project_files)}`\n"
        f"• Текущий файл: `{data.get('current_file', 'main.py')}`\n"
        f"• AI движок: `{AI_NAME}`\n"
        f"• Сессия активна: ✅\n\n"
        f"`/done` — скачать результат\n"
        f"`/export` — скачать все файлы",
        parse_mode="Markdown"
    )

async def show_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    current_file = user_sessions.get(user_id, {}).get("current_file", "main.py")
    
    if not code.strip():
        await update.message.reply_text("📭 Код пуст. Отправь мне часть кода или используй `/new_project`", parse_mode="Markdown")
        return
    
    file_type = detect_file_type(current_file, code)
    lang_map = {"python": "python", "html": "html", "css": "css", "javascript": "javascript", "json": "json"}
    
    await send_long_message(
        context.bot, 
        update.effective_chat.id,
        f"📄 *Файл:* `{current_file}`\n🎨 *Тип:* `{file_type}`\n📏 *Размер:* {len(code)} символов\n\n```{lang_map.get(file_type, '')}\n{code}\n```",
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
            caption=f"✅ *Готовый код!*\n📊 {len(code)} символов\n📁 Файл: `{current_file}`",
            parse_mode="Markdown"
        )
    os.remove(current_file)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions[user_id]["code"] = ""
        user_sessions[user_id]["history"] = []
        user_sessions[user_id]["project_files"] = {}
        user_sessions[user_id]["current_file"] = "main.py"
    await update.message.reply_text("🧹 *Код и проект полностью очищены!* Начинаем заново.", parse_mode="Markdown")

async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для перестановки")
        return
    
    reordered = reorder_code(code)
    user_sessions[user_id]["code"] = reordered
    
    # Обновляем файл в проекте
    current_file = user_sessions[user_id].get("current_file", "main.py")
    if "project_files" in user_sessions[user_id]:
        user_sessions[user_id]["project_files"][current_file] = reordered
    
    await update.message.reply_text(
        "🔄 *Код переставлен!*\n\n"
        "Импорты → Классы → Функции → Остальной код\n"
        "`/show` для просмотра",
        parse_mode="Markdown"
    )

async def complexity_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для анализа. Отправь код или создай проект `/new_project`", parse_mode="Markdown")
        return
    
    analysis = analyze_complexity(code)
    report = format_complexity_report(analysis)
    await update.message.reply_text(report, parse_mode="Markdown")

async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода для поиска багов", parse_mode="Markdown")
        return
    
    await update.message.reply_text("🐛 *Ищу баги в коде...*", parse_mode="Markdown")
    bugs = find_bugs(code)
    report = generate_bugs_report(bugs)
    await update.message.reply_text(report, parse_mode="Markdown")

async def validate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    current_file = user_sessions.get(user_id, {}).get("current_file", "main.py")
    
    if not code:
        await update.message.reply_text("📭 Нет кода для проверки", parse_mode="Markdown")
        return
    
    await update.message.reply_text("🔍 *Проверяю и исправляю код...*", parse_mode="Markdown")
    
    file_type = detect_file_type(current_file, code)
    fixed_code, errors, fixes = validate_and_fix(code, file_type)
    
    if fixed_code != code:
        user_sessions[user_id]["code"] = fixed_code
        if "project_files" in user_sessions[user_id]:
            user_sessions[user_id]["project_files"][current_file] = fixed_code
    
    report = generate_validation_report(errors, fixes)
    await update.message.reply_text(report, parse_mode="Markdown")

# ==================== МНОГОФАЙЛОВЫЕ ПРОЕКТЫ ====================
async def new_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    project_type = args[0].lower() if args else "python"
    
    templates = {
        "python": PROJECT_TEMPLATES["python"],
        "flask": PROJECT_TEMPLATES["flask"],
        "html": PROJECT_TEMPLATES["html"],
        "frontend": PROJECT_TEMPLATES["html"],
        "fullstack": PROJECT_TEMPLATES["fullstack"]
    }
    
    if project_type not in templates:
        await update.message.reply_text(
            f"❌ Неизвестный тип проекта. Доступные: `python`, `flask`, `html`, `fullstack`",
            parse_mode="Markdown"
        )
        return
    
    user_id = update.effective_user.id
    files = templates[project_type]
    
    user_sessions[user_id]["project_files"] = files.copy()
    user_sessions[user_id]["current_file"] = list(files.keys())[0]
    user_sessions[user_id]["code"] = files[list(files.keys())[0]]
    user_sessions[user_id]["project_type"] = project_type
    user_sessions[user_id]["history"] = []
    
    file_list = "\n".join([f"• `{name}` ({len(content)} символов)" for name, content in files.items()])
    
    await update.message.reply_text(
        f"✅ *Проект типа '{project_type}' создан!*\n\n"
        f"📁 *Файлы в проекте:*\n{file_list}\n\n"
        f"📄 *Текущий файл:* `{user_sessions[user_id]['current_file']}`\n\n"
        f"`/files` — список файлов\n"
        f"`/switch_file <имя>` — переключиться между файлами\n"
        f"`/add_file <имя>` — добавить новый файл\n"
        f"`/export` — скачать все файлы архивом",
        parse_mode="Markdown"
    )

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project_files = user_sessions.get(user_id, {}).get("project_files", {})
    current_file = user_sessions.get(user_id, {}).get("current_file", "")
    
    if not project_files:
        await update.message.reply_text(
            "📭 *Нет файлов в проекте*\n\n"
            "Используй `/new_project python` чтобы создать проект",
            parse_mode="Markdown"
        )
        return
    
    files_list = []
    for name, content in project_files.items():
        size = len(content)
        mark = " ✅ *текущий*" if name == current_file else ""
        files_list.append(f"• `{name}` ({size} символов){mark}")
    
    keyboard = []
    row = []
    for i, name in enumerate(project_files.keys()):
        row.append(InlineKeyboardButton(name[:20], callback_data=f"switch_{name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("➕ Добавить файл", callback_data="add_file")])
    keyboard.append([InlineKeyboardButton("📦 Экспорт ZIP", callback_data="export_zip")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📁 **Файлы проекта ({len(project_files)})**\n\n" + "\n".join(files_list),
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def switch_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("📝 *Использование:* `/switch_file main.py`\n\n`/files` — посмотреть все файлы", parse_mode="Markdown")
        return
    
    filename = args[0]
    user_id = update.effective_user.id
    project_files = user_sessions.get(user_id, {}).get("project_files", {})
    
    if filename in project_files:
        user_sessions[user_id]["current_file"] = filename
        user_sessions[user_id]["code"] = project_files[filename]
        
        file_type = detect_file_type(filename, project_files[filename])
        await update.message.reply_text(
            f"✅ *Переключён на файл:* `{filename}`\n"
            f"🎨 Тип: `{file_type}`\n"
            f"📦 Размер: {len(project_files[filename])} символов\n\n"
            f"Теперь отправляй код для этого файла!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ *Файл `{filename}` не найден*\n\n`/files` — список всех файлов", parse_mode="Markdown")

async def add_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 *Использование:* `/add_file new_file.py`\n\n"
            "Поддерживаемые расширения: `.py`, `.html`, `.css`, `.js`, `.json`, `.md`, `.txt`",
            parse_mode="Markdown"
        )
        return
    
    filename = args[0]
    user_id = update.effective_user.id
    
    if "project_files" not in user_sessions[user_id]:
        user_sessions[user_id]["project_files"] = {}
    
    ext = filename.split('.')[-1] if '.' in filename else 'txt'
    templates = {
        'py': '# Python code\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n',
        'html': '<!DOCTYPE html>\n<html>\n<head><title>New Page</title></head>\n<body>\n<h1>Hello</h1>\n</body>\n</html>',
        'css': '/* Styles */\nbody {\n    font-family: Arial, sans-serif;\n    margin: 0;\n    padding: 20px;\n}\n',
        'js': '// JavaScript\nconsole.log("Hello from " + document.title);\n',
        'json': '{\n    "name": "example",\n    "version": "1.0.0"\n}\n',
        'md': '# New File\n\nDescription here\n',
        'txt': 'Content goes here\n'
    }
    
    user_sessions[user_id]["project_files"][filename] = templates.get(ext, f"# Content of {filename}\n")
    await update.message.reply_text(
        f"✅ *Файл `{filename}` добавлен в проект!*\n\n"
        f"`/switch_file {filename}` — начать редактировать\n"
        f"`/files` — список всех файлов",
        parse_mode="Markdown"
    )

async def export_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    project_files = user_sessions.get(user_id, {}).get("project_files", {})
    
    if not project_files:
        await update.message.reply_text("📭 *Нет файлов для экспорта*\n\nСоздай проект: `/new_project python`", parse_mode="Markdown")
        return
    
    await update.message.reply_text("📦 *Создаю ZIP архив со всеми файлами...*", parse_mode="Markdown")
    
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, content in project_files.items():
            zip_file.writestr(filename, content)
    
    zip_buffer.seek(0)
    
    await update.message.reply_document(
        document=zip_buffer,
        filename=f"project_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        caption=f"📦 *Архив проекта*\n📁 {len(project_files)} файлов\n🗓️ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        parse_mode="Markdown"
    )

# ==================== GITHUB КОМАНДЫ ====================
async def gh_repo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "📁 *Создание GitHub репозитория*\n\n"
            "Использование: `/gh_repo название-репозитория`\n"
            "Пример: `/gh_repo my-awesome-bot`\n\n"
            "⚠️ Требуется настроить `GITHUB_TOKEN` в переменных окружения",
            parse_mode="Markdown"
        )
        return
    
    repo_name = args[0]
    await update.message.reply_text(f"📁 *Создаю репозиторий* `{repo_name}`...", parse_mode="Markdown")
    
    result = await create_github_repo(repo_name, f"Created via Telegram bot by {update.effective_user.first_name}")
    
    if result["success"]:
        await update.message.reply_text(
            f"✅ *Репозиторий создан!*\n\n"
            f"🔗 {result['repo_url']}\n"
            f"📦 Имя: `{result['name']}`\n\n"
            f"Теперь загрузи код: `/gh_push {repo_name} {user_sessions.get(update.effective_user.id, {}).get('current_file', 'main.py')}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ *Ошибка:* {result['error']}", parse_mode="Markdown")

async def gh_push_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📤 *Загрузка кода на GitHub*\n\n"
            "Использование: `/gh_push имя-репозитория файл.py`\n"
            "Пример: `/gh_push my-bot main.py`\n\n"
            "Загрузит текущий код в указанный репозиторий",
            parse_mode="Markdown"
        )
        return
    
    repo_name = args[0]
    filename = args[1]
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    
    if not code:
        await update.message.reply_text("❌ *Нет кода для загрузки*\n\nСначала собери код или создай проект `/new_project`", parse_mode="Markdown")
        return
    
    await update.message.reply_text(f"📤 *Загружаю* `{filename}` *в* `{repo_name}`...", parse_mode="Markdown")
    
    result = await push_to_github(repo_name, filename, code, f"Add {filename} from Telegram bot")
    
    if result["success"]:
        await update.message.reply_text(
            f"✅ *Код загружен!*\n\n"
            f"🔗 {result['file_url']}\n"
            f"📝 `{filename}` успешно добавлен",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ *Ошибка:* {result['error']}", parse_mode="Markdown")

async def gh_gist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    current_file = user_sessions.get(user_id, {}).get("current_file", "code.py")
    
    if not code:
        await update.message.reply_text("❌ *Нет кода для создания Gist*\n\nСначала собери код или создай проект", parse_mode="Markdown")
        return
    
    filename = args[0] if args else current_file
    
    await update.message.reply_text("📝 *Создаю GitHub Gist...*", parse_mode="Markdown")
    
    result = await create_gist(
        filename=filename,
        content=code,
        description=f"Code from {update.effective_user.first_name} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    
    if result["success"]:
        await update.message.reply_text(
            f"✅ *Gist создан!*\n\n"
            f"🔗 {result['gist_url']}\n"
            f"📄 Ссылка для скачивания: {result['raw_url']}\n"
            f"📁 Файл: `{filename}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ *Ошибка:* {result['error']}", parse_mode="Markdown")

# ==================== ОБРАБОТКА КОДА ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "code": "",
            "project_files": {},
            "current_file": "main.py",
            "history": [],
            "project_type": None
        }
    
    instruction = ""
    code_part = user_message
    for kw in ["ДОБАВИТЬ:", "ИЗМЕНИТЬ:", "УДАЛИТЬ:", "ПЕРЕПИСАТЬ:", "ИСПРАВИТЬ:"]:
        if kw in user_message.upper():
            parts = user_message.split(kw, 1)
            instruction = kw
            code_part = parts[1].strip()
            break
    
    current = user_sessions[user_id]["code"]
    status = await update.message.reply_text(f"🧠 *{AI_NAME}* анализирует и объединяет код...", parse_mode="Markdown")
    
    result = await ai_merge_code(current, code_part, instruction)
    final = result["code"]
    
    # Применяем перестановку
    final = reorder_code(final)
    
    # Валидация
    current_file = user_sessions[user_id].get("current_file", "main.py")
    file_type = detect_file_type(current_file, final)
    final, errors, fixes = validate_and_fix(final, file_type)
    
    user_sessions[user_id]["code"] = final
    user_sessions[user_id]["history"].append({
        "time": datetime.now().isoformat(),
        "part": code_part[:100],
        "changes": result["changes"]
    })
    
    # Обновляем файл в проекте
    if "project_files" in user_sessions[user_id]:
        user_sessions[user_id]["project_files"][current_file] = final
    
    response = f"✅ *Код обновлён!*\n\n"
    response += f"🔧 {result['changes']}\n"
    response += f"📊 Размер: {len(final)} символов\n"
    response += f"📁 Файл: `{current_file}`\n"
    response += f"📦 Частей получено: {len(user_sessions[user_id]['history'])}\n"
    
    if fixes:
        response += f"\n🔧 *Авто-исправлено:* {len(fixes)} проблем\n"
    if errors:
        response += f"\n⚠️ *Осталось ошибок:* {len(errors)}\n"
    
    response += f"\n`/show` — посмотреть код\n`/done` — скачать\n`/validate` — проверить всё"
    
    await status.edit_text(response, parse_mode="Markdown")

# ==================== INLINE КНОПКИ ====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "show":
        await show_code(update, context)
    elif data == "download":
        fake_update = update
        fake_update.message = query.message
        await done(fake_update, context)
    elif data == "reset":
        await reset(update, context)
        await query.message.delete()
    elif data == "files":
        await list_files(update, context)
    elif data == "add_file":
        await query.message.reply_text(
            "📝 *Добавление файла*\n\n"
            "Используй команду:\n"
            "`/add_file имя_файла.расширение`\n\n"
            "Пример: `/add_file app.py`",
            parse_mode="Markdown"
        )
    elif data == "export_zip":
        await export_all(update, context)
    elif data.startswith("switch_"):
        filename = data.replace("switch_", "")
        fake_update = update
        fake_update.message = query.message
        fake_update.message.text = f"/switch_file {filename}"
        await switch_file(fake_update, context)

# ==================== ВЕБ-РЕДАКТОР ====================
WEB_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>🤖 AI Code Editor</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
            min-height: 100vh;
        }
        .header {
            background: rgba(0,0,0,0.3);
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 20px;
            font-weight: bold;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .toolbar {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        button {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            transition: all 0.2s;
        }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
        .btn-primary:hover { transform: translateY(-1px); opacity: 0.9; }
        .btn-secondary { background: rgba(255,255,255,0.1); color: white; }
        .btn-secondary:hover { background: rgba(255,255,255,0.2); }
        .status-bar {
            background: rgba(0,0,0,0.5);
            padding: 6px 20px;
            font-size: 12px;
            color: #aaa;
            display: flex;
            justify-content: space-between;
        }
        #editor { height: calc(100vh - 100px); }
        @media (max-width: 768px) {
            .toolbar button { padding: 6px 12px; font-size: 11px; }
            .logo { font-size: 16px; }
        }
    </style>
</head>
<body>
<div class="header">
    <div class="logo">🤖 AI Code Editor</div>
    <div class="toolbar">
        <button class="btn-primary" onclick="saveCode()">💾 Сохранить</button>
        <button class="btn-secondary" onclick="analyzeComplexity()">📊 Сложность</button>
        <button class="btn-secondary" onclick="findBugs()">🐛 Баги</button>
        <button class="btn-secondary" onclick="validateCode()">✅ Валидация</button>
        <button class="btn-secondary" onclick="reorderCode()">🔄 Порядок</button>
        <button class="btn-secondary" onclick="downloadCode()">📥 Скачать</button>
    </div>
</div>
<div id="editor"></div>
<div class="status-bar">
    <span id="status">⚡ Готов к работе</span>
    <span id="stats">📝 Символов: 0</span>
</div>

<script>
let editor;
require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: {{ code | tojson }},
        language: 'python',
        theme: 'vs-dark',
        fontSize: 13,
        minimap: { enabled: true },
        automaticLayout: true,
        fontFamily: 'Fira Code, monospace',
        fontLigatures: true
    });
    
    editor.onDidChangeModelContent(() => {
        const len = editor.getValue().length;
        document.getElementById('stats').innerHTML = `📝 Символов: ${len}`;
    });
    
    document.getElementById('stats').innerHTML = `📝 Символов: {{ code | length }}`;
});

async function saveCode() {
    const code = editor.getValue();
    const res = await fetch('/api/save_code', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: {{ user_id }}, code: code})
    });
    const data = await res.json();
    document.getElementById('status').innerHTML = data.success ? '✅ Сохранено в бота!' : '❌ Ошибка сохранения';
    setTimeout(() => document.getElementById('status').innerHTML = '⚡ Готов к работе', 2000);
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
    document.getElementById('status').innerHTML = '🔄 Код переставлен!';
    setTimeout(() => document.getElementById('status').innerHTML = '⚡ Готов к работе', 2000);
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
        current_file = user_sessions[user_id].get("current_file", "main.py")
        if "project_files" in user_sessions[user_id]:
            user_sessions[user_id]["project_files"][current_file] = code
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

@app.route('/')
def health():
    return "🤖 AI Code Assembler Bot is running!", 200

@app.route('/health')
def health_check():
    return {"status": "ok", "active_sessions": len(user_sessions), "ai_model": AI_NAME}, 200

# ==================== ЗАПУСК ====================
def run_telegram_bot():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не задан!")
        return
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
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
    application.add_handler(CommandHandler("gh_push", gh_push_command))
    application.add_handler(CommandHandler("gh_gist", gh_gist_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info(f"🚀 Бот запущен! AI: {AI_NAME}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://your-bot.onrender.com")
    
    await update.message.reply_text(
        f"🎨 *Веб-редактор кода*\n\n"
        f"🔗 Открывай в браузере:\n{bot_url}/web_editor/{user_id}\n\n"
        f"*Возможности редактора:*\n"
        f"• Подсветка синтаксиса\n"
        f"• Автодополнение\n"
        f"• Анализ сложности\n"
        f"• Поиск багов\n"
        f"• Валидация\n"
        f"• Перестановка порядка\n"
        f"• Скачивание файла\n\n"
        f"💡 *Совет:* Сохраняй код кнопкой «Сохранить» — он синхронизируется с ботом!",
        parse_mode="Markdown"
    )

if __name__ == "__main__":
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT)
