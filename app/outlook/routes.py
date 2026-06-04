"""Rotas /outlook/* — centro de e-mail e monitoramento."""
import csv
import io
import json
from datetime import datetime
from app.shared.formatters import br_money, br_now, now_str, parse_br_date, parse_num
from app.shared.rows import row_to_dict

from flask import flash, jsonify, redirect, render_template, request, send_file, url_for

from app.auth.decorators import require_permission
from app.db import USE_POSTGRES
from app.outlook.services import (
    analyze_attachment_set,
    build_email_payload,
    built_in_monitor_test_scenarios,
    can_send_payload,
    config_get,
    config_set,
    default_template_values,
    fetch_monitor_emails,
    get_default_sender,
    get_monitor_worker_state,
    graph_credentials_ready,
    list_pending_monitor_alerts,
    load_email_center,
    mark_monitor_event_popup,
    monitor_credentials_ready,
    monitor_provider_selected,
    monitor_status_snapshot,
    normalize_email_block,
    process_monitor_payload,
    provider_readiness,
    resolve_attachment_paths,
    run_monitor_test_case,
    send_real_email,
    smtp_credentials_ready,
)
from app.config import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT


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


def outlook_monitor_events_export():
    monitor_event_filter = (request.args.get('monitor_event') or '').strip()
    monitor_popup_filter = (request.args.get('monitor_popup') or '').strip()
    monitor_status_filter = (request.args.get('monitor_status') or '').strip()
    monitor_link_filter = (request.args.get('monitor_link') or '').strip()
    monitor_flow_filter = (request.args.get('monitor_flow') or '').strip()
    monitor_from = (request.args.get('monitor_from') or '').strip()
    monitor_to = (request.args.get('monitor_to') or '').strip()
    monitor_search = (request.args.get('monitor_search') or '').strip()
    sql = 'SELECT ' + select_existing_columns('email_monitor_events', [
        'id', 'quando', 'source_message_id', 'remetente', 'assunto',
        'numero_sc', 'numero_pedido', 'evento', 'status_processamento',
        'sugestao_fluxo', 'pagamento_id', 'popup_status', 'detalhes', 'corpo_resumo',
        'detalhes_json'
    ]) + ' FROM email_monitor_events WHERE 1=1'
    params = []
    if monitor_event_filter:
        sql += ' AND evento=?'
        params.append(monitor_event_filter)
    if monitor_popup_filter:
        sql += " AND COALESCE(popup_status,'novo')=?"
        params.append(monitor_popup_filter)
    if monitor_status_filter:
        sql += ' AND status_processamento LIKE ?'
        params.append(f'%{monitor_status_filter}%')
    if monitor_link_filter == 'vinculado':
        sql += ' AND pagamento_id IS NOT NULL'
    elif monitor_link_filter == 'nao_vinculado':
        sql += ' AND pagamento_id IS NULL'
    if monitor_flow_filter:
        sql += ' AND sugestao_fluxo=?'
        params.append(monitor_flow_filter)
    if monitor_from:
        sql += ' AND substr(quando,1,10) >= ?'
        params.append(monitor_from)
    if monitor_to:
        sql += ' AND substr(quando,1,10) <= ?'
        params.append(monitor_to)
    if monitor_search:
        sql += ' AND (assunto LIKE ? OR remetente LIKE ? OR numero_sc LIKE ? OR numero_pedido LIKE ? OR corpo_resumo LIKE ? OR status_processamento LIKE ?)'
        token = f'%{monitor_search}%'
        params.extend([token] * 6)
    sql += ' ORDER BY id DESC LIMIT 1000'
    rows = [row_to_dict(r) for r in query_all(sql, tuple(params))]
    import csv
    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(['id','quando','evento','status_processamento','popup_status','remetente','assunto','numero_sc','numero_pedido','pagamento_id','sugestao_fluxo','detalhes'])
    for r in rows:
        detalhes = ' | '.join(r.get('detalhes_json') or []) if isinstance(r.get('detalhes_json'), list) else str(r.get('detalhes_json') or '')
        writer.writerow([r.get('id'),r.get('quando'),r.get('evento'),r.get('status_processamento'),r.get('popup_status'),r.get('remetente'),r.get('assunto'),r.get('numero_sc'),r.get('numero_pedido'),r.get('pagamento_id'),r.get('sugestao_fluxo'),detalhes])
    mem = io.BytesIO(sio.getvalue().encode('utf-8-sig'))
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name='historico_monitoramento.csv')



