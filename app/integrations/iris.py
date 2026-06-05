"""Iris — assistente conversacional (Claude + OpenAI)."""
import json
import re
from datetime import datetime
from urllib import parse as urllib_parse

from flask import current_app, jsonify, request, session, url_for

from app.exports.iris_ai import _iris_call_ai, _iris_call_claude
from app.exports.iris_data import (
    _iris_collect_context,
    _iris_month_label,
    _iris_normalize,
    _iris_official_finance,
    _iris_parse_br_float,
    _iris_payment_status,
    _iris_rows,
)
from app.exports.iris_reports import (
    _iris_make_ai_pdf,
    _iris_make_monthly_pdf,
    _iris_make_payments_excel,
)
from app.exports.jobs import _create_iris_job, _start_iris_job_thread
from app.os.services import os_is_overdue
from app.shared.formatters import br_money


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


IRIS_BOMBA_TERMS = ['bomba', 'bombas', 'bombeamento', 'submersa', 'submersas', 'areador', 'aerador', 'elevatoria', 'elevatorio', 'boia', 'boia', 'painel de bomba']


_IRIS_AI_SYSTEM_PLAN = """Você é a Iris, consultora operacional inteligente integrada ao sistema IRIS de gestão.
Seu papel é ser como uma gestora experiente: analise, recomende, alerte e responda perguntas com base nos dados da empresa.

Interprete pedidos em português natural e responda SOMENTE JSON válido, sem markdown, sem explicações.

Intents disponíveis:
- monthly_report: relatório mensal. Campos: month_ref MM/AAAA, format pdf|excel
- annual_report: relatório anual com tendências 12 meses. Campos: year AAAA, format pdf
- system_report: relatório por sistema/equipamento, histórico de falhas e custos. Campos: sistema, month_ref, format pdf
- executive_report: resumo executivo para gestão. Campos: month_ref ou year, format pdf
- payments_report: relatório de pagamentos. Campos: month_ref, format pdf|excel
- payments_total: total de pagamentos aprovados. Campos: month_ref
- payments_open: pagamentos em aberto. Campos: month_ref
- payment_lookup: verificar pedido/NF/documento. Campos: query
- top_os_system: sistema com mais O.S. Campos: month_ref
- os_late: O.S. atrasadas
- create_os_draft: nova O.S. em rascunho. Campos: data_ddmmyyyy, sistema, unidade, responsavel, descricao
- open_os: abrir O.S. por número. Campo: os_id
- costs_summary: resumo de custos. Campos: month_ref, mode resumo|consultoria|analitico
- cost_subject: custo de tema específico (bombas, areador etc). Campos: month_ref, subject, mode
- search: busca geral. Campos: query
- free_answer: resposta livre para perguntas gerais, análises e recomendações. Campos: message (a pergunta original)

Use free_answer quando o usuário fizer perguntas abertas como:
- "qual o maior problema?", "o que você recomenda?", "como posso melhorar X?"
- perguntas sobre gestão, manutenção, boas práticas, análises comparativas
- qualquer pergunta que não se encaixe nas outras intents

Nunca invente dados específicos. Para free_answer, responda com base no contexto geral da empresa de saneamento/manutenção.
Escolha a intent mais provável."""





def _iris_month_ref(text):
    now = datetime.now()
    t = _iris_normalize(text)
    meses = {
        'janeiro':'01','jan':'01','fevereiro':'02','fev':'02','marco':'03','mar':'03',
        'abril':'04','abr':'04','maio':'05','mai':'05','junho':'06','jun':'06',
        'julho':'07','jul':'07','agosto':'08','ago':'08','setembro':'09','set':'09',
        'outubro':'10','out':'10','novembro':'11','nov':'11','dezembro':'12','dez':'12'
    }
    m = re.search(r'(\d{1,2})[\/\-](\d{4})', t)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)}"
    for nome, num in meses.items():
        if nome in t:
            yr = re.search(r'(20\d{2})', t)
            return f"{num}/{yr.group(1) if yr else now.year}"
    if 'mes passado' in t:
        y, mth = now.year, now.month-1
        if mth == 0:
            y, mth = y-1, 12
        return f"{mth:02d}/{y}"
    if 'mes' in t or 'mensal' in t or 'este mes' in t or 'desse mes' in t:
        return now.strftime('%m/%Y')
    return ''



def _iris_mode(message):
    t = _iris_normalize(message)
    if any(w in t for w in ['analitico', 'analise completa', 'detalha', 'detalhado', 'detalhamento', 'completo']):
        return 'analitico'
    if any(w in t for w in ['resumo', 'curto', 'rapido', 'direto', 'objetivo']):
        return 'resumo'
    return 'consultoria'



