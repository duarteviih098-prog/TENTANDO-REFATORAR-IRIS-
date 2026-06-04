"""Outlook / e-mail — envio, monitoramento e integração com Pagamentos."""
import email
import imaplib
import io
import json
import mimetypes
import os
import re
import smtplib
import threading
import time
import urllib.error as urllib_error
import urllib.parse as urllib_parse
import urllib.request as urllib_request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from app.shared.formatters import br_money, br_now, now_str, parse_br_date, parse_num
from app.shared.rows import row_to_dict

import pdfplumber
from pypdf import PdfReader

from app.config import PROJECT_ROOT

try:
    import pythoncom  # type: ignore
    import win32com.client as win32_client  # type: ignore
except Exception:
    pythoncom = None
    win32_client = None

BASE_DIR = PROJECT_ROOT

MONITOR_WORKER_LOCK = threading.Lock()
MONITOR_WORKER_THREAD = None
MONITOR_WORKER_STATE = {
    "enabled": False,
    "interval_seconds": 300,
    "running": False,
    "last_run_at": "",
    "last_status": "Aguardando",
    "last_summary": "Worker ainda não inicializado.",
    "last_error": "",
    "processed_total": 0,
    "applied_total": 0,
    "duplicates_total": 0,
}
def current_company_id():
    from app.auth import current_company_id as fn
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


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def USE_POSTGRES():
    from app.db import USE_POSTGRES as flag
    return flag


def config_get(key, default=None):
    row = query_one('SELECT valor FROM email_config WHERE chave=?', (key,))
    if not row:
        return default
    try:
        return json.loads(row['valor'])
    except Exception:
        return default




def config_set(key, value):
    execute('INSERT OR REPLACE INTO email_config(chave, valor) VALUES (?, ?)', (key, json.dumps(value, ensure_ascii=False)))




def email_greeting(ref=None):
    ref = ref or datetime.now()
    return 'Bom dia' if ref.hour < 12 else 'Boa tarde'




def split_emails(raw):
    return [item.strip() for item in str(raw or '').split(';') if item.strip()]




def normalize_email_block(raw):
    return ';'.join(split_emails(raw))




def digits_only(raw):
    return ''.join(ch for ch in str(raw or '') if ch.isdigit())




def clean_html_text(raw):
    text = re.sub(r'<br\s*/?>', '\n', str(raw or ''), flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('\r', '\n')
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()




def extract_email_body_from_message(msg):
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or '').lower()
            dispo = (part.get('Content-Disposition') or '').lower()
            if 'attachment' in dispo:
                continue
            try:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                decoded = payload.decode(charset, errors='ignore') if payload else ''
            except Exception:
                decoded = ''
            if ctype == 'text/plain' and decoded.strip():
                parts.append(decoded.strip())
            elif ctype == 'text/html' and decoded.strip():
                parts.append(clean_html_text(decoded))
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            decoded = payload.decode(charset, errors='ignore') if payload else ''
        except Exception:
            decoded = ''
        if (msg.get_content_type() or '').lower() == 'text/html':
            decoded = clean_html_text(decoded)
        if decoded.strip():
            parts.append(decoded.strip())
    return '\n\n'.join(p for p in parts if p).strip()




def parse_monitor_event(sender_email, subject, body):
    sender_email = (sender_email or '').strip().lower()
    subject = (subject or '').strip()
    body = clean_html_text(body)
    combined = f"{subject}\n{body}".strip()
    combined_lower = combined.lower()

    sc_candidates = []
    for pattern in [
        r'\bSC\s*[:#\-]?\s*(\d{2,})',
        r'Solicita(?:ç|c)[aã]o\s+de\s+(?:Materiais|Compra)\s*\(?\s*(\d{2,})\s*\)?',
        r'Documento\s*[:#\-]?\s*(\d{2,})',
    ]:
        sc_candidates.extend(re.findall(pattern, combined, flags=re.IGNORECASE))
    pd_candidates = []
    for pattern in [
        r'\bPedido\s*[:#\-]?\s*(\d{2,})',
        r'\bPD\s*[:#\-]?\s*(\d{2,})',
        r'n[úu]mero\s+do\s+pedido\s*[:#\-]?\s*(\d{2,})',
    ]:
        pd_candidates.extend(re.findall(pattern, combined, flags=re.IGNORECASE))

    numero_sc = digits_only(sc_candidates[0]) if sc_candidates else ''
    numero_pedido = digits_only(pd_candidates[0]) if pd_candidates else ''
    evento = 'ignorado'
    status = 'IGNORADO'
    sugestao_fluxo = ''
    notes = []

    if 'sc 100% fechada' in combined_lower:
        evento = 'sc_fechada_100'
        status = 'SC FECHADA'
        notes.append('Mensagem tratada como SC 100% fechada.')
        if numero_pedido:
            notes.append(f'Pedido identificado automaticamente: {numero_pedido}.')
    elif ('foi aprovado' in combined_lower or 'foi aprovada' in combined_lower) and ('solicita' in combined_lower and ('material' in combined_lower or 'compra' in combined_lower)):
        evento = 'sc_aprovada'
        status = 'SC APROVADA'
        sugestao_fluxo = 'compras'
        notes.append('SC aprovada detectada; sugerir envio para Compras.')
    elif numero_pedido:
        evento = 'pedido_identificado'
        status = 'PEDIDO IDENTIFICADO'
        notes.append('Número do pedido encontrado em e-mail monitorado.')

    return {
        'sender_email': sender_email,
        'subject': subject,
        'body': body,
        'numero_sc': numero_sc,
        'numero_pedido': numero_pedido,
        'evento': evento,
        'status': status,
        'sugestao_fluxo': sugestao_fluxo,
        'notes': notes,
        'excerpt': combined[:1800],
    }