@require_permission('edit_pagamentos')
def outlook_monitor_event_confirmar_boleto(event_id):
    """Cria um lançamento em Pagamentos a partir de um alerta de boleto/NF detectado."""
    event = row_to_dict(query_one('SELECT * FROM email_monitor_events WHERE id=?', (event_id,))) or {}
    if not event:
        flash('Evento não encontrado.', 'danger')
        return redirect(url_for('outlook_page'))
    # Lê dados do formulário (usuário pode editar antes de confirmar)
    fornecedor = (request.form.get('fornecedor') or '').strip()
    valor = (request.form.get('valor') or '').strip()
    vencimento = (request.form.get('vencimento') or '').strip()
    descricao = (request.form.get('descricao') or '').strip() or f"Importado do e-mail: {event.get('assunto','')}"
    tipo_lancamento = (request.form.get('tipo_lancamento') or 'Gasto').strip()
    mes = br_now().strftime('%m/%Y')
    execute("""INSERT INTO pagamentos
        (empresa_id, fornecedor, descricao_servico, valor, status, pagamento_mes, data_vencimento, tipo_lancamento, fluxo_status, acao)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (current_company_id(), fornecedor, descricao, valor, 'Não', mes, vencimento, tipo_lancamento, 'importado_email', 'lançar'))
    mark_monitor_event_popup(event_id, 'acao_tomada')
    flash(f'Pagamento criado com sucesso! Fornecedor: {fornecedor} — Valor: R$ {valor} — Venc.: {vencimento}', 'success')
    return redirect(url_for('outlook_page'))




def outlook_monitor_event_dismiss(event_id):
    mark_monitor_event_popup(event_id, 'dispensado')
    flash('Alerta dispensado. Ele sai do popup, mas continua no histórico.', 'info')
    return redirect(url_for('outlook_page'))




def outlook_monitor_event_prepare(event_id):
    event = query_one('SELECT * FROM email_monitor_events WHERE id=?', (event_id,))
    if not event:
        flash('Evento monitorado não encontrado.', 'warning')
        return redirect(url_for('outlook_page'))
    event = row_to_dict(event)
    flow = (request.form.get('flow') or event.get('sugestao_fluxo') or 'compras').strip()
    mark_monitor_event_popup(event_id, 'acao_tomada')
    if event.get('pagamento_id'):
        flash('Alerta aceito. Prévia aberta para revisão antes do envio.', 'success')
        return redirect(url_for('outlook_page', pagamento_id=event['pagamento_id'], flow=flow, event_id=event_id))
    flash('Evento reconhecido, mas sem vínculo automático com Pagamentos. Revise o histórico do monitoramento.', 'warning')
    return redirect(url_for('outlook_page'))






def outlook_contact_delete(contact_id):
    execute('DELETE FROM email_contacts WHERE id=?', (contact_id,))
    flash('Destinatário/CC excluído.', 'success')
    return redirect(url_for('outlook_page'))




def outlook_contact_edit(contact_id):
    return redirect(url_for('outlook_page', edit_contact_id=contact_id))




def outlook_history_delete(history_id):
    execute('DELETE FROM email_history WHERE id=?', (history_id,))
    flash('Registro removido do histórico.', 'success')
    return redirect(url_for('outlook_page') + '#tab-historico')




def outlook_history_clear_sent():
    execute("DELETE FROM email_history WHERE status LIKE 'ENVIADO%'")
    flash('Histórico de enviados apagado.', 'success')
    return redirect(url_for('outlook_page') + '#tab-historico')




def outlook_history_clear_all():
    execute('DELETE FROM email_history')
    flash('Histórico inteiro apagado.', 'success')
    return redirect(url_for('outlook_page') + '#tab-historico')


def outlook_sender_save():
    rid = request.form.get('id') or None
    nome = (request.form.get('nome') or '').strip()
    email = (request.form.get('email') or '').strip()
    provider = (request.form.get('provider') or 'desktop').strip()
    ativo = 1 if request.form.get('ativo') else 0
    is_default = 1 if request.form.get('is_default') else 0
    observacoes = (request.form.get('observacoes') or '').strip()
    if not nome or not email:
        flash('Preencha nome e e-mail do remetente.', 'warning')
        return redirect(url_for('outlook_page'))
    if is_default:
        execute('UPDATE email_senders SET is_default=0')
    if rid:
        execute('UPDATE email_senders SET nome=?, email=?, provider=?, ativo=?, is_default=?, observacoes=? WHERE id=?', (nome, email, provider, ativo, is_default, observacoes, rid))
    else:
        execute('INSERT INTO email_senders(nome, email, provider, ativo, is_default, observacoes, created_at) VALUES (?,?,?,?,?,?,?)', (nome, email, provider, ativo, is_default, observacoes, now_str()))
    flash('Remetente salvo.', 'success')
    return redirect(url_for('outlook_page'))




def outlook_contact_save():
    rid = request.form.get('id') or None
    area = (request.form.get('area') or '').strip()
    tipo = (request.form.get('tipo') or 'TO').strip().upper()
    nome = (request.form.get('nome') or '').strip()
    emails = normalize_email_block(request.form.get('emails'))
    observacoes = (request.form.get('observacoes') or '').strip()
    if not area or not nome or not emails:
        flash('Área, nome e e-mails são obrigatórios no cadastro de destinatários.', 'warning')
        return redirect(url_for('outlook_page'))
    if rid:
        execute('UPDATE email_contacts SET area=?, tipo=?, nome=?, emails=?, observacoes=? WHERE id=?', (area, tipo, nome, emails, observacoes, rid))
    else:
        execute('INSERT INTO email_contacts(area, tipo, nome, emails, observacoes, created_at) VALUES (?,?,?,?,?,?)', (area, tipo, nome, emails, observacoes, now_str()))
    flash('Destinatário/CC salvo.', 'success')
    return redirect(url_for('outlook_page'))





def outlook_template_save():
    for chave in ['compras_subject', 'compras_body', 'contabil_subject', 'contabil_body']:
        valor = request.form.get(chave, default_template_values()[chave])
        execute('INSERT OR REPLACE INTO email_templates(chave, valor) VALUES (?, ?)', (chave, valor))
    config_set('monitor_email', (request.form.get('monitor_email') or 'notificacao@approvo.com.br').strip())
    config_set('email_provider', (request.form.get('email_provider') or 'desktop').strip())
    config_set('monitor_provider', (request.form.get('monitor_provider') or 'desktop').strip())
    flash('Modelos e preferências salvos.', 'success')
    return redirect(url_for('outlook_page'))




def outlook_test_run():
    sender_id = request.form.get('sender_id', type=int)
    payment_id = request.form.get('payment_id', type=int)
    flow = (request.form.get('flow') or 'compras').strip()
    target_email = normalize_email_block(request.form.get('target_email'))
    do_send = 1 if request.form.get('do_send') else 0

    sender_row = query_one('SELECT * FROM email_senders WHERE id=?', (sender_id,)) if sender_id else None
    if not sender_row:
        sender_row = query_one('SELECT * FROM email_senders WHERE is_default=1 ORDER BY id DESC LIMIT 1') or query_one('SELECT * FROM email_senders WHERE ativo=1 ORDER BY id DESC LIMIT 1')
    payment_row = query_one('SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos WHERE id=?', (payment_id,)) if payment_id else None
    if not sender_row:
        flash('Cadastre um remetente antes de usar a aba de testes.', 'warning')
        return redirect(url_for('outlook_page', pagamento_id=payment_id, flow=flow))
    if not payment_row:
        flash('Escolha um registro de Pagamentos para rodar o teste.', 'warning')
        return redirect(url_for('outlook_page'))

    preview = build_email_payload(flow, payment_row)
    attachment_files = resolve_attachment_paths(preview.get('attachments', []))
    analysis = analyze_attachment_set(flow, attachment_files)
    sender = dict(sender_row)
    provider = (sender.get('provider') or config_get('email_provider', 'desktop') or 'desktop').lower()
    details = [
        f'Provider: {provider.upper()}',
        f'Remetente: {sender.get("email","")}',
        f'Destino de teste: {target_email or "não informado"}',
        f'Fluxo: {flow}',
        f'Anexos resolvidos: {len(attachment_files)}',
    ]
    if analysis.get('boleto_due_date'):
        details.append(f'Vencimento detectado no boleto: {analysis["boleto_due_date"]}')
    if analysis.get('warnings'):
        details.append('Avisos: ' + ' | '.join(analysis['warnings']))
    status = 'DIAGNÓSTICO OK'
    if not provider_readiness(provider):
        status = 'CONFIGURAÇÃO INCOMPLETA'
        details.append('As credenciais do provider selecionado ainda não estão prontas no ambiente.')
    if do_send:
        if not target_email:
            flash('Informe ao menos um e-mail de destino para o envio de teste.', 'warning')
            return redirect(url_for('outlook_page', pagamento_id=payment_id, flow=flow))
        try:
            send_real_email(sender_row, target_email, '', f'[TESTE] {preview["subject"]}', preview['body'], preview.get('attachments', []))
            status = f'TESTE ENVIADO VIA {provider.upper()}'
            flash('E-mail de teste enviado.', 'success')
        except Exception as exc:
            status = f'ERRO TESTE: {str(exc)[:180]}'
            details.append(str(exc))
            flash(str(exc), 'danger')
    else:
        flash('Diagnóstico executado na aba de testes.', 'info')
    execute('INSERT INTO email_test_history(quando, provider, sender_email, target_email, flow, status, detalhes, anexos_json) VALUES (?,?,?,?,?,?,?,?)',
            (now_str(), provider, sender.get('email',''), target_email, flow, status, '\n'.join(details), json.dumps([str(p.relative_to(BASE_DIR)).replace('\\', '/') for p in attachment_files], ensure_ascii=False)))
    return redirect(url_for('outlook_page', pagamento_id=payment_id, flow=flow))





def outlook_monitor_test_run():
    mode = (request.form.get('mode') or 'suite').strip()
    executed = 0
    divergent = 0
    if mode == 'custom':
        sender = (request.form.get('sender_email') or config_get('monitor_email', 'notificacao@approvo.com.br')).strip()
        subject = (request.form.get('subject') or '').strip()
        body = request.form.get('body') or ''
        expected_evento = (request.form.get('expected_evento') or '').strip()
        expected_sc = (request.form.get('expected_sc') or '').strip()
        expected_pedido = (request.form.get('expected_pedido') or '').strip()
        expected_pagamento_id = request.form.get('expected_pagamento_id', type=int)
        if not subject and not body:
            flash('Preencha assunto ou corpo para rodar o teste customizado do monitoramento.', 'warning')
            return redirect(url_for('outlook_page'))
        result = run_monitor_test_case('Teste customizado', sender, subject, body, expected_evento, expected_sc, expected_pedido, expected_pagamento_id)
        executed = 1
        divergent = 1 if result['status'] != 'APROVADO' else 0
        flash(f"Teste customizado concluído: {result['status']}.", 'success' if not divergent else 'warning')
    else:
        for scenario in built_in_monitor_test_scenarios():
            result = run_monitor_test_case(**scenario)
            executed += 1
            divergent += 1 if result['status'] != 'APROVADO' else 0
        flash(f'Bateria do monitoramento executada: {executed} cenário(s), {divergent} divergente(s).', 'success' if divergent == 0 else 'warning')
    return redirect(url_for('outlook_page') + '#monitor-tests')




def outlook_monitor_run():
    mode = (request.form.get('mode') or 'imap').strip()
    processed = 0
    duplicates = 0
    applied = 0
    try:
        if mode == 'manual':
            sender = (request.form.get('sample_from') or config_get('monitor_email', 'notificacao@approvo.com.br')).strip()
            subject = (request.form.get('sample_subject') or '').strip()
            body = request.form.get('sample_body') or ''
            if not subject and not body:
                flash('Preencha assunto ou corpo para simular o parsing do monitoramento.', 'warning')
                return redirect(url_for('outlook_page'))
            result = process_monitor_payload(f'manual-{datetime.now().timestamp()}', sender, subject, body)
            processed = 1
            applied = 1 if result.get('applied') else 0
            duplicates = 1 if result.get('duplicate') else 0
            flash('Simulação de monitoramento processada.', 'success')
        else:
            messages = fetch_monitor_emails(limit=request.form.get('limit', type=int) or 10)
            if not messages:
                flash('Nenhum e-mail novo do endereço monitorado foi encontrado agora.', 'info')
                return redirect(url_for('outlook_page'))
            for msg in messages:
                result = process_monitor_payload(msg['message_id'], msg['sender_email'], msg['subject'], msg['body'])
                processed += 1
                duplicates += 1 if result.get('duplicate') else 0
                applied += 1 if result.get('applied') else 0
            flash(f'Monitoramento executado: {processed} mensagem(ns) lidas, {applied} atualização(ões) aplicadas e {duplicates} duplicada(s).', 'success')
    except Exception as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('outlook_page'))




def outlook_send_real():
    payment_id = request.form.get('payment_id', type=int)
    flow = (request.form.get('flow') or 'compras').strip()
    sender_id = request.form.get('sender_id', type=int)
    to_raw = normalize_email_block(request.form.get('to'))
    cc_raw = normalize_email_block(request.form.get('cc'))
    subject = (request.form.get('subject') or '').strip()
    body = request.form.get('body') or ''
    attachment_items = request.form.getlist('attachments')

    payment_row = query_one('SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos WHERE id=?', (payment_id,)) if payment_id else None
    if not payment_row:
        flash('Selecione um pagamento válido para preparar o envio.', 'warning')
        return redirect(url_for('outlook_page'))
    sender_row = query_one('SELECT * FROM email_senders WHERE id=?', (sender_id,)) if sender_id else None
    if not sender_row:
        sender_row = query_one('SELECT * FROM email_senders WHERE is_default=1 ORDER BY id DESC LIMIT 1') or query_one('SELECT * FROM email_senders WHERE ativo=1 ORDER BY id DESC LIMIT 1')
    attachment_files = resolve_attachment_paths(attachment_items)
    attachment_analysis = analyze_attachment_set(flow, attachment_files)
    can_send, block_reason = attachment_analysis['can_send'], attachment_analysis['block_reason']
    payment = row_to_dict(payment_row)
    history_payload = (now_str(), 'Compras' if flow == 'compras' else 'Contábil', payment.get('numero_documento') or payment.get('sc_pedido') or str(payment.get('id')), to_raw, subject, '', len(attachment_files), flow, dict(sender_row)['email'] if sender_row else '', cc_raw, payment.get('numero_documento',''), payment.get('sc_pedido',''), json.dumps([str(p.relative_to(BASE_DIR)).replace('\\', '/') for p in attachment_files], ensure_ascii=False))
    if not can_send:
        execute('''INSERT INTO email_history(quando, tipo, numero, destinatario, assunto, status, anexos, fluxo, remetente, cc, numero_sc, numero_pedido, anexos_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', history_payload[:5] + ('BLOQUEADO',) + history_payload[6:])
        flash(block_reason, 'danger')
        return redirect(url_for('outlook_page', pagamento_id=payment_id, flow=flow))
    try:
        result = send_real_email(sender_row, to_raw, cc_raw, subject, body, attachment_items)
        execute('''INSERT INTO email_history(quando, tipo, numero, destinatario, assunto, status, anexos, fluxo, remetente, cc, numero_sc, numero_pedido, anexos_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (now_str(), 'Compras' if flow == 'compras' else 'Contábil', payment.get('numero_documento') or payment.get('sc_pedido') or str(payment.get('id')), to_raw, subject, f'ENVIADO VIA {result["provider"].upper()}', len(result['attachments']), flow, result['sender_email'], cc_raw, payment.get('numero_documento',''), payment.get('sc_pedido',''), json.dumps([str(p.relative_to(BASE_DIR)).replace('\\', '/') for p in result['attachments']], ensure_ascii=False)))
        flash(f'E-mail enviado com sucesso via {result["provider"].upper()}.', 'success')
    except Exception as exc:
        execute('''INSERT INTO email_history(quando, tipo, numero, destinatario, assunto, status, anexos, fluxo, remetente, cc, numero_sc, numero_pedido, anexos_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (now_str(), 'Compras' if flow == 'compras' else 'Contábil', payment.get('numero_documento') or payment.get('sc_pedido') or str(payment.get('id')), to_raw, subject, f'ERRO: {str(exc)[:180]}', len(attachment_files), flow, dict(sender_row)['email'] if sender_row else '', cc_raw, payment.get('numero_documento',''), payment.get('sc_pedido',''), json.dumps([str(p.relative_to(BASE_DIR)).replace('\\', '/') for p in attachment_files], ensure_ascii=False)))
        flash(str(exc), 'danger')
    return redirect(url_for('outlook_page', pagamento_id=payment_id, flow=flow))





@require_permission('view_outlook')
def outlook_page():
    senders, contacts, templates = load_email_center()
    cfg = {r['chave']: json.loads(r['valor']) for r in query_all('SELECT chave, valor FROM email_config ORDER BY chave')}
    edit_contact_id = request.args.get('edit_contact_id', type=int)
    edit_contact = None
    if edit_contact_id:
        edit_contact = row_to_dict(query_one('SELECT id, nome, email, area, ativo FROM email_contacts WHERE id=?', (edit_contact_id,)))
    history_status = (request.args.get('history_status') or '').strip()
    history_flow = (request.args.get('history_flow') or '').strip()
    history_search = (request.args.get('history_search') or '').strip()
    history_sql = 'SELECT ' + select_existing_columns('email_history', [
        'id', 'quando', 'remetente', 'destinatario', 'assunto', 'status',
        'fluxo', 'numero_sc', 'numero_pedido', 'pagamento_id', 'anexos', 'numero', 'cc', 'tipo'
    ]) + ' FROM email_history WHERE 1=1'
    history_params = []
    if history_status:
        history_sql += ' AND status LIKE ?'
        history_params.append(f'%{history_status}%')
    if history_flow:
        history_sql += ' AND fluxo=?'
        history_params.append(history_flow)
    if history_search:
        history_sql += ' AND (assunto LIKE ? OR destinatario LIKE ? OR remetente LIKE ? OR numero_sc LIKE ? OR numero_pedido LIKE ?)'
        token = f'%{history_search}%'
        history_params.extend([token] * 5)
    history_sql += ' ORDER BY id DESC LIMIT 150'
    history = [row_to_dict(r) for r in query_all(history_sql, tuple(history_params))]
    test_history = [row_to_dict(r) for r in query_all('SELECT ' + select_existing_columns('email_test_history', [
        'id', 'quando', 'fluxo', 'destinatario', 'assunto', 'status', 'detalhes',
        'provider', 'sender_email', 'target_email', 'flow', 'anexos_json'
    ]) + ' FROM email_test_history ORDER BY id DESC LIMIT 30')]
    monitor_test_runs = [row_to_dict(r) for r in query_all('SELECT id, quando, scenario_name, expected_evento, detected_evento, expected_sc, detected_sc, expected_pedido, detected_pedido, expected_pagamento_id, detected_pagamento_id, status, applied, duplicate, detalhes FROM email_monitor_test_runs ORDER BY id DESC LIMIT 60')]
    monitor_event_filter = (request.args.get('monitor_event') or '').strip()
    monitor_popup_filter = (request.args.get('monitor_popup') or '').strip()
    monitor_status_filter = (request.args.get('monitor_status') or '').strip()
    monitor_link_filter = (request.args.get('monitor_link') or '').strip()
    monitor_flow_filter = (request.args.get('monitor_flow') or '').strip()
    monitor_from = (request.args.get('monitor_from') or '').strip()
    monitor_to = (request.args.get('monitor_to') or '').strip()
    monitor_search = (request.args.get('monitor_search') or '').strip()
    monitor_sql = 'SELECT ' + select_existing_columns('email_monitor_events', [
        'id', 'quando', 'source_message_id', 'remetente', 'assunto',
        'numero_sc', 'numero_pedido', 'evento', 'status_processamento',
        'sugestao_fluxo', 'pagamento_id', 'popup_status', 'detalhes', 'corpo_resumo',
        'detalhes_json'
    ]) + ' FROM email_monitor_events WHERE 1=1'
    monitor_params = []
    if monitor_event_filter:
        monitor_sql += ' AND evento=?'
        monitor_params.append(monitor_event_filter)
    if monitor_popup_filter:
        monitor_sql += " AND COALESCE(popup_status,'novo')=?"
        monitor_params.append(monitor_popup_filter)
    if monitor_status_filter:
        monitor_sql += ' AND status_processamento LIKE ?'
        monitor_params.append(f'%{monitor_status_filter}%')
    if monitor_link_filter == 'vinculado':
        monitor_sql += ' AND pagamento_id IS NOT NULL'
    elif monitor_link_filter == 'nao_vinculado':
        monitor_sql += ' AND pagamento_id IS NULL'
    if monitor_flow_filter:
        monitor_sql += ' AND sugestao_fluxo=?'
        monitor_params.append(monitor_flow_filter)
    if monitor_from:
        monitor_sql += ' AND substr(quando,1,10) >= ?'
        monitor_params.append(monitor_from)
    if monitor_to:
        monitor_sql += ' AND substr(quando,1,10) <= ?'
        monitor_params.append(monitor_to)
    if monitor_search:
        monitor_sql += ' AND (assunto LIKE ? OR remetente LIKE ? OR numero_sc LIKE ? OR numero_pedido LIKE ? OR corpo_resumo LIKE ? OR status_processamento LIKE ?)'
        token = f'%{monitor_search}%'
        monitor_params.extend([token] * 6)
    monitor_sql += ' ORDER BY id DESC LIMIT 250'
    monitor_events = [row_to_dict(r) for r in query_all(monitor_sql, tuple(monitor_params))]
    pending_alerts = list_pending_monitor_alerts(limit=6)
    rows = [row_to_dict(r) for r in query_all('SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos ORDER BY id DESC LIMIT 200')]
    preview_id = request.args.get('pagamento_id', type=int)
    flow = request.args.get('flow', 'compras')
    preview = None
    default_sender = get_default_sender()
    if preview_id:
        payment_row = query_one('SELECT id, fornecedor, descricao_servico, valor, status, nf_proposta, acao, pagamento_mes, numero_documento, sc_pedido, aprovado, tipo_documento, fluxo_status, anexos_orcamento, anexos_nf, anexos_boleto FROM pagamentos WHERE id=?', (preview_id,))
        if payment_row:
            preview = build_email_payload(flow, payment_row)
            resolved_files = resolve_attachment_paths(preview.get('attachments', []))
            preview['resolved_attachments'] = [str(p.relative_to(BASE_DIR)).replace('\\', '/') for p in resolved_files]
            preview['can_send'], preview['send_block_reason'] = can_send_payload(flow, resolved_files)
    monitor_counts = {
        'total': query_one('SELECT COUNT(*) AS n FROM email_monitor_events')['n'],
        'aprovadas': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE evento='sc_aprovada'")['n'],
        'fechadas': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE evento='sc_fechada_100'")['n'],
        'dispensados': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE COALESCE(popup_status,'novo')='dispensado'")['n'],
        'acao_tomada': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE COALESCE(popup_status,'novo')='acao_tomada'")['n'],
        'ignorados': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE evento='ignorado'")['n'],
        'vinculados': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE pagamento_id IS NOT NULL")['n'],
        'nao_vinculados': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE pagamento_id IS NULL")['n'],
        'compras': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE sugestao_fluxo='compras'")['n'],
        'ultimas_24h': query_one("SELECT COUNT(*) AS n FROM email_monitor_events WHERE quando >= " + ("(NOW() - INTERVAL '1 day')::text" if USE_POSTGRES else "datetime('now','-1 day','localtime')"))['n'],
        'filtrados': len(monitor_events),
    }
    monitor_test_counts = {
        'total': query_one('SELECT COUNT(*) AS n FROM email_monitor_test_runs')['n'],
        'aprovado': query_one("SELECT COUNT(*) AS n FROM email_monitor_test_runs WHERE status='APROVADO'")['n'],
        'divergente': query_one("SELECT COUNT(*) AS n FROM email_monitor_test_runs WHERE status='DIVERGENTE'")['n'],
    }
    provider_status = {
        'graph_ready': graph_credentials_ready(),
        'smtp_ready': smtp_credentials_ready(),
        'default_sender': default_sender,
        **monitor_status_snapshot(),
        'worker': get_monitor_worker_state(),
    }
    monitor_audit = {
        'ultimo_evento': monitor_events[0]['quando'] if monitor_events else '',
        'ultimo_vinculo': next((e['quando'] for e in monitor_events if e.get('pagamento_id')), ''),
        'ultimo_ignorado': next((e['quando'] for e in monitor_events if e.get('evento') == 'ignorado'), ''),
        'pendentes_popup': len(pending_alerts),
    }
    return render_template('outlook.html', cfg=cfg, history=history, history_filters={'status': history_status, 'flow': history_flow, 'search': history_search}, test_history=test_history, monitor_events=monitor_events, monitor_filters={'event': monitor_event_filter, 'popup': monitor_popup_filter, 'status': monitor_status_filter, 'link': monitor_link_filter, 'flow': monitor_flow_filter, 'from': monitor_from, 'to': monitor_to, 'search': monitor_search}, monitor_counts=monitor_counts, monitor_audit=monitor_audit, monitor_test_runs=monitor_test_runs, monitor_test_counts=monitor_test_counts, pending_alerts=pending_alerts, senders=senders, contacts=contacts, templates=templates, pagamentos=rows, preview=preview, preview_id=preview_id, preview_flow=flow, default_sender=default_sender, provider_status=provider_status, monitor_scenarios=built_in_monitor_test_scenarios(), edit_contact=edit_contact)






def register_routes(app):
    rules = [
        ('/outlook/monitor-events/export', 'outlook_monitor_events_export', outlook_monitor_events_export, ['GET']),
        ('/outlook/monitor-event/<int:event_id>/confirmar-boleto', 'outlook_monitor_event_confirmar_boleto', outlook_monitor_event_confirmar_boleto, ['POST']),
        ('/outlook/monitor-event/<int:event_id>/dismiss', 'outlook_monitor_event_dismiss', outlook_monitor_event_dismiss, ['POST']),
        ('/outlook/monitor-event/<int:event_id>/prepare', 'outlook_monitor_event_prepare', outlook_monitor_event_prepare, ['POST']),
        ('/outlook/contacts/delete/<int:contact_id>', 'outlook_contact_delete', outlook_contact_delete, ['GET']),
        ('/outlook/contacts/edit/<int:contact_id>', 'outlook_contact_edit', outlook_contact_edit, ['GET']),
        ('/outlook/history/<int:history_id>/delete', 'outlook_history_delete', outlook_history_delete, ['POST']),
        ('/outlook/history/clear-sent', 'outlook_history_clear_sent', outlook_history_clear_sent, ['POST']),
        ('/outlook/history/clear-all', 'outlook_history_clear_all', outlook_history_clear_all, ['POST']),
        ('/outlook/senders/save', 'outlook_sender_save', outlook_sender_save, ['POST']),
        ('/outlook/contacts/save', 'outlook_contact_save', outlook_contact_save, ['POST']),
        ('/outlook/templates/save', 'outlook_template_save', outlook_template_save, ['POST']),
        ('/outlook/test-run', 'outlook_test_run', outlook_test_run, ['POST']),
        ('/outlook/monitor-test-run', 'outlook_monitor_test_run', outlook_monitor_test_run, ['POST']),
        ('/outlook/monitor-run', 'outlook_monitor_run', outlook_monitor_run, ['POST']),
        ('/outlook/send-real', 'outlook_send_real', outlook_send_real, ['POST']),
        ('/outlook', 'outlook_page', outlook_page, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