def _iris_reply(title, direct='', bullets=None, note='', next_step=''):
    parts = []
    if title:
        parts.append(str(title).strip().rstrip('.'))
    if direct:
        parts.append(str(direct).strip())
    if bullets:
        clean = [str(b).strip() for b in bullets if str(b or '').strip()]
        if clean:
            parts.append('\n'.join(f"• {b}" for b in clean))
    if note:
        parts.append(str(note).strip())
    if next_step:
        parts.append(str(next_step).strip())
    return '\n\n'.join(parts).strip()



def _iris_payment_hay(row):
    return _iris_normalize(' '.join(str(row.get(k) or '') for k in ['id','sistema','equipamento','fornecedor','descricao_servico','status','nf_proposta','sc_pedido','numero_documento','tipo_documento','fluxo_status','categoria','observacao']))

IRIS_BOMBA_TERMS = ['bomba', 'bombas', 'bombeamento', 'submersa', 'submersas', 'areador', 'aerador', 'elevatoria', 'elevatorio', 'boia', 'boia', 'painel de bomba']



def _iris_detect_subject_terms(message):
    t = _iris_normalize(message)
    if any(x in t for x in ['bomba', 'bombas', 'areador', 'aerador', 'elevatoria', 'elevatorio']):
        return IRIS_BOMBA_TERMS, 'bombas'
    m = re.search(r'(?:com|de|sobre|referente a|relacionado a)\s+([a-z0-9\s\-_/]+)', t)
    if m:
        val = m.group(1).strip()
        val = re.split(r'\b(?:esse mes|este mes|mes|em|no periodo|quanto|total|relatorio|pdf|excel)\b', val)[0].strip()
        if len(val) > 2:
            return [val], val
    return [], ''



def _iris_filter_payments_by_terms(rows, terms):
    if not terms:
        return rows
    terms_n = [_iris_normalize(x) for x in terms if x]
    out = []
    for r in rows:
        hay = _iris_payment_hay(r)
        if any(term in hay for term in terms_n):
            out.append(r)
    return out



def _iris_group_sum(rows, field):
    d = {}
    for r in rows:
        key = (r.get(field) or 'Não informado').strip() or 'Não informado'
        d[key] = d.get(key, 0.0) + _iris_parse_br_float(r.get('valor'))
    return sorted(d.items(), key=lambda x: x[1], reverse=True)



def _iris_group_count(rows, field):
    d = {}
    for r in rows:
        key = (r.get(field) or 'Não informado').strip() or 'Não informado'
        d[key] = d.get(key, 0) + 1
    return sorted(d.items(), key=lambda x: x[1], reverse=True)



def _iris_cost_subject_answer(message, month_ref, mode='consultoria'):
    ctx = _iris_collect_context(month_ref)
    terms, label = _iris_detect_subject_terms(message)
    rows = _iris_filter_payments_by_terms(ctx['pagamentos'], terms)
    total = sum(_iris_parse_br_float(r.get('valor')) for r in rows)
    if not rows:
        return {'reply': _iris_reply(f"Não localizei gastos de {label or 'esse tema'} em {_iris_month_label(month_ref)}", "Posso procurar por outro termo, fornecedor, sistema ou descrição de serviço.")}
    pagos = sum(_iris_parse_br_float(r.get('valor')) for r in rows if _iris_payment_status(r) == 'Pago')
    aberto = total - pagos
    by_system = _iris_group_sum(rows, 'sistema')
    top_system = by_system[0] if by_system else ('Não informado', 0)
    by_desc = _iris_group_count(rows, 'descricao_servico')[:3]
    title = f"Gasto com {label or 'o tema solicitado'} — {_iris_month_label(month_ref)}"
    direct = f"Total apurado: {br_money(total)}."
    bullets = [f"Pago: {br_money(pagos)}; em aberto: {br_money(aberto)}.", f"Maior impacto por sistema: {top_system[0]} ({br_money(top_system[1])})."]
    if by_desc:
        bullets.append("Principais ocorrências: " + '; '.join(f"{(desc or 'Sem descrição')[:45]} ({qtd})" for desc, qtd in by_desc))
    note = "Leitura técnica: considerei lançamentos cuja descrição, fornecedor, sistema ou documento indicam relação com o tema pesquisado."
    if mode == 'resumo':
        return {'reply': _iris_reply(title, direct, [bullets[1]], next_step='Posso detalhar os lançamentos ou gerar um relatório.')}
    if mode == 'analitico':
        detail = []
        for r in sorted(rows, key=lambda x: _iris_parse_br_float(x.get('valor')), reverse=True)[:8]:
            detail.append(f"ID {r.get('id')} — {r.get('fornecedor') or r.get('sistema') or 'Sem fornecedor'} — {br_money(_iris_parse_br_float(r.get('valor')))} — {(r.get('descricao_servico') or '')[:60]}")
        return {'reply': _iris_reply(title, direct, bullets + detail, note=note, next_step='Posso transformar esse detalhamento em PDF ou Excel.')}
    return {'reply': _iris_reply(title, direct, bullets, note=note, next_step='Quer que eu abra o detalhamento ou gere um relatório?')}