def find_payment_for_monitor_event(numero_sc='', numero_pedido=''):
    numero_sc = digits_only(numero_sc)
    numero_pedido = digits_only(numero_pedido)
    if numero_sc:
        row = query_one("SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos WHERE REPLACE(REPLACE(REPLACE(COALESCE(numero_documento,''), ' ', ''), '-', ''), '/', '')=? ORDER BY id DESC LIMIT 1", (numero_sc,))
        if row:
            return row
    if numero_pedido:
        row = query_one("SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos WHERE REPLACE(REPLACE(REPLACE(COALESCE(sc_pedido,''), ' ', ''), '-', ''), '/', '')=? ORDER BY id DESC LIMIT 1", (numero_pedido,))
        if row:
            return row
    if numero_sc and numero_pedido:
        return query_one("SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos WHERE REPLACE(REPLACE(REPLACE(COALESCE(numero_documento,''), ' ', ''), '-', ''), '/', '')=? OR REPLACE(REPLACE(REPLACE(COALESCE(sc_pedido,''), ' ', ''), '-', ''), '/', '')=? ORDER BY id DESC LIMIT 1", (numero_sc, numero_pedido))
    return None




def apply_monitor_event(parsed):
    payment_row = find_payment_for_monitor_event(parsed.get('numero_sc'), parsed.get('numero_pedido'))
    payment = row_to_dict(payment_row) if payment_row else None
    notes = list(parsed.get('notes', []))
    linked_id = payment['id'] if payment else None
    applied = False

    if payment:
        if parsed['evento'] == 'sc_aprovada':
            execute('UPDATE pagamentos SET aprovado=?, fluxo_status=? WHERE id=?', ('Sim', 'SC APROVADA', payment['id']))
            applied = True
            notes.append(f"Registro #{payment['id']} marcado como SC aprovada.")
        if parsed.get('numero_pedido') and (not digits_only(payment.get('sc_pedido')) or digits_only(payment.get('sc_pedido')) != digits_only(parsed['numero_pedido'])):
            execute('UPDATE pagamentos SET sc_pedido=? WHERE id=?', (parsed['numero_pedido'], payment['id']))
            applied = True
            notes.append(f"Pedido {parsed['numero_pedido']} vinculado ao registro #{payment['id']}.")
        elif parsed.get('numero_pedido'):
            notes.append(f"Pedido {parsed['numero_pedido']} já estava vinculado ao registro #{payment['id']}.")
    elif parsed.get('numero_sc') or parsed.get('numero_pedido'):
        notes.append('Nenhum registro de Pagamentos foi localizado para vincular automaticamente.')

    return {'payment_id': linked_id, 'applied': applied, 'notes': notes}





def simulate_monitor_detection(sender_email, subject, body):
    parsed = parse_monitor_event(sender_email, subject, body)
    payment_row = find_payment_for_monitor_event(parsed.get('numero_sc'), parsed.get('numero_pedido'))
    payment = row_to_dict(payment_row) if payment_row else None
    notes = list(parsed.get('notes', []))
    if payment:
        notes.append(f"Vínculo provável localizado no registro #{payment['id']}.")
    elif parsed.get('numero_sc') or parsed.get('numero_pedido'):
        notes.append('Nenhum registro de Pagamentos seria vinculado automaticamente neste cenário.')
    return {
        'parsed': parsed,
        'payment_id': payment['id'] if payment else None,
        'notes': notes,
    }




