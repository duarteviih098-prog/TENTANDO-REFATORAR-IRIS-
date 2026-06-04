"""Apply Module 16 — cleanup: routes out of legacy, bootstrap, compat re-exports."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'

COMPAT = '''

# --- compat: símbolos usados via _legacy() por outros módulos ---
from app.auth import owned_by_current_company, user_has
from app.auth.decorators import is_mobile_request
from app.campo.push import _ensure_push_subscriptions_table, _send_push
from app.campo.services import (
    _api_campo_guard,
    campo_numero_visivel,
    campo_os_atrasada,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_status_pausado,
    campo_tecnico_for_os_row,
    campo_token_for,
    campo_token_para_usuario,
    usuario_eh_campo_operacional,
)
from app.controle.services import fetch_bombas_counts
from app.exports.excel import excel_rows_from_upload
from app.os.pdf import _draw_pdf_header, excel_file, table_pdf
from app.os.services import ensure_os_tipo_os_column, os_is_overdue
from app.storage import (
    backup_company_data,
    ensure_company_storage,
    load_company_identity_config,
    save_company_identity_config,
    save_company_identity_file,
)

app = None  # preenchido por app.bootstrap após create_app()
'''


def main():
    text = legacy_path.read_text(encoding='utf-8')
    if '# --- compat: símbolos usados via _legacy()' in text:
        print('Module 16 legacy cleanup already applied.')
        return

    lines = text.splitlines(keepends=True)

    # Remove duplicate local query_all (shadows app.db)
    start_dup = next(i for i, l in enumerate(lines) if l.startswith('def query_all(sql, params=()):') and i > 400)
    end_dup = start_dup + 1
    while end_dup < len(lines) and lines[end_dup].strip() and not lines[end_dup].startswith('def '):
        end_dup += 1
    del lines[start_dup:end_dup]

    # Remove bootstrap block: from app.factory through register_integrations + jinja wiring
    start_boot = next(i for i, l in enumerate(lines) if l.strip() == 'from app.factory import create_app')
    end_boot = start_boot
    while end_boot < len(lines) and not lines[end_boot].startswith('def br_date('):
        end_boot += 1
    # drop jinja lines right before br_date if any
    while end_boot > start_boot and 'jinja_env' in lines[end_boot - 1]:
        end_boot -= 1
    del lines[start_boot:end_boot]

    # Remove trailing jinja globals after format_phone_br (if still present)
    cleaned = []
    skip_jinja = False
    for line in lines:
        if line.startswith('app.jinja_env.') or line.strip() == "app.jinja_env.globals['user_has'] = user_has":
            continue
        cleaned.append(line)
    lines = cleaned

    # Remove API routes + startup block
    try:
        start_api = next(i for i, l in enumerate(lines) if l.startswith("@app.route('/api/search')"))
    except StopIteration:
        start_api = next(
            i for i, l in enumerate(lines)
            if l.startswith('if __name__') or (l.strip().startswith('# =') and i > 600)
        )
    end_api = next(i for i, l in enumerate(lines) if l.startswith('# --- compat:'))
    del lines[start_api:end_api]

    # Remove duplicate DB_PATH assignment
    lines = [l for l in lines if l.strip() != "DB_PATH = BASE_DIR / 'app.db'"]

    text = ''.join(lines).rstrip() + '\n' + COMPAT
    legacy_path.write_text(text, encoding='utf-8')
    print('legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