def _iris_safe_json(text):
    try:
        if not text:
            return None
        text = text.strip()
        m = re.search(r'\{.*\}', text, re.S)
        if m:
            text = m.group(0)
        return json.loads(text)
    except Exception:
        return None



def _iris_fallback_plan(message):
    t = _iris_normalize(message)
    month_ref = _iris_month_ref(message)

    # Combustível
    if any(x in t for x in ['combustivel', 'abastecimento', 'gasolina', 'diesel', 'etanol']) and any(w in t for w in ['quanto', 'gasto', 'gastamos', 'gastei', 'custo', 'custou', 'despesa', 'valor']):
        return {'intent':'fuel_costs', 'month_ref': month_ref, 'mode': _iris_mode(message)}

    # Relatório anual
    if any(w in t for w in ['anual', 'ano', 'annual', '12 meses', 'doze meses']):
        if any(w in t for w in ['relatorio', 'pdf', 'gerar', 'gere', 'gera', 'fazer', 'faz', 'quero', 'me da', 'me manda']):
            year_match = re.search(r'(20\d{2})', t)
            year = year_match.group(1) if year_match else str(datetime.now().year)
            return {'intent': 'annual_report', 'year': year, 'format': 'pdf'}

    # Relatório executivo
    if any(w in t for w in ['executivo', 'gestao', 'gestão', 'diretoria', 'board']):
        if any(w in t for w in ['relatorio', 'pdf', 'resumo', 'gerar', 'gere', 'fazer']):
            return {'intent': 'executive_report', 'month_ref': month_ref or datetime.now().strftime('%m/%Y'), 'format': 'pdf'}

    # Relatório por sistema
    if 'sistema' in t and any(w in t for w in ['relatorio', 'historico', 'histórico', 'falhas', 'manutencao']):
        sistema_match = re.search(r'sistema\s+([a-z\s]+?)(?:\s+de|\s+do|\s+no|\s+em|$)', t)
        sistema = sistema_match.group(1).strip().title() if sistema_match else ''
        return {'intent': 'system_report', 'sistema': sistema, 'month_ref': month_ref, 'format': 'pdf'}

    # Relatório mensal
    if ('relatorio' in t or 'pdf' in t) and any(w in t for w in ['gerar', 'gere', 'gera', 'relatorio', 'fazer', 'faz', 'quero', 'me da', 'me manda']):
        return {'intent':'monthly_report', 'month_ref': month_ref or datetime.now().strftime('%m/%Y'), 'format':'pdf'}
    if 'excel' in t and 'pagamento' in t:
        return {'intent':'payments_report', 'month_ref': month_ref, 'format':'excel'}
    if 'pdf' in t and 'pagamento' in t:
        return {'intent':'payments_report', 'month_ref': month_ref, 'format':'pdf'}
    if 'pagamento' in t and ('aberto' in t or 'pendente' in t or 'nao pago' in t):
        return {'intent':'payments_open', 'month_ref': month_ref}
    if 'pagamento' in t and any(w in t for w in ['quanto', 'total', 'valor', 'soma', 'somou', 'pagamos', 'pago']):
        return {'intent':'payments_total', 'month_ref': month_ref}
    if 'pedido' in t or 'nf' in t or 'nota' in t or 'documento' in t:
        nums = re.findall(r'\d+', t)
        return {'intent':'payment_lookup', 'query': nums[-1] if nums else message}
    if ('sistema' in t and ('mais' in t or 'maior' in t) and ('os' in t or 'o.s' in t or 'ordem' in t or 'chamado' in t)):
        return {'intent':'top_os_system', 'month_ref': month_ref}
    if ('atrasad' in t) and ('os' in t or 'o.s' in t or 'ordem' in t):
        return {'intent':'os_late'}
    # Perguntas financeiras têm prioridade sobre O.S.
    # Ex.: "quanto gastamos em abril" NÃO pode abrir modal de O.S.
    if any(w in t for w in ['custo','custos','gasto','gastamos','gastei','despesa','despesas','valor']):
        terms, label = _iris_detect_subject_terms(message)
        if terms:
            return {'intent':'cost_subject', 'month_ref': month_ref, 'subject': label, 'mode': _iris_mode(message)}
        return {'intent':'costs_summary', 'month_ref': month_ref, 'mode': _iris_mode(message)}

    # Abrir/criar O.S. somente quando o usuário pedir O.S./ordem de serviço explicitamente.
    # Evita falso positivo: "abril" contém "abr" e "gastamos" contém "os".
    quer_criar_os = re.search(r'\b(abrir|abra|abre|criar|cria|crie|nova|novo)\b', t)
    citou_os = re.search(r'\b(o\.?s\.?|ordem|servico|serviço)\b', t)
    if quer_criar_os and citou_os:
        return {'intent':'create_os_draft', 'raw':message}
    return {'intent':'search', 'query':message, 'month_ref': month_ref}



