"""Jobs em background para relatórios PDF Iris."""
import re
import threading

from flask import session

from app.exports.iris_reports import _iris_make_ai_pdf
from app.shared.rows import row_get_value, row_to_dict


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)


def _flask_app():
    from app.runtime import flask_app
    return flask_app()


def _bg_context():
    from app.runtime import BACKGROUND_COMPANY_CONTEXT
    return BACKGROUND_COMPANY_CONTEXT


app = None


def _lazy_app_refs():
    global app
    if app is None:
        app = _flask_app()


def _create_iris_job(tipo, ref_param):
    job_id = execute(
        "INSERT INTO pdf_jobs (empresa_id, usuario_id, tipo, mes, status) VALUES (?,?,?,?,?)",
        (current_company_id(), session.get('user_id'), f'iris_{tipo}', str(ref_param), 'pendente')
    )
    if not job_id:
        row = query_one(
            "SELECT id FROM pdf_jobs WHERE empresa_id=? AND tipo=? AND mes=? ORDER BY id DESC LIMIT 1",
            (current_company_id(), f'iris_{tipo}', str(ref_param))
        )
        job_id = row_get_value(row, 'id') if row else None
    return int(job_id)




def _gerar_iris_job_worker(job_id):
    from app.os.pdf import _pdf_job_now
    flask_app = _flask_app()
    bg_ctx = _bg_context()
    with flask_app.app_context():
        old_empresa = getattr(bg_ctx, 'empresa_id', None)
        try:
            job = row_to_dict(query_one('SELECT * FROM pdf_jobs WHERE id=?', (job_id,)))
            if not job:
                return
            bg_ctx.empresa_id = row_get_value(job, 'empresa_id')
            execute("UPDATE pdf_jobs SET status=?, iniciado_em=?, erro=? WHERE id=?",
                    ('gerando', _pdf_job_now(), '', job_id))
            tipo_raw = str(row_get_value(job, 'tipo') or '').replace('iris_', '')
            ref_param = str(row_get_value(job, 'mes') or '')
            year = month_ref = sistema = ''
            if re.match(r'^\d{4}$', ref_param):
                year = ref_param
            elif '|' in ref_param:
                partes = ref_param.split('|')
                sistema = partes[1] if len(partes) > 1 else ''
                month_ref = partes[2] if len(partes) > 2 else ''
            else:
                month_ref = ref_param
            out, arquivo_url = _iris_make_ai_pdf(
                tipo_raw, month_ref=month_ref, year=year,
                sistema=sistema, upload_supabase=True
            )
            execute(
                "UPDATE pdf_jobs SET status=?, arquivo_url=?, storage_path=?, finalizado_em=? WHERE id=?",
                ('pronto', arquivo_url, str(out), _pdf_job_now(), job_id)
            )
            print(f'Iris job {job_id} ({tipo_raw}) OK — {arquivo_url}')
        except Exception as exc:
            flask_app.logger.exception('Falha iris job %s', job_id)
            try:
                execute("UPDATE pdf_jobs SET status=?, erro=?, finalizado_em=? WHERE id=?",
                        ('erro', str(exc)[:2000], _pdf_job_now(), job_id))
            except Exception:
                pass
        finally:
            bg_ctx.empresa_id = old_empresa




def _start_iris_job_thread(job_id):
    t = threading.Thread(target=_gerar_iris_job_worker, args=(int(job_id),),
                         daemon=True, name=f'iris-job-{job_id}')
    t.start()
    return t




def _render_iris_job_wait_page(job_id, titulo, subtitulo=''):
    job_id = int(job_id)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IRIS — Gerando relatório</title>
<style>*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:linear-gradient(135deg,#0d2461,#1a4a8a);color:#eef6ff;min-height:100vh;display:flex;align-items:center;justify-content:center}}.card{{width:min(500px,calc(100vw - 32px));background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);border-radius:24px;padding:36px;text-align:center}}.logo{{font-size:2rem;font-weight:900;color:#fff;margin-bottom:4px}}.tipo{{font-size:.95rem;color:#a8c8f0;margin-bottom:22px}}.sw{{width:70px;height:70px;margin:0 auto 18px;position:relative}}.sp{{width:70px;height:70px;border:5px solid rgba(255,255,255,.15);border-top-color:#4aa3ff;border-radius:50%;animation:spin 1s linear infinite}}.br{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:24px}}@keyframes spin{{to{{transform:rotate(360deg)}}}}h1{{margin:0 0 6px;font-size:1.2rem}}p{{color:#a8c8f0;font-size:.88rem;margin:0 0 16px;line-height:1.5}}.sb{{background:rgba(0,0,0,.25);border-radius:12px;padding:11px 14px;font-weight:700;font-size:.88rem;margin-bottom:14px;min-height:42px;display:flex;align-items:center;justify-content:center;gap:8px}}.dot{{width:7px;height:7px;background:#4aa3ff;border-radius:50%;animation:pulse 1.5s infinite;flex-shrink:0}}@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}.btn{{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(100deg,#2d7a3a,#4caf50);color:#fff;text-decoration:none;padding:12px 22px;border-radius:13px;font-weight:900;font-size:.92rem;margin-top:6px}}.err{{background:rgba(239,66,111,.2);border-radius:10px;padding:10px;color:#fca5a5;font-size:.82rem;margin-top:10px}}</style></head>
<body><div class="card">
<div class="logo">IRIS</div><div class="tipo">{subtitulo or titulo}</div>
<div class="sw"><div class="sp"></div><div class="br">🧠</div></div>
<h1 id="title">IA trabalhando em paralelo...</h1>
<p>3 chamadas simultâneas à IA. Leva de 20 a 50 segundos.</p>
<div class="sb"><div class="dot" id="dot"></div><span id="status">Iniciando...</span></div>
<div id="actions"></div></div>
<script>
const jobId={job_id};
const steps=['Coletando dados do sistema...','IA escrevendo Resumo e Operacional...','IA escrevendo Financeiro e Sistemas...','IA escrevendo Tendências e Recomendações...','Montando PDF profissional...'];
let i=0;const iv=setInterval(()=>{{if(i<steps.length)document.getElementById('status').textContent=steps[i++];}},9000);
async function check(){{
  try{{const r=await fetch(`/os/pdf/job/${{jobId}}/status?ts=${{Date.now()}}`,{{cache:'no-store'}});const d=await r.json();
  if(d.status==='pronto'){{clearInterval(iv);document.getElementById('status').textContent='Relatório pronto!';document.getElementById('title').textContent='✅ Pronto!';document.getElementById('actions').innerHTML=`<a class="btn" href="${{d.arquivo_url}}" target="_blank">⬇ Baixar PDF</a>`;setTimeout(()=>window.location.href=d.arquivo_url,1000);return;}}
  if(d.status==='erro'){{clearInterval(iv);document.getElementById('status').textContent='Erro.';document.getElementById('actions').innerHTML=`<div class="err">❌ ${{d.erro||'Erro desconhecido.'}}</div>`;return;}}
  }}catch(e){{}}setTimeout(check,4000);}}check();
</script></body></html>"""




def _ensure_app_refs():
    _lazy_app_refs()
