"""Testes de infraestrutura — entry points, deploy e bootstrap."""
from pathlib import Path


def test_wsgi_app_imports():
    import wsgi  # noqa: F401

    assert wsgi.app is not None
    assert wsgi.app.name == 'app.factory'


def test_procfile_uses_wsgi_entrypoint():
    procfile = Path(__file__).resolve().parents[1] / 'Procfile'
    text = procfile.read_text(encoding='utf-8')
    assert 'gunicorn wsgi:app' in text


def test_runtime_python_version():
    runtime = Path(__file__).resolve().parents[1] / 'runtime.txt'
    assert 'python-3.11' in runtime.read_text(encoding='utf-8')


def test_gitignore_blocks_sensitive_paths():
    gitignore = Path(__file__).resolve().parents[1] / '.gitignore'
    text = gitignore.read_text(encoding='utf-8')
    for needle in ('app.db', '__pycache__', '.env', 'static/uploads/'):
        assert needle in text


def test_supabase_url_has_no_hardcoded_default():
    settings_py = Path(__file__).resolve().parents[1] / 'app' / 'storage' / 'settings.py'
    text = settings_py.read_text(encoding='utf-8')
    assert 'njbzfjbponspalirndqj' not in text
    assert "os.getenv('SUPABASE_URL', '')" in text


def test_bootstrap_db_script_runs_on_temp_db(tmp_path):
    import os
    import subprocess
    import sys

    db_path = tmp_path / 'bootstrap-test.db'
    env = os.environ.copy()
    env['IRIS_TEST_DB'] = str(db_path)
    env.pop('DATABASE_URL', None)
    env.setdefault('SECRET_KEY', 'test-secret-key-with-32-chars-minimum-ok')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / 'tools' / 'bootstrap_db.py'), '--db-path', str(db_path)],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert db_path.exists()