def _iris_context_summary():
    """Gera resumo do contexto atual da empresa para a Iris responder perguntas livres."""
    try:
        empresa_id = current_company_id()
        from datetime import datetime as _dt
        mes_atual = _dt.now().strftime('%m/%Y')

        os_total = (query_one('SELECT COUNT(*) AS c FROM os_ordens WHERE empresa_id=?', (empresa_id,)) or {}).get('c', 0)
        os_aberta = (query_one("SELECT COUNT(*) AS c FROM os_ordens WHERE empresa_id=? AND status NOT IN ('Finalizada','Cancelada')", (empresa_id,)) or {}).get('c', 0)
        os_atraso = (query_one("SELECT COUNT(*) AS c FROM os_ordens WHERE empresa_id=? AND status='Atrasada'", (empresa_id,)) or {}).get('c', 0)
        bombas_estoque = (query_one("SELECT COUNT(*) AS c FROM bombas WHERE empresa_id=? AND em_estoque='Sim'", (empresa_id,)) or {}).get('c', 0)
        bombas_conserto = (query_one("SELECT COUNT(*) AS c FROM bombas WHERE empresa_id=? AND em_conserto='Sim'", (empresa_id,)) or {}).get('c', 0)

        return f"""Empresa ID: {empresa_id} | Mês: {mes_atual}
O.S.: {os_total} total, {os_aberta} em aberto, {os_atraso} em atraso
Bombas: {bombas_estoque} em estoque, {bombas_conserto} em conserto"""
    except Exception as exc:
        return f'Contexto indisponível: {exc}'




def _iris_ai_plan(message):
    """Interpreta a mensagem usando IA (Claude ou OpenAI) para identificar a intent."""
    system_prompt = _IRIS_AI_SYSTEM_PLAN + "\n\nResponda APENAS com JSON, sem markdown."
    full_prompt = f"{system_prompt}\n\nMensagem do usuário: {message}"

    text, prov = _iris_call_ai(full_prompt, max_tokens=400, json_mode=True)
    if text:
        return _iris_safe_json(text)
    return None



def _iris_extract_create_params(raw, plan=None):
    plan = plan or {}
    t = _iris_normalize(raw)
    data = plan.get('data_ddmmyyyy') or ''
    if not data:
        m = re.search(r'(\d{1,2})\s+de\s+([a-zç]+)(?:\s+de\s+(\d{4}))?', t)
        meses = {'janeiro':1,'fevereiro':2,'marco':3,'abril':4,'maio':5,'junho':6,'julho':7,'agosto':8,'setembro':9,'outubro':10,'novembro':11,'dezembro':12}
        if m and m.group(2) in meses:
            y = int(m.group(3) or datetime.now().year)
            data = f"{int(m.group(1)):02d}/{meses[m.group(2)]:02d}/{y}"
        elif 'hoje' in t:
            data = datetime.now().strftime('%d/%m/%Y')
    sistema = plan.get('sistema') or ''
    unidade = plan.get('unidade') or plan.get('equipamento') or ''
    responsavel = plan.get('responsavel') or ''
    descricao = plan.get('descricao') or ''
    # Regex fallbacks
    if not sistema:
        m = re.search(r'sistema\s+(.+?)(?:\s+unidade|\s+equipamento|\s+responsavel|\s+para|\s+no dia|\s+dia|$)', raw, re.I)
        if m: sistema = m.group(1).strip()
    if not unidade:
        m = re.search(r'(?:unidade|equipamento|ativo)\s+(.+?)(?:\s+responsavel|\s+para|\s+no dia|\s+dia|$)', raw, re.I)
        if m: unidade = m.group(1).strip()
    if not responsavel:
        m = re.search(r'respons[aá]vel\s+(.+?)(?:\s+descri[cç][aã]o|\s+para|\s+no dia|\s+dia|$)', raw, re.I)
        if m: responsavel = m.group(1).strip()
    if not descricao:
        m = re.search(r'descri[cç][aã]o\s+(.+)$', raw, re.I)
        if m: descricao = m.group(1).strip()
    return {'data':data, 'sistema':sistema, 'unidade':unidade, 'responsavel':responsavel, 'descricao':descricao}



