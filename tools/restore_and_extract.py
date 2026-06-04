"""Restore legacy, re-run module 2+3 extraction."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 1) Restore from zip
z = zipfile.ZipFile(r'C:\Users\Vitoria Duarte\Downloads\iris-cost-para-github.zip')
(ROOT / 'app' / 'legacy.py').write_bytes(z.read('app.py'))

# 2) Module 1 patches
legacy_path = ROOT / 'app' / 'legacy.py'
t = legacy_path.read_text(encoding='utf-8')
t = t.replace(
    "APP_TIMEZONE = os.getenv('APP_TIMEZONE', 'America/Sao_Paulo')",
    "from app.config import APP_TIMEZONE, PROJECT_ROOT, SESSION_IDLE_MINUTES",
)
t = t.replace('BASE_DIR = Path(__file__).resolve().parent', 'BASE_DIR = PROJECT_ROOT')
old_app = """app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'gg-web-app')

# Render roda atrás de proxy. Isto permite que Flask reconheça HTTPS corretamente
# sem quebrar sessão/cookie no PC, celular ou ambiente local.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Sessão estável para Render + Chrome mobile.
# Lax é suficiente para redirecionamentos dentro do mesmo domínio e evita o bug
# de SameSite=None que derrubou o login em alguns navegadores.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '1').strip().lower() in ('1', 'true', 'yes', 'on'),
    SESSION_COOKIE_NAME=os.getenv('SESSION_COOKIE_NAME', 'iris_session'),
    SESSION_COOKIE_PATH='/',
    PERMANENT_SESSION_LIFETIME=timedelta(days=int(os.getenv('SESSION_DAYS', '7') or 7)),
)
# ── Configurações de segurança ────────────────────────────────
SESSION_IDLE_MINUTES = int(os.getenv('SESSION_IDLE_MINUTES', '120') or 120)


# Render/free: limites para não deixar upload/request explodir memória.
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '20') or 20) * 1024 * 1024
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0"""
new_app = """from app.factory import create_app

app = create_app()"""
if old_app not in t:
    raise SystemExit('Module 1 patch block not found')
t = t.replace(old_app, new_app)
legacy_path.write_text(t, encoding='utf-8')
print('module 1 ok')

# 3) Module 2
import subprocess
subprocess.check_call([str(ROOT / '.venv' / 'Scripts' / 'python.exe'), str(ROOT / 'tools' / 'extract_db.py')])

# 4) Module 3 - run fixed extract_auth
subprocess.check_call([str(ROOT / '.venv' / 'Scripts' / 'python.exe'), str(ROOT / 'tools' / 'extract_auth_fixed.py')])

print('all done')