def run_monitor_test_case(scenario_name, sender_email, subject, body, expected_evento='', expected_sc='', expected_pedido='', expected_pagamento_id=None):
    result = simulate_monitor_detection(sender_email, subject, body)
    parsed = result['parsed']
    checks = []
    checks.append((not expected_evento) or parsed.get('evento') == expected_evento)
    checks.append((not digits_only(expected_sc)) or digits_only(parsed.get('numero_sc')) == digits_only(expected_sc))
    checks.append((not digits_only(expected_pedido)) or digits_only(parsed.get('numero_pedido')) == digits_only(expected_pedido))
    checks.append((not expected_pagamento_id) or int(result.get('payment_id') or 0) == int(expected_pagamento_id))
    status = 'APROVADO' if all(checks) else 'DIVERGENTE'
    details = list(result['notes'])
    details.append(f"Esperado evento: {expected_evento or 'qualquer'} | Detectado: {parsed.get('evento') or '—'}")
    details.append(f"Esperado SC: {expected_sc or 'qualquer'} | Detectado: {parsed.get('numero_sc') or '—'}")
    details.append(f"Esperado Pedido: {expected_pedido or 'qualquer'} | Detectado: {parsed.get('numero_pedido') or '—'}")
    details.append(f"Esperado vínculo: {expected_pagamento_id or 'qualquer'} | Detectado: {result.get('payment_id') or '—'}")
    execute("INSERT INTO email_monitor_test_runs(quando, scenario_name, sender_email, subject, body_resumo, expected_evento, detected_evento, expected_sc, detected_sc, expected_pedido, detected_pedido, expected_pagamento_id, detected_pagamento_id, status, applied, duplicate, detalhes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now_str(), scenario_name, sender_email, subject[:240], clean_html_text(body)[:500], expected_evento, parsed.get('evento',''), digits_only(expected_sc), digits_only(parsed.get('numero_sc')), digits_only(expected_pedido), digits_only(parsed.get('numero_pedido')), expected_pagamento_id or None, result.get('payment_id'), status, 0, 0, '\n'.join(details)))
    return {'status': status, 'parsed': parsed, 'payment_id': result.get('payment_id'), 'details': details}




def built_in_monitor_test_scenarios():
    rows = [row_to_dict(r) for r in query_all("SELECT id, fornecedor, numero_documento, sc_pedido FROM pagamentos ORDER BY id DESC LIMIT 60")]
    with_sc = next((r for r in rows if digits_only(r.get('numero_documento'))), None)
    with_pd = next((r for r in rows if digits_only(r.get('sc_pedido'))), None)
    with_both = next((r for r in rows if digits_only(r.get('numero_documento')) and digits_only(r.get('sc_pedido'))), None) or with_pd or with_sc
    scenarios = []
    monitor_sender = (config_get('monitor_email', 'notificacao@approvo.com.br') or 'notificacao@approvo.com.br').strip()
    if with_sc:
        sc = digits_only(with_sc.get('numero_documento'))
        fornecedor = with_sc.get('fornecedor') or 'Teste'
        scenarios.append({
            'scenario_name': 'SC aprovada padrão',
            'sender_email': monitor_sender,
            'subject': f'O documento Solicitação de Materiais ({sc}) foi aprovado',
            'body': f'Filial: Matriz\\nValor: R$ 1.234,56\\nFornecedor: {fornecedor}',
            'expected_evento': 'sc_aprovada',
            'expected_sc': sc,
            'expected_pedido': '',
            'expected_pagamento_id': with_sc.get('id'),
        })
    if with_both:
        sc = digits_only(with_both.get('numero_documento'))
        pd = digits_only(with_both.get('sc_pedido'))
        scenarios.append({
            'scenario_name': 'SC 100% fechada com pedido',
            'sender_email': monitor_sender,
            'subject': f'SC {sc} finalizada',
            'body': f'Boa tarde. SC 100% fechada. Pedido {pd}.',
            'expected_evento': 'sc_fechada_100',
            'expected_sc': sc,
            'expected_pedido': pd,
            'expected_pagamento_id': with_both.get('id'),
        })
    if with_pd:
        pd = digits_only(with_pd.get('sc_pedido'))
        scenarios.append({
            'scenario_name': 'Pedido identificado isolado',
            'sender_email': monitor_sender,
            'subject': f'Atualização do Pedido {pd}',
            'body': f'Número do pedido: {pd}. Segue atualização.',
            'expected_evento': 'pedido_identificado',
            'expected_sc': '',
            'expected_pedido': pd,
            'expected_pagamento_id': with_pd.get('id'),
        })
    scenarios.append({
        'scenario_name': 'Ruído ignorado',
        'sender_email': monitor_sender,
        'subject': 'Mensagem aleatória sem SC nem pedido',
        'body': 'Apenas um aviso genérico sem dados estruturados.',
        'expected_evento': 'ignorado',
        'expected_sc': '',
        'expected_pedido': '',
        'expected_pagamento_id': None,
    })
    return scenarios




def monitor_provider_selected():
    return (config_get('monitor_provider', os.getenv('MONITOR_PROVIDER', 'imap')) or 'imap').strip().lower()




def monitor_credentials_ready(provider=None):
    provider = (provider or monitor_provider_selected() or 'imap').strip().lower()
    if provider == 'desktop':
        return os.name == 'nt'
    return all([
        os.getenv('MONITOR_IMAP_HOST', 'outlook.office365.com').strip(),
        os.getenv('MONITOR_IMAP_USER', '').strip(),
        os.getenv('MONITOR_IMAP_PASS', '').strip(),
    ])




def fetch_monitor_emails_imap(limit=10):
    host = os.getenv('MONITOR_IMAP_HOST', 'outlook.office365.com').strip()
    username = os.getenv('MONITOR_IMAP_USER', '').strip()
    password = os.getenv('MONITOR_IMAP_PASS', '').strip()
    folder = os.getenv('MONITOR_IMAP_FOLDER', 'INBOX').strip()
    sender_filter = (config_get('monitor_email', 'notificacao@approvo.com.br') or 'notificacao@approvo.com.br').strip()
    if not username or not password:
        raise RuntimeError('Credenciais de monitoramento IMAP ausentes. Preencha MONITOR_IMAP_USER e MONITOR_IMAP_PASS no ambiente.')
    imap = imaplib.IMAP4_SSL(host)
    imap.login(username, password)
    try:
        status, _ = imap.select(folder)
        if status != 'OK':
            raise RuntimeError(f'Não foi possível abrir a pasta {folder}.')
        status, data = imap.search(None, f'(UNSEEN FROM "{sender_filter}")')
        if status != 'OK':
            raise RuntimeError('Falha ao buscar e-mails monitorados no IMAP.')
        ids = [x for x in data[0].split() if x][-limit:]
        messages = []
        for msg_id in ids:
            status, fetched = imap.fetch(msg_id, '(RFC822)')
            if status != 'OK' or not fetched:
                continue
            raw = fetched[0][1]
            msg = email.message_from_bytes(raw)
            subject = str(email.header.make_header(email.header.decode_header(msg.get('Subject', ''))))
            sender = str(email.header.make_header(email.header.decode_header(msg.get('From', ''))))
            sender_match = re.search(r'<([^>]+)>', sender)
            sender_email = (sender_match.group(1) if sender_match else sender).strip()
            message_id = (msg.get('Message-ID') or f'imap-{msg_id.decode(errors="ignore")}').strip()
            body = extract_email_body_from_message(msg)
            # Extrai boletos/NFs de anexos PDF
            boletos_nf = extract_boleto_nf_from_email_message(msg)
            messages.append({'message_id': message_id, 'sender_email': sender_email, 'subject': subject, 'body': body, 'boletos_nf': boletos_nf})
        return messages
    finally:
        try:
            imap.logout()
        except Exception:
            pass




def fetch_monitor_emails_desktop(limit=10):
    if os.name != 'nt':
        raise RuntimeError('O monitoramento via Outlook do PC só funciona no Windows.')
    if win32_client is None or pythoncom is None:
        raise RuntimeError('Instale o pacote pywin32 para usar o Outlook do PC.')
    sender_filter = (config_get('monitor_email', 'notificacao@approvo.com.br') or 'notificacao@approvo.com.br').strip().lower()
    pythoncom.CoInitialize()
    try:
        outlook = win32_client.Dispatch('Outlook.Application')
        namespace = outlook.GetNamespace('MAPI')
        inbox = namespace.GetDefaultFolder(6)
        messages = inbox.Items
        messages.Sort('[ReceivedTime]', True)
        found = []
        for msg in messages:
            try:
                sender_email = (getattr(msg, 'SenderEmailAddress', '') or '').strip()
                if sender_filter and sender_email.lower() != sender_filter:
                    continue
                subject = (getattr(msg, 'Subject', '') or '').strip()
                body = (getattr(msg, 'Body', '') or '')
                message_id = (getattr(msg, 'EntryID', '') or f'desktop-{datetime.now().timestamp()}').strip()
                found.append({'message_id': message_id, 'sender_email': sender_email, 'subject': subject, 'body': body})
                if len(found) >= max(1, int(limit or 10)):
                    break
            except Exception:
                continue
        return found
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass




def fetch_monitor_emails(limit=10):
    provider = monitor_provider_selected()
    if provider == 'desktop':
        return fetch_monitor_emails_desktop(limit=limit)
    return fetch_monitor_emails_imap(limit=limit)




def process_monitor_payload(message_id, sender_email, subject, body, boletos_nf=None):
    source_id = (message_id or '').strip() or f"manual-{datetime.now().timestamp()}"
    existing = query_one('SELECT id, source_message_id FROM email_monitor_events WHERE source_message_id=?', (source_id,))
    if existing:
        return {'duplicate': True, 'event_id': existing['id'], 'parsed': row_to_dict(existing), 'applied': False, 'notes': ['Mensagem já processada anteriormente.']}
    parsed = parse_monitor_event(sender_email, subject, body)
    applied_info = apply_monitor_event(parsed)
    notes = applied_info['notes']
    sql = "INSERT INTO email_monitor_events(quando, source_message_id, remetente, assunto, corpo_resumo, evento, status_processamento, numero_sc, numero_pedido, pagamento_id, sugestao_fluxo, popup_status, detalhes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    event_id = execute(sql, (now_str(), source_id, parsed['sender_email'], parsed['subject'], parsed['excerpt'], parsed['evento'], parsed['status'], parsed['numero_sc'], parsed['numero_pedido'], applied_info['payment_id'], parsed['sugestao_fluxo'], 'novo' if parsed['evento'] in ('sc_aprovada','sc_fechada_100') or parsed['sugestao_fluxo'] else 'novo', json.dumps(notes, ensure_ascii=False)))
    # Processa boletos/NFs detectados nos anexos
    boleto_events = []
    for bnf in (boletos_nf or []):
        if not (bnf.get('valor') or bnf.get('vencimento')):
            continue
        bnf_source_id = f"{source_id}-bnf-{bnf.get('filename','')}"
        existing_bnf = query_one('SELECT id FROM email_monitor_events WHERE source_message_id=?', (bnf_source_id,))
        if existing_bnf:
            continue
        bnf_details = [
            f"Arquivo: {bnf.get('filename','')}",
            f"Tipo: {bnf.get('tipo','').upper()}",
            f"Valor: R$ {bnf.get('valor','')}",
            f"Vencimento: {bnf.get('vencimento','')}",
            f"Fornecedor: {bnf.get('fornecedor','') or 'não identificado'}",
        ]
        status_txt = f"{'NF' if bnf.get('tipo') == 'nf' else 'BOLETO'} DETECTADO — R$ {bnf.get('valor','')} — Venc. {bnf.get('vencimento','')}"
        bnf_event_id = execute(sql, (now_str(), bnf_source_id, sender_email, subject, bnf.get('texto_resumo','')[:400], 'boleto_nf_detectado', status_txt, '', '', None, 'boleto_nf', 'novo', json.dumps(bnf_details, ensure_ascii=False)))
        boleto_events.append({'event_id': bnf_event_id, 'dados': bnf})
    return {'duplicate': False, 'event_id': event_id, 'parsed': parsed, 'applied': applied_info['applied'], 'notes': notes, 'boleto_events': boleto_events}




def monitor_status_snapshot():
    provider = monitor_provider_selected()
    return {
        'monitor_provider': provider,
        'monitor_ready': monitor_credentials_ready(provider),
        'monitor_host': os.getenv('MONITOR_IMAP_HOST', 'outlook.office365.com').strip(),
        'monitor_user': os.getenv('MONITOR_IMAP_USER', '').strip(),
    }




def list_pending_monitor_alerts(limit=6):
    cols = select_existing_columns('email_monitor_events', [
        'id', 'quando', 'evento', 'status_processamento', 'sugestao_fluxo',
        'popup_status', 'numero_sc', 'numero_pedido', 'pagamento_id',
        'detalhes_json', 'assunto', 'remetente', 'corpo_resumo'
    ])
    # Filtra só por colunas que existem
    has_popup = table_has_column('email_monitor_events', 'popup_status')
    has_evento = table_has_column('email_monitor_events', 'evento')
    has_fluxo = table_has_column('email_monitor_events', 'sugestao_fluxo')
    where_parts = []
    if has_popup:
        where_parts.append("COALESCE(popup_status,'novo')='novo'")
    if has_evento and has_fluxo:
        where_parts.append("(evento IN ('sc_aprovada','sc_fechada_100','boleto_nf_detectado') OR sugestao_fluxo!='')")
    elif has_evento:
        where_parts.append("evento IN ('sc_aprovada','sc_fechada_100','boleto_nf_detectado')")
    where_sql = (' WHERE ' + ' AND '.join(where_parts)) if where_parts else ''
    rows = query_all(f'SELECT {cols} FROM email_monitor_events{where_sql} ORDER BY id DESC LIMIT ?', (limit,))
    return [row_to_dict(r) for r in rows]




def mark_monitor_event_popup(event_id, status):
    allowed = {'novo', 'dispensado', 'acao_tomada'}
    status = status if status in allowed else 'dispensado'
    execute('UPDATE email_monitor_events SET popup_status=?, popup_dispensado_em=? WHERE id=?', (status, now_str(), event_id))




def monitor_worker_enabled():
    return os.getenv('ENABLE_MONITOR_WORKER', '0').strip().lower() in ('1', 'true', 'yes', 'on')




def monitor_worker_interval_seconds():
    raw = os.getenv('MONITOR_INTERVAL_SECONDS', '300').strip()
    try:
        val = int(raw)
    except Exception:
        val = 180
    return max(30, val)




def update_monitor_worker_state(**kwargs):
    with MONITOR_WORKER_LOCK:
        MONITOR_WORKER_STATE.update(kwargs)




def get_monitor_worker_state():
    with MONITOR_WORKER_LOCK:
        state = dict(MONITOR_WORKER_STATE)
    state['enabled'] = monitor_worker_enabled()
    state['interval_seconds'] = monitor_worker_interval_seconds()
    state['running'] = bool(MONITOR_WORKER_THREAD and MONITOR_WORKER_THREAD.is_alive())
    return state




def run_monitor_cycle(limit=10):
    messages = fetch_monitor_emails(limit=limit)
    processed = duplicates = applied = boletos = 0
    for msg in messages:
        result = process_monitor_payload(msg['message_id'], msg['sender_email'], msg['subject'], msg['body'], boletos_nf=msg.get('boletos_nf', []))
        processed += 1
        duplicates += 1 if result.get('duplicate') else 0
        applied += 1 if result.get('applied') else 0
        boletos += len(result.get('boleto_events', []))
    return {'processed': processed, 'duplicates': duplicates, 'applied': applied, 'boletos': boletos}




def monitor_worker_loop():
    update_monitor_worker_state(enabled=monitor_worker_enabled(), interval_seconds=monitor_worker_interval_seconds(), running=True, last_status='INICIANDO')
    while True:
        interval = monitor_worker_interval_seconds()
        update_monitor_worker_state(enabled=monitor_worker_enabled(), interval_seconds=interval, running=True)
        if not monitor_worker_enabled():
            update_monitor_worker_state(last_status='PAUSADO', last_summary='Worker desativado pelo ambiente. Dormindo até nova checagem.')
            time.sleep(interval)
            continue
        try:
            summary = run_monitor_cycle(limit=min(20, max(1, int(os.getenv('MONITOR_BATCH_LIMIT', '10') or '10'))))
            update_monitor_worker_state(
                last_run_at=now_str(),
                last_status='OK',
                last_summary=f"{summary['processed']} lidas / {summary['applied']} aplicadas / {summary['duplicates']} duplicadas",
                last_error='',
                processed_total=MONITOR_WORKER_STATE.get('processed_total', 0) + summary['processed'],
                applied_total=MONITOR_WORKER_STATE.get('applied_total', 0) + summary['applied'],
                duplicates_total=MONITOR_WORKER_STATE.get('duplicates_total', 0) + summary['duplicates'],
            )
        except Exception as exc:
            update_monitor_worker_state(last_run_at=now_str(), last_status='ERRO', last_summary='Falha no ciclo automático.', last_error=str(exc)[:240])
        time.sleep(interval)




def maybe_start_monitor_worker():
    global MONITOR_WORKER_THREAD
    if not monitor_worker_enabled():
        update_monitor_worker_state(enabled=False, interval_seconds=monitor_worker_interval_seconds(), running=False, last_status='DESATIVADO')
        return
    if MONITOR_WORKER_THREAD and MONITOR_WORKER_THREAD.is_alive():
        return
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        return
    update_monitor_worker_state(enabled=True, interval_seconds=monitor_worker_interval_seconds())
    MONITOR_WORKER_THREAD = threading.Thread(target=monitor_worker_loop, name='gg-monitor-worker', daemon=True)
    MONITOR_WORKER_THREAD.start()




def extract_pdf_text(pdf_path):
    chunks = []
    try:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages[:5]:
            chunks.append(page.extract_text() or '')
    except Exception:
        pass
    text = '\n'.join(chunks).strip()
    if text:
        return text
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = []
            for page in pdf.pages[:5]:
                pages.append(page.extract_text() or '')
        return '\n'.join(pages).strip()
    except Exception:
        return ''




def extract_boleto_nf_from_email_message(msg):
    """Extrai PDFs de anexo de um email e tenta extrair valor, vencimento e fornecedor."""
    import io as _io
    results = []
    for part in msg.walk():
        ct = part.get_content_type()
        cd = str(part.get('Content-Disposition') or '')
        fname = part.get_filename() or ''
        is_pdf = ct == 'application/pdf' or fname.lower().endswith('.pdf')
        if not is_pdf or 'attachment' not in cd.lower():
            continue
        try:
            data = part.get_payload(decode=True)
            if not data:
                continue
            text = ''
            with pdfplumber.open(_io.BytesIO(data)) as pdf:
                for page in pdf.pages[:4]:
                    text += (page.extract_text() or '') + '\n'
            if not text.strip():
                continue
            # Extrai vencimento
            vencimento = ''
            for pat in [
                r'[Vv]encimento[\s:]*(\d{2}/\d{2}/\d{4})',
                r'VENCIMENTO[\s:]*(\d{2}/\d{2}/\d{4})',
                r'[Vv]enc[\s.:]*(\d{2}/\d{2}/\d{4})',
                r'[Pp]ag[aá]vel[^\d]*(\d{2}/\d{2}/\d{4})',
                r'DATA\s+DE\s+VENCIMENTO[\s:]*(\d{2}/\d{2}/\d{4})',
            ]:
                m = re.search(pat, text)
                if m:
                    parts = m.group(1).split('/')
                    if len(parts) == 3 and int(parts[2]) >= 2020:
                        vencimento = m.group(1)
                        break
            # Extrai valor
            valor = ''
            for pat in [
                r'[Vv]alor\s+[Cc]obrado[\s:R$]*([0-9.,]+)',
                r'[Vv]alor\s+[Dd]ocumento[\s:R$]*([0-9.,]+)',
                r'[Vv]alor\s+[Dd]o\s+[Dd]ocumento[\s:R$]*([0-9.,]+)',
                r'[Tt]otal[\s:R$]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',
                r'[Vv]alor[\s:R$]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',
                r'R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',
            ]:
                m = re.search(pat, text)
                if m:
                    valor = m.group(1).strip()
                    break
            # Extrai CNPJ/fornecedor
            fornecedor = ''
            for pat in [
                r'(?:Cedente|Benefici[aá]rio|Raz[aã]o\s+Social|Empresa|Fornecedor)[\s:]*([A-Za-zÀ-ú\s&.,]{5,60})',
            ]:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    fornecedor = m.group(1).strip()[:60]
                    break
            # Detecta tipo
            tipo = 'nf' if any(x in fname.lower() + text[:500].lower() for x in ['nota fiscal', 'nf-e', 'danfe', 'nfe']) else 'boleto'
            if valor or vencimento:
                results.append({
                    'filename': fname,
                    'tipo': tipo,
                    'valor': valor,
                    'vencimento': vencimento,
                    'fornecedor': fornecedor,
                    'texto_resumo': text[:800],
                })
        except Exception as exc:
            print(f'extract_boleto_nf_from_email_message: erro ao ler {fname}: {exc}')
    return results




def extract_boleto_due_date(pdf_path):
    text = extract_pdf_text(pdf_path)
    if not text:
        return {'date': '', 'source': 'pdf_sem_texto', 'text_excerpt': ''}
    patterns = [
        r'Vencimento\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})',
        r'VENCIMENTO\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})',
        r'Pag[aá]vel[^\d]*(\d{2}/\d{2}/\d{4})',
        r'VALOR\s+DOCUMENTO.*?(\d{2}/\d{2}/\d{4})',
        r'(\d{2}/\d{2}/\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            candidate = match.group(1)
            parsed = parse_br_date(candidate)
            if parsed:
                return {'date': parsed.strftime('%d/%m/%Y'), 'source': 'boleto_pdf', 'text_excerpt': text[:1200]}
    return {'date': '', 'source': 'nao_identificado', 'text_excerpt': text[:1200]}




def classify_attachment(path_like):
    name = Path(str(path_like)).name.lower()
    if 'boleto' in name:
        return 'boleto'
    if 'orc' in name or 'cotacao' in name or 'proposta' in name:
        return 'orcamento'
    if 'nf' in name or 'nota' in name or 'danfe' in name:
        return 'nf'
    return 'outro'




def analyze_attachment_set(flow, attachment_files):
    analysis = {'can_send': True, 'block_reason': '', 'warnings': [], 'items': []}
    counts = {'nf': 0, 'boleto': 0, 'orcamento': 0, 'outro': 0}
    boleto_due_date = ''
    boleto_source = ''
    for path in attachment_files:
        kind = classify_attachment(path)
        counts[kind] = counts.get(kind, 0) + 1
        item = {'path': path, 'name': path.name, 'kind': kind, 'due_date': ''}
        if kind == 'boleto' and path.suffix.lower() == '.pdf':
            due = extract_boleto_due_date(path)
            item['due_date'] = due.get('date', '')
            item['due_source'] = due.get('source', '')
            if due.get('date') and not boleto_due_date:
                boleto_due_date = due['date']
                boleto_source = due.get('source', '')
        analysis['items'].append(item)
    analysis['counts'] = counts
    analysis['boleto_due_date'] = boleto_due_date
    analysis['boleto_due_source'] = boleto_source

    if flow == 'compras':
        if counts['orcamento'] == 0:
            analysis['warnings'].append('Nenhum orçamento elegível foi encontrado para Compras.')
        non_budget = counts['nf'] + counts['boleto'] + counts['outro']
        if non_budget:
            analysis['warnings'].append('Compras usa somente orçamento; os demais anexos foram ignorados na preparação.')
    else:
        has_nf = counts['nf'] > 0
        has_boleto = counts['boleto'] > 0
        if not has_nf and not has_boleto:
            analysis['can_send'] = False
            analysis['block_reason'] = 'Envio bloqueado: para Contábil é obrigatório existir NF ou boleto. Sem os dois, o sistema não envia.'
        elif not has_nf or not has_boleto:
            missing = 'NF' if not has_nf else 'boleto'
            analysis['warnings'].append(f'Alerta: está faltando {missing}. O envio continua liberado, mas exige conferência manual.')
        if has_boleto and not boleto_due_date:
            analysis['warnings'].append('O boleto foi encontrado, mas o vencimento não pôde ser lido automaticamente do PDF.')
    return analysis




def choose_flow_attachments(flow, payment):
    if flow == 'compras':
        return list(payment.get('anexos_orcamento', []))
    selected = []
    selected.extend(list(payment.get('anexos_nf', [])))
    selected.extend(list(payment.get('anexos_boleto', [])))
    return selected




def load_email_center():
    senders = query_all('SELECT * FROM email_senders ORDER BY is_default DESC, nome ASC, id DESC')
    contacts = query_all('SELECT * FROM email_contacts ORDER BY area ASC, nome ASC, id DESC')
    templates = {r['chave']: r['valor'] for r in query_all("SELECT chave, valor FROM email_templates ORDER BY chave") }
    return senders, contacts, templates




def default_template_values():
    return {
        'compras_subject': 'SOLICITAÇÃO DE COMPRA {numero_sc}',
        'compras_body': '{saudacao},\n\nSegue solicitação de compra para aprovação.\n\nSC: {numero_sc}\nFornecedor: {fornecedor}\nValor: {valor}\nServiço/Objeto: {descricao}\n\nAtenciosamente,',
        'contabil_subject': 'LANÇAMENTO DA NOTA - PEDIDO {numero_pd}',
        'contabil_body': '{saudacao},\n\nSegue NF e Boleto para pagamento.\n\nPedido: {numero_pd}\nFornecedor: {fornecedor}\nValor: {valor}\nServiço/Objeto: {descricao}\nLocal/Unidade: {local_unidade}\nForma de pagamento: {forma_pagamento}\nVencimento: {vencimento}\n\nAtenciosamente,',
        'monitor_email': 'notificacao@approvo.com.br',
        'email_provider': 'desktop',
        'monitor_provider': 'desktop',
    }




def build_email_payload(flow, payment_row):
    payment = row_to_dict(payment_row) if payment_row else {}
    _, contacts, templates = load_email_center()
    templates = {**default_template_values(), **templates}
    saudacao = email_greeting()
    numero_sc = payment.get('numero_documento', '')
    numero_pd = payment.get('sc_pedido', '')
    valor_fmt = br_money(payment.get('valor'))
    attachments = choose_flow_attachments(flow, payment)
    attachment_files = resolve_attachment_paths(attachments)
    attachment_analysis = analyze_attachment_set(flow, attachment_files)
    vencimento = payment.get('nf_proposta', '')
    if flow == 'contabil' and attachment_analysis.get('boleto_due_date'):
        vencimento = attachment_analysis['boleto_due_date']
    tokens = {
        'saudacao': saudacao,
        'numero_sc': numero_sc,
        'numero_pd': numero_pd,
        'fornecedor': payment.get('fornecedor', ''),
        'valor': valor_fmt,
        'descricao': payment.get('descricao_servico', ''),
        'local_unidade': f"{payment.get('sistema','')} / {payment.get('equipamento','')}".strip(' /'),
        'forma_pagamento': payment.get('tipo_documento', ''),
        'vencimento': vencimento,
    }
    if flow == 'compras':
        subject = templates['compras_subject'].format(**tokens)
        body = templates['compras_body'].format(**tokens)
        area = 'Compras'
    else:
        subject = templates['contabil_subject'].format(**tokens)
        body = templates['contabil_body'].format(**tokens)
        area = 'Contábil'
    area_contacts = [dict(r) for r in contacts if (r['area'] or '').lower() == area.lower()]
    to = ';'.join([r['emails'] for r in area_contacts if (r['tipo'] or '').upper() == 'TO'])
    cc = ';'.join([r['emails'] for r in area_contacts if (r['tipo'] or '').upper() == 'CC'])
    warnings = list(attachment_analysis.get('warnings', []))
    return {
        'flow': flow,
        'area': area,
        'subject': subject,
        'body': body,
        'to': normalize_email_block(to),
        'cc': normalize_email_block(cc),
        'attachments': attachments,
        'payment': payment,
        'warnings': warnings,
        'vencimento_detectado': vencimento,
        'attachment_analysis': attachment_analysis,
    }






def get_default_sender():
    senders, _, _ = load_email_center()
    if not senders:
        return {'id': None, 'email': '', 'provider': config_get('email_provider', 'desktop'), 'nome': ''}
    preferred = next((dict(s) for s in senders if s['is_default'] and s['ativo']), None)
    if preferred:
        return preferred
    first_active = next((dict(s) for s in senders if s['ativo']), None)
    return first_active or dict(senders[0])




def graph_credentials_ready():
    return all([
        os.getenv('OUTLOOK_TENANT_ID'),
        os.getenv('OUTLOOK_CLIENT_ID'),
        os.getenv('OUTLOOK_CLIENT_SECRET'),
    ])




def smtp_credentials_ready():
    return all([
        os.getenv('SMTP_HOST', 'smtp.office365.com'),
        os.getenv('SMTP_USER') or os.getenv('OUTLOOK_SMTP_USER'),
        os.getenv('SMTP_PASS') or os.getenv('OUTLOOK_SMTP_PASS'),
    ])




def provider_readiness(provider):
    provider = (provider or config_get('email_provider', 'desktop') or 'desktop').lower()
    if provider == 'desktop':
        return os.name == 'nt' and win32_client is not None and pythoncom is not None
    if provider == 'smtp':
        return smtp_credentials_ready()
    return graph_credentials_ready()




def resolve_attachment_paths(items):
    resolved = []
    for raw in items or []:
        if not raw:
            continue
        raw = str(raw).strip()
        candidate = BASE_DIR / raw.lstrip('/\\') if raw.startswith('static/') else BASE_DIR / raw
        if not candidate.exists() and raw.startswith('/'):
            candidate = BASE_DIR / raw.lstrip('/\\')
        if candidate.exists() and candidate.is_file():
            resolved.append(candidate)
    return resolved




def can_send_payload(flow, attachment_files):
    analysis = analyze_attachment_set(flow, attachment_files)
    return analysis['can_send'], analysis['block_reason']




def build_graph_message(sender_email, to_list, cc_list, subject, body, attachment_files):
    msg = {
        'subject': subject,
        'body': {'contentType': 'Text', 'content': body},
        'toRecipients': [{'emailAddress': {'address': addr}} for addr in to_list],
        'ccRecipients': [{'emailAddress': {'address': addr}} for addr in cc_list],
        'attachments': [],
    }
    for path in attachment_files:
        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or 'application/octet-stream'
        with open(path, 'rb') as fh:
            content = fh.read()
        msg['attachments'].append({
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': path.name,
            'contentType': mime_type,
            'contentBytes': __import__('base64').b64encode(content).decode('ascii'),
        })
    return {'message': msg, 'saveToSentItems': True}




def acquire_graph_token():
    tenant = os.getenv('OUTLOOK_TENANT_ID', '').strip()
    client_id = os.getenv('OUTLOOK_CLIENT_ID', '').strip()
    client_secret = os.getenv('OUTLOOK_CLIENT_SECRET', '').strip()
    if not all([tenant, client_id, client_secret]):
        raise RuntimeError('Credenciais do Microsoft Graph ausentes. Preencha OUTLOOK_TENANT_ID, OUTLOOK_CLIENT_ID e OUTLOOK_CLIENT_SECRET no ambiente.')
    url = f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
    payload = urllib_parse.urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }).encode('utf-8')
    req = urllib_request.Request(url, data=payload, method='POST', headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'Falha ao autenticar no Microsoft Graph: {detail or exc.reason}') from exc
    token = data.get('access_token')
    if not token:
        raise RuntimeError('O Microsoft Graph não retornou access_token.')
    return token