def _iris_search_payments(query):
    q = _iris_normalize(query)
    rows = _iris_rows('pagamentos', limit=1000)
    nums = re.findall(r'\d+', q)
    out = []
    for r in rows:
        hay = ' '.join(str(r.get(k) or '') for k in ['id','sistema','equipamento','fornecedor','descricao_servico','status','nf_proposta','sc_pedido','numero_documento','tipo_documento','fluxo_status']).lower()
        hn = _iris_normalize(hay)
        if (q and q in hn) or any(n and n in hn for n in nums):
            out.append(r)
    return out[:20]



def _iris_answer(plan, message):
    intent = (plan or {}).get('intent') or 'search'
    month_ref = (plan or {}).get('month_ref') or _iris_month_ref(message)
    fmt = ((plan or {}).get('format') or '').lower()
    mode = (plan or {}).get('mode') or _iris_mode(message)

    if intent == 'monthly_report':
        ref = month_ref or datetime.now().strftime('%m/%Y')
        try:
            jid = _create_iris_job('mensal', ref); _start_iris_job_thread(jid)
            wu = url_for('iris_relatorio_wait', job_id=jid)
            return {'reply': _iris_reply(f"Relatório mensal — {_iris_month_label(ref)}",
                "A IA está escrevendo o relatório em 3 chamadas paralelas. Leva cerca de 30 segundos.",
                next_step="Acompanhe pelo botão abaixo."),
                'download_url': wu, 'download_label': '📊 Acompanhar geração do PDF'}
        except Exception:
            path = _iris_make_monthly_pdf(ref)
            return {'reply': _iris_reply(f"Relatório mensal — {_iris_month_label(ref)}", "Relatório gerado."), 'download_url': url_for('static', filename='exports/' + path.name), 'download_label': 'Baixar PDF'}

    if intent == 'annual_report':
        year = str((plan or {}).get('year') or datetime.now().year)
        try:
            jid = _create_iris_job('anual', year); _start_iris_job_thread(jid)
            wu = url_for('iris_relatorio_wait', job_id=jid)
            return {'reply': _iris_reply(f"Relatório anual — {year}",
                "A IA está analisando os 12 meses em paralelo e escrevendo o relatório estratégico.",
                next_step="Acompanhe pelo botão abaixo. Leva ~45 segundos."),
                'download_url': wu, 'download_label': '📊 Acompanhar geração do PDF'}
        except Exception as exc:
            return {'reply': _iris_reply("Erro ao iniciar relatório anual", str(exc)[:200])}

    if intent == 'system_report':
        sistema = str((plan or {}).get('sistema') or '')
        ref_param = f'sistema|{sistema}|{month_ref}' if sistema else month_ref
        try:
            jid = _create_iris_job('sistema', ref_param); _start_iris_job_thread(jid)
            wu = url_for('iris_relatorio_wait', job_id=jid)
            label = f"{sistema} — {_iris_month_label(month_ref)}" if sistema else _iris_month_label(month_ref)
            return {'reply': _iris_reply(f"Relatório por sistema — {label}",
                "A IA está analisando falhas, componentes e reincidências em paralelo.",
                next_step="Acompanhe pelo botão abaixo."),
                'download_url': wu, 'download_label': '📊 Acompanhar geração do PDF'}
        except Exception as exc:
            return {'reply': _iris_reply("Erro ao iniciar relatório por sistema", str(exc)[:200])}

    if intent == 'executive_report':
        ref = month_ref or datetime.now().strftime('%m/%Y')
        year_e = str((plan or {}).get('year') or '')
        ref_param = year_e if year_e else ref
        try:
            jid = _create_iris_job('executivo', ref_param); _start_iris_job_thread(jid)
            wu = url_for('iris_relatorio_wait', job_id=jid)
            return {'reply': _iris_reply(f"Relatório executivo — {_iris_month_label(ref) if ref else year_e}",
                "A IA está preparando o resumo executivo para a diretoria.",
                next_step="Acompanhe pelo botão abaixo."),
                'download_url': wu, 'download_label': '📊 Acompanhar geração do PDF'}
        except Exception as exc:
            return {'reply': _iris_reply("Erro ao gerar relatório executivo", str(exc)[:200])}

    if intent == 'payments_report':
        if fmt == 'excel':
            path = _iris_make_payments_excel(month_ref)
            return {'reply': _iris_reply(f"Excel de pagamentos — {_iris_month_label(month_ref)}", "Organizei a planilha com status, valores, fornecedor, sistema, pedido e documento.", next_step="O arquivo está pronto para download."), 'download_url': url_for('static', filename='exports/' + path.name), 'download_label':'Baixar Excel'}
        try:
            out, arquivo_url = _iris_make_ai_pdf('mensal', month_ref=month_ref or datetime.now().strftime('%m/%Y'))
            return {'reply': _iris_reply(f"Relatório de pagamentos — {_iris_month_label(month_ref)}", "Gerei o PDF com análise detalhada dos pagamentos do período."), 'download_url': arquivo_url, 'download_label': 'Baixar PDF'}
        except Exception:
            path = _iris_make_monthly_pdf(month_ref or datetime.now().strftime('%m/%Y'))
            return {'reply': _iris_reply(f"Relatório de pagamentos — {_iris_month_label(month_ref)}", "Gerei o PDF com os pagamentos dentro do relatório executivo do período.", next_step="Use o botão abaixo para baixar."), 'download_url': url_for('static', filename='exports/' + path.name), 'download_label':'Baixar PDF'}

    if intent == 'payments_total':
        finance = _iris_official_finance(month_ref)
        label = _iris_month_label(month_ref) if month_ref else 'unidade ativa'
        return {'reply': f"Pagamentos aprovados em {label}: {br_money(finance['pagamentos_total'])}."}

    if intent == 'payments_open':
        ctx = _iris_collect_context(month_ref)
        rows = ctx['pagamentos_abertos_rows']
        if not rows:
            return {'reply': _iris_reply(f"Pagamentos em aberto — {_iris_month_label(month_ref)}", "Não localizei pendências financeiras nesse recorte.", next_step="Posso consultar outro mês ou abrir a aba de pagamentos."), 'action_url':url_for('pagamentos'), 'action_label':'Abrir pagamentos'}
        direct = f"Encontrei {len(rows)} pagamento(s) em aberto, totalizando {br_money(ctx['pagamentos_aberto'])}."
        bullets = [f"ID {r.get('id')} — {r.get('fornecedor') or r.get('sistema') or 'Sem fornecedor'} — {br_money(_iris_parse_br_float(r.get('valor')))}" for r in rows[:6]]
        if len(rows) > 6:
            bullets.append(f"Há mais {len(rows)-6} pendência(s) além das listadas aqui.")
        return {'reply': _iris_reply(f"Pagamentos em aberto — {_iris_month_label(month_ref)}", direct, bullets if mode != 'resumo' else bullets[:3], next_step="Quer que eu gere o relatório financeiro desse recorte?"), 'action_url':url_for('pagamentos'), 'action_label':'Abrir pagamentos'}

    if intent == 'payment_lookup':
        rows = _iris_search_payments((plan or {}).get('query') or message)
        if not rows:
            return {'reply': _iris_reply("Não localizei esse pagamento", "Me envie o número do pedido, NF, documento, fornecedor ou uma palavra da descrição que eu procuro novamente.")}
        r = rows[0]
        status = _iris_payment_status(r)
        val = br_money(_iris_parse_br_float(r.get('valor')))
        return {'reply': _iris_reply(f"Pagamento localizado — ID {r.get('id')}", f"Status: {status}. Valor: {val}.", [f"Fornecedor/Sistema: {r.get('fornecedor') or r.get('sistema') or 'Não informado'}.", f"Descrição: {r.get('descricao_servico') or 'sem descrição cadastrada'}."], next_step="Se quiser, eu abro a aba de pagamentos já para conferência."), 'action_url':url_for('pagamentos'), 'action_label':'Abrir pagamentos'}

    if intent == 'top_os_system':
        ctx = _iris_collect_context(month_ref)
        if not ctx['by_system_os']:
            return {'reply': _iris_reply("Não encontrei O.S. nesse recorte", "Posso consultar outro mês ou o período geral.")}
        sys, total = ctx['by_system_os'][0]
        bullets = []
        if ctx['by_unit_os']:
            bullets.append(f"Local/unidade mais recorrente: {ctx['by_unit_os'][0][0]} ({ctx['by_unit_os'][0][1]} ocorrência(s)).")
        return {'reply': _iris_reply(f"Sistema com maior volume de O.S. — {_iris_month_label(month_ref)}", f"O sistema {sys} lidera o recorte, com {total} O.S.", bullets, note="Leitura técnica: esse indicador ajuda a priorizar manutenção preventiva e análise de reincidência.", next_step="Posso abrir a aba de O.S. filtrada por esse sistema."), 'action_url':url_for('os_page') + '?busca=' + urllib_parse.quote(sys), 'action_label':'Ver O.S. desse sistema'}

    if intent == 'os_late':
        rows = _iris_rows('os_ordens', limit=1000)
        late = [r for r in rows if os_is_overdue(r)]
        if not late:
            return {'reply': _iris_reply("O.S. atrasadas", "Não encontrei O.S. atrasadas no momento.")}
        bullets = [f"O.S. {r.get('id')} — {r.get('sistema')} — {r.get('equipamento')} — {r.get('data')}" for r in late[:10]]
        return {'reply': _iris_reply("O.S. atrasadas", f"Localizei {len(late)} ordem(ns) em atraso.", bullets, next_step="Posso abrir a tela já filtrada para você conferir."), 'action_url':url_for('os_page', status='atrasada'), 'action_label':'Abrir O.S. atrasadas'}

    if intent == 'open_os':
        os_id = (plan or {}).get('os_id') or ''.join(re.findall(r'\d+', message)[:1])
        return {'reply': f'Perfeito — vou abrir a O.S. {os_id} para você.', 'action_url':url_for('os_page') + f'?abrir_os={os_id}', 'auto_open': True}

    if intent == 'create_os_draft':
        params = _iris_extract_create_params((plan or {}).get('raw') or message, plan)
        qs = urllib_parse.urlencode({'iris_create':'1', **{k:v for k,v in params.items() if v}})
        return {'reply': _iris_reply("Nova O.S. em rascunho", "Abri o formulário com as informações que consegui identificar.", [f"Data: {params.get('data') or 'não informada'}.", f"Sistema: {params.get('sistema') or 'não informado'}.", f"Unidade/equipamento: {params.get('unidade') or 'não informado'}.", f"Responsável: {params.get('responsavel') or 'não informado'}."], next_step="Ela só será salva depois da sua confirmação."), 'action_url':url_for('os_page') + '?' + qs, 'auto_open': True}

    if intent == 'fuel_costs':
        finance = _iris_official_finance(month_ref)
        total = finance['combustivel_total']
        label = _iris_month_label(month_ref) if month_ref else 'unidade ativa'
        return {'reply': f"Combustível em {label}: {br_money(total)}."}

    if intent == 'cost_subject':
        tt = _iris_normalize(message)
        if any(x in tt for x in ['combustivel', 'abastecimento', 'gasolina', 'diesel', 'etanol']):
            finance = _iris_official_finance(month_ref)
            total = finance['combustivel_total']
            label = _iris_month_label(month_ref) if month_ref else 'unidade ativa'
            return {'reply': f"Combustível em {label}: {br_money(total)}."}
        return _iris_cost_subject_answer(message, month_ref, mode)

    if intent == 'costs_summary':
        finance = _iris_official_finance(month_ref)
        pagamentos = finance['pagamentos_total']
        combustivel = finance['combustivel_total']
        total = finance['gasto_total']
        if not total:
            return {'reply': "Não localizei gastos lançados para a unidade ativa."}
        label = _iris_month_label(month_ref) if month_ref else 'unidade ativa'
        return {'reply': (
            f"Gasto total em {label}: {br_money(total)}.\n"
            f"Pagamentos aprovados: {br_money(pagamentos)}.\n"
            f"Combustível: {br_money(combustivel)}."
        )}


    # free_answer: perguntas abertas via IA
    if intent == 'free_answer':
        q_free = (plan or {}).get('message') or message
        ctx = _iris_context_summary()
        fp = f"Você é a Iris, consultora operacional do IRIS de gestão de saneamento. Responda em português, direto e prático, como gestora experiente. Max 400 palavras. Dados da empresa: {ctx}\n\nPergunta: {q_free}"
        text, _ = _iris_call_claude(fp, max_tokens=1200)
        if text:
            return {'reply': {'title': '💡 Iris', 'summary': text, 'sections': []}}

        q = (plan or {}).get('query') or message
    qn = _iris_normalize(q)
    rows = []
    for table, fields in [('os_ordens',['id','sistema','equipamento','responsavel','descricao','servico_executado']), ('pagamentos',['id','sistema','equipamento','fornecedor','descricao_servico','sc_pedido','numero_documento'])]:
        for r in _iris_rows(table, limit=800):
            hay = _iris_normalize(' '.join(str(r.get(f) or '') for f in fields))
            if qn and any(part in hay for part in qn.split() if len(part)>2):
                rows.append((table,r))
                if len(rows)>=8: break
    if not rows:
        return {'reply': _iris_reply("Não encontrei um resultado seguro", "Posso procurar melhor se você citar O.S., sistema, unidade, fornecedor, pedido, NF ou uma palavra da descrição.", next_step="Exemplo: ‘Iris, gastos com bombas em abril’ ou ‘pedido 159 foi pago?’")}
    bullets=[]
    for table, r in rows:
        if table == 'os_ordens':
            bullets.append(f"O.S. {r.get('id')} — {r.get('sistema')} — {r.get('equipamento')} — {r.get('status')}")
        else:
            bullets.append(f"Pagamento {r.get('id')} — {r.get('fornecedor') or r.get('sistema')} — {_iris_payment_status(r)} — {br_money(_iris_parse_br_float(r.get('valor')))}")
    return {'reply': _iris_reply("Resultados encontrados", f"Localizei {len(rows)} ocorrência(s) relacionadas ao termo pesquisado.", bullets, next_step="Quer que eu abra a área correspondente ou gere um relatório?")}

