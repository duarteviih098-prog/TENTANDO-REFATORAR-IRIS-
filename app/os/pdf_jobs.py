"""Jobs em background para PDF mensal de O.S."""
import os
import threading
import time

from flask import session

from app.os.pdf_builder import _build_os_pdf_mes_buffer
from app.os.pdf_common import (
    _bg,
    _flask_app,
    current_company_id,
    execute,
    query_one,
)
from app.os.pdf_support import _pdf_safe_text
from app.shared.formatters import br_now
from app.shared.months import normalize_month_reference
from app.shared.rows import row_get_value, row_to_dict
from app.storage import _upload_pdf_bytes_to_supabase, company_folder_name

def _render_pdf_job_wait_page(job_id, mes_norm):
    """Página simples para aba nova: mostra status e abre o PDF quando ficar pronto."""
    job_id = int(job_id)
    mes_txt = _pdf_safe_text(mes_norm or '')
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gerando PDF mensal - IRIS</title>
  <style>
    body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:#0f1b2d;color:#eef6ff;display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{width:min(560px,calc(100vw - 32px));background:#162844;border:1px solid #29486f;border-radius:22px;padding:28px;box-shadow:0 22px 70px rgba(0,0,0,.35);text-align:center}}
    .spin{{width:54px;height:54px;border:5px solid rgba(255,255,255,.18);border-top-color:#4aa3ff;border-radius:999px;margin:0 auto 18px;animation:spin 1s linear infinite}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    h1{{margin:0 0 8px;font-size:1.45rem}}
    p{{color:#b9c8dc;line-height:1.45}}
    .status{{margin-top:18px;padding:12px 14px;border-radius:14px;background:#0f1b2d;color:#d9e8ff;font-weight:800}}
    .btn{{display:inline-block;margin-top:18px;border-radius:14px;padding:12px 16px;background:#2f80ed;color:white;text-decoration:none;font-weight:800}}
    .err{{background:#4a1720;color:#ffd7df}}
  </style>
</head>
<body>
  <div class="card">
    <div class="spin" id="spin"></div>
    <h1>Gerando PDF mensal</h1>
    <p>O IRIS está montando o relatório de <strong>{mes_txt}</strong> com todas as fotos disponíveis. Pode levar alguns minutos.</p>
    <div class="status" id="status">Preparando fila...</div>
    <div id="actions"></div>
  </div>
<script>
const jobId = {job_id};
async function checkStatus() {{
  try {{
    const r = await fetch(`/os/pdf/job/${{jobId}}/status?ts=${{Date.now()}}`, {{cache:'no-store'}});
    const d = await r.json();
    const status = document.getElementById('status');
    const actions = document.getElementById('actions');
    if (d.status === 'pendente') status.textContent = 'Na fila...';
    else if (d.status === 'gerando') status.textContent = 'Gerando PDF e comprimindo fotos...';
    else if (d.status === 'pronto') {{
      document.getElementById('spin').style.display = 'none';
      status.textContent = 'PDF pronto.';
      actions.innerHTML = `<a class="btn" href="${{d.arquivo_url}}" target="_blank" rel="noopener">Abrir PDF</a>`;
      window.location.href = d.arquivo_url;
      return;
    }} else if (d.status === 'erro') {{
      document.getElementById('spin').style.display = 'none';
      status.classList.add('err');
      status.textContent = 'Erro ao gerar PDF: ' + (d.erro || 'erro desconhecido');
      return;
    }}
  }} catch(e) {{
    document.getElementById('status').textContent = 'Aguardando servidor...';
  }}
  setTimeout(checkStatus, 3000);
}}
checkStatus();
</script>
</body>
</html>"""


def _pdf_job_now():
    """Timestamp no formato ISO para o PostgreSQL."""
    return br_now().strftime('%Y-%m-%d %H:%M:%S')


def _create_pdf_job(tipo, mes):
    """Cria registro em pdf_jobs e retorna o id."""
    mes_norm = normalize_month_reference(mes) or mes
    job_id = execute(
        """INSERT INTO pdf_jobs (empresa_id, usuario_id, tipo, mes, status)
           VALUES (?, ?, ?, ?, ?)""",
        (current_company_id(), session.get('user_id'), tipo, mes_norm, 'pendente')
    )
    if not job_id:
        row = query_one(
            """SELECT id FROM pdf_jobs
               WHERE empresa_id=? AND usuario_id=? AND tipo=? AND mes=?
               ORDER BY id DESC LIMIT 1""",
            (current_company_id(), session.get('user_id'), tipo, mes_norm)
        )
        job_id = row_get_value(row, 'id') if row else None
    return int(job_id), mes_norm


def _gerar_pdf_mensal_job_worker(job_id):
    """Worker em background: gera PDF mensal, salva no Supabase e atualiza pdf_jobs."""
    with _flask_app().app_context():
        ctx = _bg()
        old_empresa = getattr(ctx, 'empresa_id', None)
        old_all_images = getattr(ctx, 'pdf_all_images', False)
        try:
            job = row_to_dict(query_one('SELECT * FROM pdf_jobs WHERE id=?', (job_id,)))
            if not job:
                return
            ctx.empresa_id = row_get_value(job, 'empresa_id')
            # Usa limite de imagens padrão — não força todas as fotos para não travar
            ctx.pdf_all_images = False

            execute("UPDATE pdf_jobs SET status=?, iniciado_em=?, erro=? WHERE id=?", ('gerando', _pdf_job_now(), '', job_id))

            pdf_buf, mes_norm = _build_os_pdf_mes_buffer(row_get_value(job, 'mes'), include_all_images=False, use_cache=False)
            pdf_buf.seek(0)
            pdf_bytes = pdf_buf.read()

            empresa_id = row_get_value(job, 'empresa_id')
            folder = company_folder_name(empresa_id)
            safe_mes = str(mes_norm or 'mes').replace('/', '-')
            storage_path = f"empresas/{folder}/pdfs/rdo_mensal_{safe_mes}_job_{job_id}.pdf"
            arquivo_url = _upload_pdf_bytes_to_supabase(pdf_bytes, storage_path)

            execute(
                """UPDATE pdf_jobs
                   SET status=?, arquivo_url=?, storage_path=?, finalizado_em=?
                   WHERE id=?""",
                ('pronto', arquivo_url, storage_path, _pdf_job_now(), job_id)
            )
        except Exception as exc:
            _flask_app().logger.exception('Falha no job de PDF mensal %s', job_id)
            try:
                execute(
                    "UPDATE pdf_jobs SET status=?, erro=?, finalizado_em=? WHERE id=?",
                    ('erro', str(exc)[:2000], _pdf_job_now(), job_id)
                )
            except Exception:
                pass
        finally:
            ctx.empresa_id = old_empresa
            ctx.pdf_all_images = old_all_images


def _start_pdf_job_thread(job_id):
    t = threading.Thread(target=_gerar_pdf_mensal_job_worker, args=(int(job_id),), daemon=True, name=f'pdf-job-{job_id}')
    t.start()
    return t