def send_via_graph(sender_email, to_list, cc_list, subject, body, attachment_files):
    token = acquire_graph_token()
    endpoint = f'https://graph.microsoft.com/v1.0/users/{urllib_parse.quote(sender_email)}/sendMail'
    payload = build_graph_message(sender_email, to_list, cc_list, subject, body, attachment_files)
    req = urllib_request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), method='POST', headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    })
    try:
        with urllib_request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 202):
                raise RuntimeError(f'Graph respondeu com status inesperado: {resp.status}')
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'Falha no envio via Microsoft Graph: {detail or exc.reason}') from exc




def send_via_smtp(sender_email, to_list, cc_list, subject, body, attachment_files):
    host = os.getenv('SMTP_HOST', 'smtp.office365.com').strip()
    port = int(os.getenv('SMTP_PORT', '587').strip())
    username = os.getenv('SMTP_USER', os.getenv('OUTLOOK_SMTP_USER', '')).strip()
    password = os.getenv('SMTP_PASS', os.getenv('OUTLOOK_SMTP_PASS', '')).strip()
    if not username or not password:
        raise RuntimeError('Credenciais SMTP ausentes. Preencha SMTP_USER e SMTP_PASS no ambiente.')
    msg = EmailMessage()
    msg['From'] = sender_email
    msg['To'] = ', '.join(to_list)
    if cc_list:
        msg['Cc'] = ', '.join(cc_list)
    msg['Subject'] = subject
    msg.set_content(body)
    for path in attachment_files:
        mime_type, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime_type.split('/', 1) if mime_type else ('application', 'octet-stream'))
        with open(path, 'rb') as fh:
            msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype, filename=path.name)
    try:
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg, from_addr=sender_email, to_addrs=to_list + cc_list)
    except smtplib.SMTPException as exc:
        raise RuntimeError(f'Falha no envio via SMTP Outlook: {exc}') from exc