def iris_chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get('message') or '').strip()
    if not message:
        return jsonify({'reply': 'Me manda uma pergunta ou comando pra eu executar.'})

    history = session.get('iris_history') or []
    effective = message
    if len(_iris_normalize(message).split()) <= 4 and history:
        effective = history[-1].get('user', '') + '\nPergunta complementar: ' + message

    try:
        tn = _iris_normalize(effective)

        # Tenta resposta direta via IA primeiro (menos engessada)
        ctx = _iris_context_summary()
        hist_ctx = ''
        if history:
            hist_ctx = '\n'.join([f"Usuário: {h.get('user','')}" for h in history[-3:]])

        hist_ctx_label = ('Histórico recente:\n' + hist_ctx) if hist_ctx else ''
        direct_prompt = f"""Você é a Iris, consultora operacional integrada ao sistema IRIS de gestão de saneamento e infraestrutura.
Responda em português, de forma direta, prática e útil. Máximo 350 palavras.
Use bullet points quando ajudar a organizar.
Se o usuário pedir um relatório, diga que está gerando e qual comando usar.
Se for pergunta sobre dados específicos (pagamentos, O.S., custos), responda com base no contexto abaixo.

Contexto atual da empresa:
{ctx}

{hist_ctx_label}

Pergunta/comando: {effective}"""

        text, prov = _iris_call_claude(direct_prompt, max_tokens=800)
        if text:
            # Verifica se a mensagem pede algo que precisa de uma intent específica
            keywords_relatorio = ['relatorio', 'relatório', 'pdf', 'gerar', 'baixar', 'exportar', 'excel']
            keywords_os = ['criar os', 'nova os', 'abrir os', 'create_os']
            if any(k in tn for k in keywords_relatorio + keywords_os):
                # Tenta a intent estruturada também
                plan = _iris_ai_plan(effective) or _iris_fallback_plan(effective)
                if plan.get('intent') not in ('search', 'free_answer', None):
                    ans = _iris_answer(plan, effective)
                    history.append({'user': message, 'reply': ans.get('reply', ''), 'intent': plan.get('intent', '')})
                    session['iris_history'] = history[-8:]
                    return jsonify(ans)

            ans = {'reply': {'title': '💡 Iris', 'summary': text, 'sections': []}}
            history.append({'user': message, 'reply': text, 'intent': 'direct'})
            session['iris_history'] = history[-8:]
            return jsonify(ans)

        # Fallback: intent estruturada
        if any(w in tn for w in ['quanto', 'gasto', 'gastamos', 'custo', 'custos', 'despesa', 'valor', 'combustivel']):
            plan = _iris_fallback_plan(effective)
        else:
            plan = _iris_ai_plan(effective) or _iris_fallback_plan(effective)

        ans = _iris_answer(plan, effective)
        history.append({'user': message, 'reply': ans.get('reply', ''), 'intent': plan.get('intent') if isinstance(plan, dict) else ''})
        session['iris_history'] = history[-8:]
        return jsonify(ans)

    except Exception as exc:
        current_app.logger.error('iris_chat erro: %s', exc)
        return jsonify({'reply': {'title': 'Iris', 'summary': f'Erro interno: {str(exc)[:200]}. Tente novamente.', 'sections': []}})





def register_iris_routes(app):
    app.add_url_rule('/iris/chat', 'iris_chat', iris_chat, methods=['POST'])
