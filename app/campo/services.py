"""Regras de negócio Campo / PWA / Push."""
def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin(user=None):
    from app.auth import current_user_is_super_admin as fn
    return fn(user)


def get_current_user():
    from app.auth import get_current_user as fn
    return fn()


def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)


def company_and(table):
    from app.auth import company_and as fn
    return fn(table)


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def get_conn():
    from app.db import get_conn as fn
    return fn()


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_db():
    from app.db import ensure_db as fn
    return fn()


def tenant_upload_dir(kind, empresa_id=None):
    from app.storage import tenant_upload_dir as fn
    return fn(kind, empresa_id=empresa_id)


def company_folder_name(empresa_id=None):
    from app.storage import company_folder_name as fn
    return fn(empresa_id)


def ensure_company_storage(empresa_id=None):
    from app.storage import ensure_company_storage as fn
    return fn(empresa_id)


def load_whatsapp_templates(empresa_id=None):
    from app.storage import load_whatsapp_templates as fn
    return fn(empresa_id)


def save_whatsapp_templates(items, empresa_id=None):
    from app.storage import save_whatsapp_templates as fn
    return fn(items, empresa_id=empresa_id)


def active_whatsapp_template(tipo, empresa_id=None):
    from app.storage import active_whatsapp_template as fn
    return fn(tipo, empresa_id)


def upload_file_to_supabase(file_storage, storage_path, content_type=None):
    from app.storage import upload_file_to_supabase as fn
    return fn(file_storage, storage_path, content_type)


def pagamentos_query_rows(*args, **kwargs):
    from app.pagamentos.services import pagamentos_query_rows as fn
    return fn(*args, **kwargs)

import hashlib
import hmac
import json
import os
import re
import uuid
import urllib.parse as urllib_parse
from datetime import timedelta
from app.auth import owned_by_current_company, user_has
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, elapsed_label, format_phone_br, normalize_phone, now_str, only_time_str, parse_br_date, parse_num, time_diff_minutes
from app.shared.payments import payment_status_is_paid
from app.shared.queries import fetch_sistemas_map, list_page, safe_int_id as _safe_int_id
from app.shared.rows import row_get_value, row_to_dict
from app.storage import backup_company_data

from flask import request, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app.db import USE_POSTGRES, ensure_column
from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE
from app.os.services import os_is_overdue, prepare_os_row_for_template
from app.storage import active_whatsapp_template

def _flask_app():
    from app.runtime import flask_app
    return flask_app()

TOKEN_EXPIRY_DAYS = int(os.getenv('CAMPO_TOKEN_EXPIRY_DAYS', '30') or 30)



def _token_expira_str(days=None):
    days = int(days or TOKEN_EXPIRY_DAYS)
    return (br_now() + timedelta(days=days)).strftime('%d/%m/%Y %H:%M:%S')




def _token_expirado(tecnico):
    expira = str(tecnico.get('token_expira_em') or '').strip()
    if not expira:
        return False
    parsed = parse_br_date(expira)
    if not parsed:
        return False
    return br_now().date() > parsed.date()




def _token_renovar(tecnico_id):
    """Renova o token por mais 30 dias a cada uso."""
    execute('UPDATE campo_tecnicos SET token_ultimo_uso=?, token_expira_em=? WHERE id=?',
            (now_str(), _token_expira_str(), tecnico_id))




def _token_revogar(tecnico_id):
    """Revoga o token — gera um novo para o técnico."""
    novo_token = uuid.uuid4().hex
    execute('UPDATE campo_tecnicos SET token=?, token_criado_em=?, token_ultimo_uso=?, token_expira_em=? WHERE id=?',
            (novo_token, now_str(), '', _token_expira_str(), tecnico_id))
    return novo_token









def _ensure_push_subscriptions_table():
    if USE_POSTGRES:
        execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER DEFAULT 0,
            tecnico_id INTEGER DEFAULT 0,
            tecnico_nome TEXT DEFAULT '',
            endpoint TEXT DEFAULT '',
            p256dh TEXT DEFAULT '',
            auth TEXT DEFAULT '',
            criado_em TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1
        )""")
    else:
        execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER DEFAULT 0,
            tecnico_id INTEGER DEFAULT 0,
            tecnico_nome TEXT DEFAULT '',
            endpoint TEXT DEFAULT '',
            p256dh TEXT DEFAULT '',
            auth TEXT DEFAULT '',
            criado_em TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1
        )""")
    try:
        ensure_column('push_subscriptions', 'tecnico_nome', "TEXT DEFAULT ''")
    except Exception:
        pass




def _send_push(subscription_info, title, body, url='/'):
    """Envia Web Push para uma subscription. Retorna True se OK, 'gone' se expirada."""
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        print('_send_push: VAPID keys não configuradas.')
        return False
    try:
        from pywebpush import webpush, WebPushException
        data = json.dumps({'title': title, 'body': body, 'url': url}, ensure_ascii=False)
        webpush(
            subscription_info=subscription_info,
            data=data,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={'sub': f'mailto:{VAPID_CLAIMS_EMAIL}'}
        )
        print(f'_send_push OK: {title}')
        return True
    except Exception as exc:
        err = str(exc)
        print(f'_send_push falhou: {exc}')
        # 410 Gone = assinatura expirada/cancelada
        if '410' in err or 'unsubscribed or expired' in err or 'Gone' in err:
            return 'gone'
        return False