def send_via_desktop(sender_email, to_list, cc_list, subject, body, attachment_files):
    if os.name != 'nt':
        raise RuntimeError('O envio pelo Outlook do PC só funciona no Windows.')
    if win32_client is None or pythoncom is None:
        raise RuntimeError('Instale o pacote pywin32 para usar o Outlook do PC.')
    pythoncom.CoInitialize()
    try:
        outlook = win32_client.Dispatch('Outlook.Application')
        namespace = outlook.GetNamespace('MAPI')
        mail = outlook.CreateItem(0)
        # tenta usar a conta correspondente ao remetente, quando existir
        if sender_email:
            try:
                for account in namespace.Folders:
                    addr = getattr(account, 'Name', '') or ''
                    if sender_email.lower() in addr.lower():
                        mail._oleobj_.Invoke(*(64209, 0, 8, 0, account))
                        break
            except Exception:
                pass
        mail.To = '; '.join(to_list)
        if cc_list:
            mail.CC = '; '.join(cc_list)
        mail.Subject = subject
        mail.Body = body
        for path in attachment_files:
            if path and path.exists():
                mail.Attachments.Add(str(path))
        mail.Send()
    except Exception as exc:
        raise RuntimeError(f'Falha no envio via Outlook do PC: {exc}') from exc
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass



def send_real_email(sender_row, to_raw, cc_raw, subject, body, attachment_items):
    sender = dict(sender_row) if sender_row else {}
    sender_email = (sender.get('email') or '').strip()
    if not sender_email:
        raise RuntimeError('Nenhum remetente válido foi selecionado.')
    to_list = split_emails(to_raw)
    cc_list = split_emails(cc_raw)
    if not to_list:
        raise RuntimeError('Preencha ao menos um destinatário principal.')
    attachment_files = resolve_attachment_paths(attachment_items)
    provider = (sender.get('provider') or config_get('email_provider', 'desktop') or 'desktop').lower()
    if provider == 'desktop':
        send_via_desktop(sender_email, to_list, cc_list, subject, body, attachment_files)
    elif provider == 'smtp':
        send_via_smtp(sender_email, to_list, cc_list, subject, body, attachment_files)
    else:
        send_via_graph(sender_email, to_list, cc_list, subject, body, attachment_files)
    return {'provider': provider, 'attachments': attachment_files, 'to_list': to_list, 'cc_list': cc_list, 'sender_email': sender_email}