def resumo_curto(texto, limite=110):
    """Resumo seguro para cards/listas do campo sem quebrar quando o texto vem vazio.

    Mantém o layout atual: só entrega uma string curta para o template.
    """
    try:
        limite = int(limite or 110)
    except Exception:
        limite = 110
    txt = re.sub(r'\s+', ' ', str(texto or '')).strip()
    if not txt:
        return ''
    if len(txt) <= limite:
        return txt
    corte = max(1, limite - 1)
    base = txt[:corte].rstrip()
    # evita cortar no meio de uma palavra quando der
    if ' ' in base and len(base.rsplit(' ', 1)[0]) >= max(20, limite // 2):
        base = base.rsplit(' ', 1)[0].rstrip()
    return base + '…'



def campo_token_for(os_id, empresa_id):
    secret = str(_flask_app().secret_key or 'gg-web-app').encode('utf-8')
    raw = f'{int(os_id)}:{int(empresa_id or 0)}'.encode('utf-8')
    return hmac.new(secret, raw, hashlib.sha256).hexdigest()[:18]




def ensure_absolute_url(url):
    """Garante URL clicável no WhatsApp: sempre http:// ou https://."""
    raw = str(url or '').strip()
    if not raw:
        return raw
    if raw.startswith(('http://', 'https://')):
        return raw
    if raw.startswith('//'):
        return 'https:' + raw
    if raw.startswith('/'):
        try:
            return request.host_url.rstrip('/') + raw
        except Exception:
            return raw
    try:
        return request.host_url.rstrip('/') + '/' + raw.lstrip('/')
    except Exception:
        return raw




def public_base_url():
    try:
        return request.host_url.rstrip('/')
    except Exception:
        return ''




def campo_link_publico(os_id, empresa_id=None):
    empresa_id = empresa_id or current_company_id()
    token = campo_token_for(os_id, empresa_id)
    try:
        link = url_for('campo_tecnico', rid=os_id, token=token, _external=True, _scheme=request.scheme or 'http')
    except Exception:
        base = public_base_url()
        link = f"{base}/os/{os_id}/campo/{token}" if base else f"/os/{os_id}/campo/{token}"
    return ensure_absolute_url(link)




def campo_tecnico_token_for(tecnico_id, empresa_id=None):
    empresa_id = empresa_id or current_company_id()
    row = row_to_dict(query_one('SELECT token FROM campo_tecnicos WHERE id=? AND COALESCE(empresa_id, ?) = ?', (tecnico_id, empresa_id, empresa_id))) or {}
    token = (row.get('token') or '').strip()
    if not token:
        token = uuid.uuid4().hex
        execute('UPDATE campo_tecnicos SET token=? WHERE id=? AND COALESCE(empresa_id, ?) = ?', (token, tecnico_id, empresa_id, empresa_id))
    return token




def campo_tecnico_app_link(tecnico_id, empresa_id=None):
    empresa_id = empresa_id or current_company_id()
    token = campo_tecnico_token_for(tecnico_id, empresa_id)
    try:
        # LINK_PERFEITO: caminho curto, linha limpa, sem /campo/app longo.
        # Em rede local força http, porque Flask local não roda HTTPS.
        host = request.host
        return f"http://{host}/c/{token}"
    except Exception:
        return f"/c/{token}"






def campo_link_com_tecnico(os_id, tecnico_token='', empresa_id=None):
    link = campo_link_publico(os_id, empresa_id)
    tecnico_token = str(tecnico_token or '').strip().strip('/')
    if tecnico_token:
        sep = '&' if '?' in link else '?'
        return f"{link}{sep}tecnico_token={urllib_parse.quote(tecnico_token, safe='')}"
    return link




def campo_tecnico_por_token(token, empresa_id=None):
    token = str(token or '').strip().strip('/')
    if not token:
        return {}
    if empresa_id:
        return row_to_dict(query_one('SELECT * FROM campo_tecnicos WHERE TRIM(token)=? AND COALESCE(empresa_id, ?) = ? AND ativo=1', (token, empresa_id, empresa_id))) or {}
    return row_to_dict(query_one('SELECT * FROM campo_tecnicos WHERE TRIM(token)=? AND ativo=1', (token,))) or {}




def campo_mesmo_tecnico(responsavel='', tecnico=None):
    tecnico = tecnico or {}
    resp = str(responsavel or '').strip().lower()
    if not resp:
        return True
    nomes = {str(tecnico.get('nome') or '').strip().lower(), str(tecnico.get('email') or '').strip().lower()}
    return resp in {x for x in nomes if x}




def campo_whatsapp_url(os_row, telefone):
    telefone = normalize_phone(telefone)
    empresa_id = os_row.get('empresa_id') or current_company_id()
    tecnico_row = campo_tecnico_for_os_row(os_row)
    direct_link = ensure_absolute_url(campo_link_publico(os_row.get('id'), empresa_id))
    link = campo_tecnico_app_link(tecnico_row.get('id'), empresa_id) if tecnico_row.get('id') else direct_link
    link = ensure_absolute_url(link)
    numero_visivel = campo_numero_visivel(os_row, os_row.get('id'))
    texto_msg = "\n".join([
        f"Nova O.S. #{numero_visivel}", "",
        f"Sistema: {os_row.get('sistema') or '-'}",
        f"Unidade: {os_row.get('equipamento') or '-'}",
        f"Responsável: {os_row.get('responsavel') or 'Disponível para equipe'}",
        f"Criticidade: {os_row.get('criticidade') or '-'}",
        f"Data: {os_row.get('data') or '-'}", "",
        "Descrição:", (os_row.get('descricao') or '-').strip(), "",
        "Link do atendimento:", link,
    ])
    return f'https://wa.me/{telefone}?text=' + urllib_parse.quote(texto_msg, safe='')





def campo_whatsapp_url_para_tecnico(os_row, tecnico_row):
    """Monta o link do WhatsApp para um técnico específico.

    Mantém o fluxo novo: a O.S. continua visível na fila global quando ainda
    não foi iniciada, mas o link enviado abre o app já no acesso daquele
    técnico. Não altera responsável, status, PDF nem layout.
    """
    os_row = row_to_dict(os_row) if os_row is not None else {}
    tecnico_row = row_to_dict(tecnico_row) if tecnico_row is not None else {}

    empresa_id = os_row.get('empresa_id') or tecnico_row.get('empresa_id') or current_company_id()
    telefone = normalize_phone(tecnico_row.get('telefone') or os_row.get('telefone') or '')
    if not telefone:
        telefone = normalize_phone(os_row.get('responsavel') or '')

    numero_visivel = campo_numero_visivel(os_row, os_row.get('id'))
    link = ''
    try:
        if tecnico_row.get('id'):
            link = campo_tecnico_app_link(tecnico_row.get('id'), empresa_id)
    except Exception:
        link = ''
    if not link:
        try:
            link = campo_link_com_tecnico(os_row.get('id'), tecnico_row.get('token') or '', empresa_id)
        except Exception:
            link = campo_link_publico(os_row.get('id'), empresa_id)
    link = ensure_absolute_url(link)

    template = active_whatsapp_template('nova_os', empresa_id) or {}
    texto_template = str(template.get('texto') or '').strip()

    dados = {
        'os_id': numero_visivel,
        'numero_os': numero_visivel,
        'id': os_row.get('id') or '',
        'sistema': os_row.get('sistema') or '-',
        'unidade': os_row.get('equipamento') or os_row.get('ativo_nome') or '-',
        'equipamento': os_row.get('equipamento') or os_row.get('ativo_nome') or '-',
        'criticidade': os_row.get('criticidade') or '-',
        'descricao': (os_row.get('descricao') or os_row.get('descricao_resumo') or '-').strip(),
        'responsavel': tecnico_row.get('nome') or os_row.get('responsavel') or 'Disponível para equipe',
        'tecnico': tecnico_row.get('nome') or '',
        'data': os_row.get('data') or '-',
        'link': link,
    }

    if texto_template:
        try:
            texto_msg = texto_template.format(**dados)
        except Exception:
            texto_msg = texto_template
            for k, v in dados.items():
                texto_msg = texto_msg.replace('{' + k + '}', str(v))
    else:
        texto_msg = "\n".join([
            f"Nova O.S. #{numero_visivel}", "",
            f"Sistema: {dados['sistema']}",
            f"Unidade: {dados['unidade']}",
            f"Responsável: {dados['responsavel']}",
            f"Criticidade: {dados['criticidade']}",
            f"Data: {dados['data']}", "",
            "Descrição:", dados['descricao'], "",
            "Link do atendimento:", link,
        ])

    return f"https://wa.me/{telefone}?text=" + urllib_parse.quote(texto_msg, safe='')




def ensure_campo_eventos_table():
    execute("""CREATE TABLE IF NOT EXISTS campo_eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        os_id INTEGER,
        empresa_id INTEGER,
        tipo TEXT DEFAULT '',
        titulo TEXT DEFAULT '',
        mensagem TEXT DEFAULT '',
        status TEXT DEFAULT 'novo',
        criado_em TEXT DEFAULT ''
    )""")
    try:
        cols = {r['name'] for r in query_all('PRAGMA table_info(campo_eventos)')}
    except Exception:
        cols = set()
    for col, ddl in {
        'os_id': "ALTER TABLE campo_eventos ADD COLUMN os_id INTEGER",
        'empresa_id': "ALTER TABLE campo_eventos ADD COLUMN empresa_id INTEGER",
        'tipo': "ALTER TABLE campo_eventos ADD COLUMN tipo TEXT DEFAULT ''",
        'titulo': "ALTER TABLE campo_eventos ADD COLUMN titulo TEXT DEFAULT ''",
        'mensagem': "ALTER TABLE campo_eventos ADD COLUMN mensagem TEXT DEFAULT ''",
        'status': "ALTER TABLE campo_eventos ADD COLUMN status TEXT DEFAULT 'novo'",
        'criado_em': "ALTER TABLE campo_eventos ADD COLUMN criado_em TEXT DEFAULT ''",
    }.items():
        if col not in cols:
            try:
                execute(ddl)
            except Exception:
                pass




def campo_evento_registrar(os_id, empresa_id=None, tipo='', mensagem=''):
    """Registra um evento de campo para o popup do operador.

    Esse ponto é a ponte entre o celular do técnico e a tela do operador.
    Por isso ele é deliberadamente defensivo: busca a O.S. novamente, usa
    numero_os como número visível e nunca deixa erro de popup quebrar a ação.
    """
    titulo_map = {
        'iniciar': 'O.S. iniciada',
        'pausar': 'O.S. pausada',
        'retomar': 'O.S. retomada',
        'finalizar': 'O.S. finalizada'
    }
    verbo_map = {
        'iniciar': 'iniciada',
        'pausar': 'pausada',
        'retomar': 'retomada',
        'finalizar': 'finalizada'
    }
    try:
        ensure_campo_eventos_table()
        os_row = row_to_dict(query_one('SELECT id, numero_os, empresa_id, status, responsavel FROM os_ordens WHERE id=?', (os_id,))) or {}
        if not os_row:
            return None
        empresa_evento = empresa_id if empresa_id not in (None, '', 0, '0') else (os_row.get('empresa_id') or None)
        numero_visivel = campo_numero_visivel(os_row, os_id)
        responsavel = os_row.get('responsavel') or 'técnico'
        verbo = verbo_map.get(str(tipo or '').lower(), 'atualizada')
        tipo = str(tipo or '').lower().strip() or 'atualizar'
        texto = (mensagem or '').strip()
        # Corrige mensagens antigas que ainda vinham com o id interno.
        if texto:
            texto = re.sub(r'O\.S\.\s*#\s*' + re.escape(str(os_id)) + r'\b', f'O.S. #{numero_visivel}', texto, flags=re.I)
        if not texto:
            texto = f"O.S. #{numero_visivel} {verbo} por {responsavel}."
        titulo = titulo_map.get(tipo, 'Atualização da O.S.')

        # Anti-metralhadora de popup: se o mesmo clique/submit chegar duplicado
        # ou o polling pegar eventos antigos, deixa apenas 1 aviso pendente por
        # O.S. + tipo. O operador não precisa ver cinco clones do mesmo fantasma.
        try:
            execute("""UPDATE campo_eventos
                       SET status='visto'
                       WHERE os_id=? AND tipo=? AND COALESCE(status,'novo')='novo'""",
                    (os_id, tipo))
        except Exception:
            pass

        return execute("""INSERT INTO campo_eventos(os_id, empresa_id, tipo, titulo, mensagem, status, criado_em)
                          VALUES (?,?,?,?,?,?,?)""",
                       (os_id, empresa_evento, tipo, titulo, texto, 'novo', now_str()))
    except Exception:
        _flask_app().logger.exception('Falha ao registrar evento de campo')
        return None




def _api_campo_guard(empty_key='eventos'):
    """Autorização JSON para polling; evita redirect HTML silencioso."""
    if not session.get('user_id'):
        return jsonify({'ok': False, empty_key: [], 'login_required': True}), 200
    if not user_has('view_os'):
        return jsonify({'ok': False, empty_key: [], 'forbidden': True}), 200
    return None





def ensure_campo_tecnicos_email_column():
    """Garante e-mail opcional no cadastro separado dos técnicos de campo.

    Técnicos continuam separados dos usuários do desktop, mas agora podem ter
    e-mail visível em Campo / WhatsApp > Técnicos.
    """
    try:
        if not table_has_column('campo_tecnicos', 'email'):
            execute('ALTER TABLE campo_tecnicos ADD COLUMN email TEXT')
            _TABLE_COLUMN_CACHE.pop(('campo_tecnicos', 'email'), None)
            _TABLE_COLUMNS_CACHE.pop('campo_tecnicos', None)
    except Exception as exc:
        print('ensure_campo_tecnicos_email_column falhou:', exc)




def ensure_campo_tecnicos_sync_columns():
    """Garante colunas usadas para sincronizar Usuários ↔ Técnicos de Campo."""
    ensure_campo_tecnicos_email_column()
    try:
        if not table_has_column('campo_tecnicos', 'user_id'):
            execute('ALTER TABLE campo_tecnicos ADD COLUMN user_id INTEGER')
            _TABLE_COLUMN_CACHE.pop(('campo_tecnicos', 'user_id'), None)
            _TABLE_COLUMNS_CACHE.pop('campo_tecnicos', None)
    except Exception as exc:
        print('ensure_campo_tecnicos_sync_columns user_id falhou:', exc)
    try:
        if not table_has_column('campo_tecnicos', 'token'):
            execute('ALTER TABLE campo_tecnicos ADD COLUMN token TEXT')
            _TABLE_COLUMN_CACHE.pop(('campo_tecnicos', 'token'), None)
            _TABLE_COLUMNS_CACHE.pop('campo_tecnicos', None)
    except Exception as exc:
        print('ensure_campo_tecnicos_sync_columns token falhou:', exc)




def perfil_eh_campo(perfil):
    txt = str(perfil or '').strip().lower()
    txt = txt.replace('é', 'e').replace('ê', 'e').replace('ã', 'a').replace('á', 'a').replace('í', 'i').replace('ó', 'o').replace('ç', 'c')
    txt = re.sub(r'[^a-z0-9]+', '_', txt).strip('_')
    return txt in {
        'campo', 'colaborador_de_campo', 'colaborador_campo',
        'tecnico', 'tecnico_campo', 'tecnico_de_campo',
        'field', 'field_technician', 'field_tech'
    }




def campo_tecnico_row_para_usuario(user):
    """Encontra o técnico de campo ligado ao usuário logado.

    Importante: alguns cadastros nasceram primeiro em Campo/WhatsApp e só depois
    viraram usuários. Então NÃO podemos depender só do perfil do usuário. Se o
    e-mail/telefone/user_id existe em campo_tecnicos, esse login é de campo e
    deve ir para o app mobile, não para o desktop.
    """
    try:
        ensure_campo_tecnicos_sync_columns()
        user = row_to_dict(user) if user is not None else {}
        user_id = int(user.get('id') or 0) if str(user.get('id') or '').strip() else 0
        empresa_id = int(user.get('empresa_id') or session.get('empresa_id') or current_company_id() or 0) or None
        email = str(user.get('email') or session.get('user_email') or '').strip().lower()
        telefone = normalize_phone(user.get('telefone') or '')

        params = []
        clauses = []
        if table_has_column('campo_tecnicos', 'user_id') and user_id:
            clauses.append('user_id=?')
            params.append(user_id)
        if email:
            clauses.append("lower(trim(COALESCE(email,'')))=lower(trim(?))")
            params.append(email)
        if telefone:
            clauses.append("regexp_replace(COALESCE(telefone,''), '[^0-9]', '', 'g')=?" if USE_POSTGRES else "replace(replace(replace(replace(replace(COALESCE(telefone,''),'(',''),')',''),'-',''),' ',''),'+','')=?")
            params.append(telefone)

        if not clauses:
            return {}

        empresa_sql = ''
        if empresa_id:
            empresa_sql = ' AND COALESCE(empresa_id, ?) = ?'
            params.extend([empresa_id, empresa_id])

        row = row_to_dict(query_one(f"""
            SELECT *
            FROM campo_tecnicos
            WHERE COALESCE(ativo,1)=1
              AND ({' OR '.join(clauses)})
              {empresa_sql}
            ORDER BY id DESC
            LIMIT 1
        """, tuple(params))) or {}
        return row
    except Exception as exc:
        print('campo_tecnico_row_para_usuario falhou:', exc)
        return {}




def is_mobile_request():
    """Detecta se a requisição vem de um celular."""
    ua = request.headers.get('User-Agent', '').lower()
    return any(x in ua for x in ['android', 'iphone', 'ipad', 'mobile', 'tablet'])




def usuario_eh_campo_operacional(user):
    user = row_to_dict(user) if user is not None else {}
    if int(user.get('is_super_admin') or 0):
        return False
    if perfil_eh_campo(user.get('perfil')):
        return True
    return bool(campo_tecnico_row_para_usuario(user).get('id'))




def campo_token_para_usuario(user):
    """Retorna o token do app de campo para o usuário, criando se necessário."""
    try:
        user = row_to_dict(user) if user is not None else {}
        tecnico = campo_tecnico_row_para_usuario(user)
        if tecnico and tecnico.get('token'):
            return tecnico['token']
        # Não tem token — sincroniza e cria
        tecnico = sincronizar_usuario_campo(
            user_id=user.get('id'),
            nome=user.get('nome', ''),
            email=user.get('email', ''),
            telefone=user.get('telefone', ''),
            empresa_id=user.get('empresa_id'),
            perfil=user.get('perfil', ''),
            ativo=int(user.get('ativo') or 1),
        )
        return tecnico.get('token') if tecnico else None
    except Exception as exc:
        print('campo_token_para_usuario erro:', exc)
        return None




def sincronizar_usuario_campo(user_id=None, nome='', email='', telefone='', empresa_id=None, perfil='', ativo=1):
    """Mantém técnico de campo visível quando nasce/é editado pela aba Usuários.

    Regra da Vi:
    - todo usuário aparece em Usuários;
    - usuário com perfil de campo também aparece em Campo / WhatsApp;
    - se deixar de ser campo ou for inativado, sai operacionalmente da lista de técnicos ativos.
    """
    try:
        ensure_campo_tecnicos_sync_columns()
        user_id = int(user_id or 0) if str(user_id or '').strip() else None
        empresa_id = int(empresa_id or current_company_id() or 0) or None
        nome = str(nome or '').strip()
        email = str(email or '').strip().lower()
        telefone = normalize_phone(telefone or '')
        ativo = 1 if str(ativo).lower() in ('1', 'true', 'sim', 'on', 'yes') or ativo == 1 else 0

        if not empresa_id or not nome:
            return None

        deve_ser_campo = perfil_eh_campo(perfil)

        existente = None
        if user_id and table_has_column('campo_tecnicos', 'user_id'):
            existente = row_to_dict(query_one(
                'SELECT * FROM campo_tecnicos WHERE user_id=? AND COALESCE(empresa_id, ?) = ? ORDER BY id DESC LIMIT 1',
                (user_id, empresa_id, empresa_id)
            ))
        if not existente and email:
            existente = row_to_dict(query_one(
                """SELECT * FROM campo_tecnicos
                   WHERE lower(trim(COALESCE(email,'')))=lower(trim(?))
                     AND COALESCE(empresa_id, ?) = ?
                   ORDER BY id DESC LIMIT 1""",
                (email, empresa_id, empresa_id)
            ))
        if not existente:
            existente = row_to_dict(query_one(
                """SELECT * FROM campo_tecnicos
                   WHERE lower(trim(COALESCE(nome,'')))=lower(trim(?))
                     AND COALESCE(empresa_id, ?) = ?
                   ORDER BY id DESC LIMIT 1""",
                (nome, empresa_id, empresa_id)
            ))

        if not deve_ser_campo:
            if existente and existente.get('id'):
                execute('UPDATE campo_tecnicos SET ativo=0 WHERE id=?', (existente['id'],))
            return existente

        token = (existente or {}).get('token') or uuid.uuid4().hex
        if existente and existente.get('id'):
            if table_has_column('campo_tecnicos', 'user_id'):
                execute('UPDATE campo_tecnicos SET nome=?, email=?, telefone=?, ativo=?, user_id=?, token=? WHERE id=?',
                        (nome, email, telefone, ativo, user_id, token, existente['id']))
            else:
                execute('UPDATE campo_tecnicos SET nome=?, email=?, telefone=?, ativo=?, token=? WHERE id=?',
                        (nome, email, telefone, ativo, token, existente['id']))
            return row_to_dict(query_one('SELECT * FROM campo_tecnicos WHERE id=?', (existente['id'],)))

        cols = ['nome', 'email', 'telefone', 'empresa_id', 'ativo', 'criado_em', 'token']
        vals = [nome, email, telefone, empresa_id, ativo, now_str(), token]
        if table_has_column('campo_tecnicos', 'user_id'):
            cols.append('user_id')
            vals.append(user_id)
        q = ','.join(['?'] * len(cols))
        new_id = execute(f"INSERT INTO campo_tecnicos({','.join(cols)}) VALUES ({q})", tuple(vals))
        return row_to_dict(query_one('SELECT * FROM campo_tecnicos WHERE id=?', (new_id,)))
    except Exception as exc:
        _flask_app().logger.exception('Falha ao sincronizar usuário com técnico de campo')
        print('sincronizar_usuario_campo falhou:', exc)
        return None




def sincronizar_tecnico_usuario(tecnico_id=None, nome='', email='', telefone='', empresa_id=None, ativo=1, senha=''):
    """Mantém usuário visível quando técnico nasce/é editado pela aba Campo / WhatsApp."""
    try:
        empresa_id = int(empresa_id or current_company_id() or 0) or None
        nome = str(nome or '').strip()
        email = str(email or '').strip().lower()
        telefone = normalize_phone(telefone or '')
        ativo = 1 if str(ativo).lower() in ('1', 'true', 'sim', 'on', 'yes') or ativo == 1 else 0
        if not empresa_id or not nome:
            return None
        empresa = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=?', (empresa_id,))) or {}
        dominio = normalize_domain(empresa.get('dominio_email') or '')
        if not email:
            email = unique_email_for_domain(nome, dominio, ignore_user_id=None)
        existente = row_to_dict(query_one('SELECT * FROM users WHERE lower(email)=lower(?) LIMIT 1', (email,))) if email else None
        permissions = normalize_permissions(ROLE_PERMISSIONS.get('campo', []))
        if existente and existente.get('id'):
            if senha:
                execute('UPDATE users SET nome=?, email=?, senha_hash=?, perfil=?, empresa_id=?, is_super_admin=0, permissions=?, ativo=?, telefone=? WHERE id=?',
                        (nome, email, generate_password_hash(senha), 'campo', empresa_id, json.dumps(permissions, ensure_ascii=False), ativo, telefone, existente['id']))
            else:
                execute('UPDATE users SET nome=?, email=?, perfil=?, empresa_id=?, is_super_admin=0, permissions=?, ativo=?, telefone=? WHERE id=?',
                        (nome, email, 'campo', empresa_id, json.dumps(permissions, ensure_ascii=False), ativo, telefone, existente['id']))
            user_id = existente['id']
        else:
            senha_final = senha or '123456'
            user_id = execute('INSERT INTO users(nome,email,senha_hash,perfil,empresa_id,is_super_admin,permissions,ativo,criado_em,telefone) VALUES (?,?,?,?,?,?,?,?,?,?)',
                              (nome, email, generate_password_hash(senha_final), 'campo', empresa_id, 0, json.dumps(permissions, ensure_ascii=False), ativo, now_str(), telefone))
        if tecnico_id and table_has_column('campo_tecnicos', 'user_id'):
            execute('UPDATE campo_tecnicos SET user_id=?, email=? WHERE id=?', (user_id, email, tecnico_id))
        return row_to_dict(query_one('SELECT * FROM users WHERE id=?', (user_id,)))
    except Exception as exc:
        _flask_app().logger.exception('Falha ao sincronizar técnico com usuário')
        print('sincronizar_tecnico_usuario falhou:', exc)
        return None




def campo_numero_visivel(os_row=None, fallback_id=None):
    """Número amigável da O.S. para Campo/WhatsApp/app mobile."""
    os_row = os_row or {}

    def pick(key):
        try:
            if hasattr(os_row, 'keys') and key in os_row.keys():
                return os_row[key]
        except Exception:
            pass
        if isinstance(os_row, dict):
            return os_row.get(key)
        return None

    for key in ('numero_visivel', 'numero_os', 'nr_os', 'os_numero', 'id'):
        value = str(pick(key) or '').strip()
        if value:
            return value

    return str(fallback_id or '').strip() or '-'




def campo_tecnico_for_os_row(os_row):
    """Encontra o técnico da O.S. para envio automático de WhatsApp.

    Aceita responsável como nome, e-mail ou telefone.
    Não altera a O.S.; só procura o técnico cadastrado em campo_tecnicos.
    """
    os_row = os_row or {}
    empresa_id = row_get_value(os_row, 'empresa_id', None) or current_company_id()
    responsavel = str(row_get_value(os_row, 'responsavel', '') or '').strip()

    if not responsavel:
        return {}

    tel = re.sub(r'\D+', '', responsavel)

    try:
        row = row_to_dict(query_one(
            """SELECT * FROM campo_tecnicos
               WHERE COALESCE(empresa_id, ?) = ?
                 AND ativo=1
                 AND (
                   lower(trim(COALESCE(nome,''))) = lower(trim(?))
                   OR lower(trim(COALESCE(email,''))) = lower(trim(?))
                 )
               ORDER BY id DESC
               LIMIT 1""",
            (empresa_id, empresa_id, responsavel, responsavel)
        )) or {}
        if row:
            return row
    except Exception:
        pass

    if tel:
        try:
            rows = [dict(r) for r in query_all(
                """SELECT * FROM campo_tecnicos
                   WHERE COALESCE(empresa_id, ?) = ?
                     AND ativo=1
                   ORDER BY id DESC""",
                (empresa_id, empresa_id)
            )]
            for r in rows:
                rt = re.sub(r'\D+', '', str(r.get('telefone') or ''))
                if rt and (rt == tel or rt.endswith(tel) or tel.endswith(rt)):
                    return r
        except Exception:
            pass

    try:
        user = row_to_dict(query_one(
            """SELECT nome,email,telefone FROM users
               WHERE COALESCE(empresa_id, ?) = ?
                 AND ativo=1
                 AND (
                   lower(trim(COALESCE(nome,''))) = lower(trim(?))
                   OR lower(trim(COALESCE(email,''))) = lower(trim(?))
                 )
               LIMIT 1""",
            (empresa_id, empresa_id, responsavel, responsavel)
        )) or {}

        for value in (user.get('nome'), user.get('email'), user.get('telefone')):
            value = str(value or '').strip()
            if not value or value == responsavel:
                continue
            fake = dict(os_row)
            fake['responsavel'] = value
            found = campo_tecnico_for_os_row(fake)
            if found:
                return found
    except Exception:
        pass

    return {}




def campo_flag_atrasada_existente(os_row):
    """Lê o campo atrasada já salvo/calculado pelo sistema principal."""
    raw = row_get_value(os_row, 'atrasada', '')
    if raw is True:
        return True
    txt = str(raw or '').strip().lower()
    return txt in ('sim', 'true', '1', 'atrasada', 'yes', 's')




def campo_status_finalizado(os_row):
    """True quando a O.S. está encerrada em qualquer texto legado usado no sistema."""
    status = str(row_get_value(os_row, 'status', '') or '').strip().lower()
    finalizada = str(row_get_value(os_row, 'finalizada', '') or '').strip().lower()
    return (
        finalizada in ('sim', 'true', '1', 'finalizada', 'finalizado', 'concluida', 'concluída', 'concluido', 'concluído', 'entregue')
        or any(x in status for x in ('finalizada', 'finalizado', 'concluida', 'concluída', 'concluido', 'concluído', 'entregue'))
    )




def campo_status_pausado(os_row):
    status = str(row_get_value(os_row, 'status', '') or '').strip().lower()
    return 'pausada' in status or 'pausado' in status




def campo_status_em_andamento(os_row):
    status = str(row_get_value(os_row, 'status', '') or '').strip().lower()
    return status in ('em andamento', 'andamento', 'execução', 'execucao', 'iniciada', 'iniciado') or 'andamento' in status or 'execu' in status




def campo_os_iniciada(os_row):
    return bool(
        only_time_str(row_get_value(os_row, 'data_inicio', '') or row_get_value(os_row, 'campo_iniciado_em', ''))
        or campo_status_em_andamento(os_row)
        or campo_status_pausado(os_row)
    )




def campo_os_atrasada(os_row, hoje=None, dias_limite=3):
    """Regra de atraso do app de campo alinhada à tela principal de O.S.

    A tela desktop usa `os_is_overdue()` para aberta sem início. O app mobile deve
    refletir a mesma verdade para não aparecerem 2 atrasadas no celular e 3 no
    programa. Para pausadas, mantém a regra combinada de 3+ dias pausada.
    """
    os_row = os_row or {}

    if campo_status_finalizado(os_row):
        return False

    if campo_flag_atrasada_existente(os_row):
        return True

    try:
        if os_is_overdue(os_row, ref_date=hoje):
            return True
    except Exception:
        pass

    hoje = hoje or br_now().date()
    status = str(row_get_value(os_row, 'status', '') or '').strip().lower()

    data_os = _campo_parse_date(
        row_get_value(os_row, 'data', '') or
        row_get_value(os_row, 'criado_em', '') or
        row_get_value(os_row, 'created_at', '')
    )

    data_inicio = _campo_parse_date(
        row_get_value(os_row, 'data_inicio', '') or
        row_get_value(os_row, 'campo_iniciado_em', '')
    )

    data_pausa = _campo_parse_date(
        row_get_value(os_row, 'pausado_em', '') or
        row_get_value(os_row, 'data_pausa', '') or
        row_get_value(os_row, 'campo_pausado_em', '') or
        row_get_value(os_row, 'data_fim', '') or
        row_get_value(os_row, 'data_inicio', '')
    )

    if 'pausada' in status or 'pausado' in status:
        base = data_pausa or data_inicio or data_os
        return bool(base and (hoje - base).days >= dias_limite)

    return False



def _campo_parse_date(value):
    """Converte datas de O.S. em date com segurança."""
    if not value:
        return None
    try:
        if hasattr(value, 'date'):
            return value.date()
    except Exception:
        pass

    txt = str(value or '').strip()
    if not txt:
        return None

    txt_base = txt.split(' ')[0].strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(txt_base, fmt).date()
        except Exception:
            pass

    m = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', txt)
    if m:
        try:
            d, mo, y = m.group(1).split('/')
            y = int(y)
            if y < 100:
                y += 2000
            return datetime(int(y), int(mo), int(d)).date()
        except Exception:
            pass
    return None




def _campo_valid_files(field_name='imagens'):
    """Lê fotos do mobile de forma tolerante.

    Alguns navegadores de celular mandam entradas vazias no multipart.
    Aqui só contam arquivos reais, com nome e stream não vazia.
    """
    candidatos = []
    try:
        candidatos.extend(request.files.getlist(field_name) or [])
    except Exception:
        pass
    try:
        # fallback: alguns browsers usam o mesmo campo mas Flask pode expor em values misturados
        for key in request.files.keys():
            if key != field_name and key.startswith(field_name):
                candidatos.extend(request.files.getlist(key) or [])
    except Exception:
        pass

    validos = []
    for file in candidatos:
        if not file or not getattr(file, 'filename', ''):
            continue
        filename = str(file.filename or '').strip()
        if not filename:
            continue
        try:
            pos = file.stream.tell()
            file.stream.seek(0, os.SEEK_END)
            size = file.stream.tell()
            file.stream.seek(pos)
            if size <= 0:
                continue
            file.stream.seek(0)
        except Exception:
            try:
                file.stream.seek(0)
            except Exception:
                pass
        validos.append(file)
    return validos




def _campo_save_images(files, empresa_id):
    saved = []
    for file in files or []:
        if file and getattr(file, 'filename', ''):
            original = secure_filename(file.filename)
            if not original:
                continue
            stem, ext = os.path.splitext(original)
            if not ext:
                ext = '.jpg'
            unique_name = f'campo_{uuid.uuid4().hex}_{stem[:60]}.jpg'
            storage_path = _os_attachment_relpath(unique_name, empresa_id=empresa_id)
            try:
                file.stream.seek(0)
            except Exception:
                pass
            # Comprime a imagem antes de enviar (reduz tamanho e tempo de upload)
            try:
                from PIL import Image as _PILImage
                import io as _io
                raw = file.stream.read()
                img = _PILImage.open(_io.BytesIO(raw))
                # Converte para RGB se necessário (PNG com transparência, etc)
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                # Redimensiona se maior que 1600px
                max_side = 1600
                if max(img.width, img.height) > max_side:
                    ratio = max_side / max(img.width, img.height)
                    img = img.resize((int(img.width * ratio), int(img.height * ratio)), _PILImage.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, format='JPEG', quality=72, optimize=True)
                buf.seek(0)
                # Cria objeto compatível com upload_file_to_supabase
                class _FakeFile:
                    def __init__(self, b):
                        self.stream = b
                        self.mimetype = 'image/jpeg'
                        self.filename = unique_name
                    def read(self): return self.stream.read()
                fake = _FakeFile(buf)
                if upload_file_to_supabase(fake, storage_path, 'image/jpeg'):
                    saved.append(storage_path)
                    continue
            except Exception as compress_err:
                print(f'_campo_save_images: compressão falhou ({compress_err}), tentando original')
                try:
                    file.stream.seek(0)
                except Exception:
                    pass
            if upload_file_to_supabase(file, storage_path, getattr(file, 'mimetype', None)):
                saved.append(storage_path)
                continue
            print(f'_campo_save_images: upload Supabase falhou para {unique_name}')
    return saved




def get_tecnico_from_token():
    """Identifica técnico de campo pelo token enviado no header ou query."""
    payload = request.get_json(silent=True) or {}
    token = (
        request.headers.get('X-Tecnico-Token')
        or request.args.get('tecnico_token')
        or payload.get('tecnico_token')
        or ''
    ).strip().strip('/')
    if not token:
        auth = request.headers.get('Authorization', '')
        if auth.lower().startswith('bearer '):
            token = auth[7:].strip()
    if not token:
        return {}
    return campo_tecnico_por_token(token)
