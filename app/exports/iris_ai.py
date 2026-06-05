"""Geração de texto IA para relatórios PDF."""
import os

from app.exports.iris_data import _iris_parse_br_float, _iris_rows
from app.os.services import os_is_overdue
from app.shared.formatters import br_money

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None

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


def _iris_build_rich_context(ctx, tipo='mensal', periodo_label=''):
    """Monta contexto COMPLETO e detalhado para a IA ter tudo que precisa para análise profunda."""
    lines = [
        f"SISTEMA IRIS — DADOS COMPLETOS DO PERÍODO: {periodo_label.upper()}",
        "=" * 70, ""
    ]

    os_rows = ctx.get('os_rows', [])

    # ── ORDENS DE SERVIÇO ────────────────────────────────────────────────────
    finalizadas = sum(1 for r in os_rows if str(r.get('finalizada') or '').lower() == 'sim')
    em_andamento = sum(1 for r in os_rows if str(r.get('status') or '').lower() == 'em andamento')
    atrasadas = sum(1 for r in os_rows if os_is_overdue(r))
    com_troca = sum(1 for r in os_rows if str(r.get('troca_componentes') or '').lower() == 'sim')
    taxa_conclusao = round(finalizadas / len(os_rows) * 100, 1) if os_rows else 0
    taxa_atraso = round(atrasadas / len(os_rows) * 100, 1) if os_rows else 0

    tempos = [int(r.get('acumulado_minutos') or 0) for r in os_rows if int(r.get('acumulado_minutos') or 0) > 0]
    tempo_medio = sum(tempos) // len(tempos) if tempos else 0
    tempo_max = max(tempos) if tempos else 0
    tempo_min = min(tempos) if tempos else 0

    lines.append("1. ORDENS DE SERVIÇO")
    lines.append(f"   Total: {len(os_rows)} O.S.")
    lines.append(f"   Finalizadas: {finalizadas} ({taxa_conclusao}%)")
    lines.append(f"   Em andamento: {em_andamento}")
    lines.append(f"   Atrasadas: {atrasadas} ({taxa_atraso}%)")
    lines.append(f"   Com troca de componentes: {com_troca} ({round(com_troca/len(os_rows)*100,1) if os_rows else 0}%)")
    if tempo_medio:
        lines.append(f"   Tempo médio de atendimento: {tempo_medio//60}h{tempo_medio%60:02d}min")
        lines.append(f"   Tempo máximo: {tempo_max//60}h{tempo_max%60:02d}min | Mínimo: {tempo_min//60}h{tempo_min%60:02d}min")

    # Sistemas — TODOS
    lines.append("")
    lines.append("   TODOS OS SISTEMAS (ranking por volume):")
    comp_map = dict(ctx.get('component_by_system', []))
    for sys, qtd in ctx.get('by_system_os', []):
        perc = round(qtd / len(os_rows) * 100, 1) if os_rows else 0
        trocas = comp_map.get(sys, 0)
        lines.append(f"   - {sys}: {qtd} O.S. ({perc}%) | trocas de componentes: {trocas}")

    # Equipamentos — todos
    lines.append("")
    lines.append("   EQUIPAMENTOS MAIS ACIONADOS:")
    for unit, qtd in ctx.get('by_unit_os', [])[:15]:
        lines.append(f"   - {unit}: {qtd} ocorrências")

    # Detalhamento de cada O.S. com troca de componente
    os_com_troca = [r for r in os_rows if str(r.get('troca_componentes') or '').lower() == 'sim']
    if os_com_troca:
        lines.append("")
        lines.append("   DETALHAMENTO DAS TROCAS DE COMPONENTES:")
        for r in os_com_troca:
            sistema = r.get('sistema') or 'Não informado'
            equip = r.get('equipamento') or r.get('ativo_nome') or 'Não informado'
            comp = (r.get('componentes_descricao') or r.get('componentes') or 'Não especificado').strip()
            data = r.get('data') or ''
            resp = r.get('responsavel') or ''
            lines.append(f"   • {data} | {sistema} / {equip}")
            lines.append(f"     Componente: {comp}")
            if resp:
                lines.append(f"     Responsável: {resp}")

    # Responsáveis mais ativos
    resp_count = {}
    for r in os_rows:
        resp = (r.get('responsavel') or '').strip()
        if resp:
            resp_count[resp] = resp_count.get(resp, 0) + 1
    if resp_count:
        lines.append("")
        lines.append("   TÉCNICOS / RESPONSÁVEIS:")
        for resp, qtd in sorted(resp_count.items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"   - {resp}: {qtd} O.S.")

    lines.append("")

    # ── FINANCEIRO ──────────────────────────────────────────────────────────
    pags_total = ctx.get('pagamentos_total', 0)
    comb_total = ctx.get('combustivel_total', 0)
    gasto_total = ctx.get('gasto_realizado_total', 0)
    aberto_total = ctx.get('pagamentos_aberto', 0)
    pago_total = pags_total - aberto_total

    lines.append("2. FINANCEIRO")
    lines.append(f"   Gasto total do período: {br_money(gasto_total)}")
    lines.append(f"   Pagamentos (fornecedores): {br_money(pags_total)}")
    lines.append(f"     - Já pagos: {br_money(pago_total)}")
    lines.append(f"     - Pendentes: {br_money(aberto_total)}")
    lines.append(f"   Combustível: {br_money(comb_total)}")

    # Fornecedores — TODOS com valor e percentual
    pags = ctx.get('pagamentos', [])
    if pags:
        por_fornecedor = {}
        por_categoria = {}
        for p in pags:
            forn = (p.get('fornecedor') or 'Não informado').strip()
            val = _iris_parse_br_float(p.get('valor'))
            por_fornecedor[forn] = por_fornecedor.get(forn, 0) + val
            desc = (p.get('descricao_servico') or p.get('tipo_documento') or 'Outros').strip()
            cat = desc[:40] if desc else 'Outros'
            por_categoria[cat] = por_categoria.get(cat, 0) + val

        lines.append("")
        lines.append("   TODOS OS FORNECEDORES:")
        for forn, val in sorted(por_fornecedor.items(), key=lambda x: x[1], reverse=True):
            perc = round(val / pags_total * 100, 1) if pags_total else 0
            lines.append(f"   - {forn}: {br_money(val)} ({perc}%)")

    # Pagamentos pendentes — TODOS
    abertos = ctx.get('pagamentos_abertos_rows', [])
    if abertos:
        lines.append("")
        lines.append(f"   PAGAMENTOS PENDENTES ({len(abertos)} lançamentos):")
        for p in abertos:
            forn = (p.get('fornecedor') or 'Sem fornecedor').strip()
            val = br_money(_iris_parse_br_float(p.get('valor')))
            desc = (p.get('descricao_servico') or '').strip()[:60]
            mes = p.get('pagamento_mes') or ''
            lines.append(f"   - {forn} | {val} | {desc} | {mes}")

    # Combustível por motorista
    comb_rows = ctx.get('combustivel_rows', [])
    if comb_rows:
        por_motorista = {}
        por_veiculo = {}
        for r in comb_rows:
            m = (r.get('motorista') or 'Não informado').strip()
            v = (r.get('modelo_veiculo') or r.get('placa') or '').strip()
            val = _iris_parse_br_float(r.get('custo'))
            por_motorista[m] = por_motorista.get(m, 0) + val
            if v:
                por_veiculo[v] = por_veiculo.get(v, 0) + val
        lines.append("")
        lines.append("   COMBUSTÍVEL POR MOTORISTA:")
        for mot, val in sorted(por_motorista.items(), key=lambda x: x[1], reverse=True):
            perc = round(val / comb_total * 100, 1) if comb_total else 0
            lines.append(f"   - {mot}: {br_money(val)} ({perc}%)")

    lines.append("")

    # ── BOMBAS / ESTOQUE ─────────────────────────────────────────────────────
    try:
        bombas_rows = _iris_rows('bombas', limit=200)
        if bombas_rows:
            em_conserto = [r for r in bombas_rows if str(r.get('localizacao') or '').lower() == 'conserto']
            atrasadas_b = [r for r in bombas_rows if str(r.get('status_entrega') or '').lower() == 'em atraso']
            lines.append("3. ESTOQUE DE BOMBAS")
            lines.append(f"   Total cadastrado: {len(bombas_rows)}")
            lines.append(f"   Em conserto: {len(em_conserto)}")
            lines.append(f"   Com entrega atrasada: {len(atrasadas_b)}")
            if em_conserto:
                lines.append("   Bombas em conserto:")
                for b in em_conserto[:10]:
                    lines.append(f"   - {b.get('equipamento') or b.get('nome') or 'Bomba'} | {b.get('fornecedor') or ''} | Prev: {b.get('previsao_entrega') or 'Não informado'}")
            lines.append("")
    except Exception:
        pass

    # ── CUSTOS ───────────────────────────────────────────────────────────────
    custos = ctx.get('custos_rows', [])
    if custos:
        lines.append("4. CUSTOS REGISTRADOS")
        lines.append(f"   Total de registros: {len(custos)}")
        por_sistema_custo = {}
        for c in custos:
            s = (c.get('sistema') or 'Não informado').strip()
            por_sistema_custo[s] = por_sistema_custo.get(s, 0) + 1
        for s, qtd in sorted(por_sistema_custo.items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"   - {s}: {qtd} registro(s)")
        lines.append("")

    lines.append("=" * 70)
    lines.append("FIM DOS DADOS — analise tudo com profundidade e rigor técnico.")
    return '\n'.join(lines)




def _iris_call_claude(prompt, max_tokens=4000):
    """Chama Claude via API da Anthropic. Retorna (texto, 'claude') ou (None, None)."""
    key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not key:
        return None, None
    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=key, timeout=45.0)
        msg = client.messages.create(
            model=os.environ.get('ANTHROPIC_IRIS_MODEL', 'claude-haiku-4-5-20251001'),
            max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}]
        )
        text = ''
        for block in (msg.content or []):
            if hasattr(block, 'text'):
                text += block.text
        return text.strip() or None, 'claude'
    except Exception as exc:
        print(f'Iris Claude falhou: {exc}')
        return None, None




def _iris_call_openai(prompt, max_tokens=4000, json_mode=False):
    """Chama OpenAI. Retorna (texto, 'openai') ou (None, None)."""
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key or OpenAI is None:
        return None, None
    try:
        client = OpenAI(api_key=key, timeout=45.0)
        kwargs = dict(
            model=os.environ.get('OPENAI_IRIS_MODEL', 'gpt-4o-mini'),
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        if json_mode:
            kwargs['response_format'] = {'type': 'json_object'}
        resp = client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or '').strip()
        return text or None, 'openai'
    except Exception as exc:
        print(f'Iris OpenAI falhou: {exc}')
        return None, None




def _iris_call_ai(prompt, max_tokens=4000, json_mode=False):
    """Claude primeiro, OpenAI como fallback. Retorna (texto, provedor) ou (None, None)."""
    if json_mode:
        # Para plano/intent: OpenAI tem json_mode nativo; Claude retorna JSON sem wrapper
        text, prov = _iris_call_claude(prompt, max_tokens=1000)
        if text:
            return text, prov
        return _iris_call_openai(prompt, max_tokens=1000, json_mode=True)
    else:
        text, prov = _iris_call_claude(prompt, max_tokens=max_tokens)
        if text:
            return text, prov
        return _iris_call_openai(prompt, max_tokens=max_tokens, json_mode=False)




def _iris_generate_ai_report(tipo, ctx, periodo_label, empresa_nome=''):
    """Gera relatório completo em 3 chamadas paralelas simultâneas.

    Cada chamada escreve 2 seções com 1200 tokens.
    Resultado: ~3600 tokens de conteúdo no tempo de 1 chamada só.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    dados = _iris_build_rich_context(ctx, tipo=tipo, periodo_label=periodo_label)
    empresa_nome = empresa_nome or (current_company() or {}).get('nome') or 'Empresa'

    REGRAS = (
        "Português brasileiro formal. Use apenas os dados fornecidos. "
        "NÃO use tabelas markdown com pipes. Use **negrito** para destaques. "
        "Seja analítico — interprete, não apenas liste. Sem introduções genéricas."
    )

    cabecalho = (
        f"Empresa: {empresa_nome} | Período: {periodo_label}\n"
        f"Regras: {REGRAS}\n\n"
        f"DADOS:\n{dados}\n\n"
    )

    # Define as 3 fatias por tipo de relatório
    fatias = {
        'mensal': [
            ("1. RESUMO EXECUTIVO\n"
             "Síntese de 3 parágrafos: desempenho geral, principais números, 2-3 pontos críticos para a diretoria.\n\n"
             "2. DESEMPENHO OPERACIONAL\n"
             "Analise O.S. em profundidade: volume, taxa de conclusão, sistemas críticos, equipamentos recorrentes, "
             "trocas de componentes com descrição do que foi trocado, tempo de atendimento, eficiência da equipe."),

            ("3. ANÁLISE FINANCEIRA\n"
             "Detalhe todos os gastos e fornecedores com valores e percentuais. Separe claramente pago vs pendente. "
             "Analise concentração de fornecedores e riscos.\n\n"
             "4. PONTOS CRÍTICOS E ALERTAS\n"
             "Liste problemas que precisam de atenção imediata com causa provável e impacto estimado."),

            ("5. RECOMENDAÇÕES\n"
             "Mínimo 5 recomendações concretas e priorizadas. Para cada uma: ação específica, prazo sugerido "
             "e justificativa baseada nos dados."),
        ],
        'anual': [
            ("1. SÍNTESE DO ANO\n"
             "Visão executiva do exercício: performance geral, grandes números, marcos importantes, "
             "comparativo com benchmark do setor de saneamento.\n\n"
             "2. DESEMPENHO OPERACIONAL\n"
             "Análise profunda: volume total de O.S., taxa de conclusão, sistemas mais críticos com reincidência, "
             "equipamentos problemáticos, trocas de componentes detalhadas, tempo médio de atendimento."),

            ("3. ANÁLISE FINANCEIRA\n"
             "Composição total dos investimentos, todos os fornecedores com valores e percentuais, "
             "análise estratégica dos maiores contratos, combustível por motorista, pagamentos pendentes.\n\n"
             "4. SISTEMAS CRÍTICOS E REINCIDÊNCIAS\n"
             "Para cada sistema com mais de 5 O.S.: diagnóstico técnico, causas prováveis, "
             "riscos operacionais e recomendação específica."),

            ("5. TENDÊNCIAS E PADRÕES\n"
             "O que os dados revelam sobre a direção da operação? Sazonalidade, padrões de falha, "
             "evolução dos custos, o que está melhorando e o que preocupa.\n\n"
             "6. RECOMENDAÇÕES ESTRATÉGICAS\n"
             "Mínimo 6 recomendações priorizadas por urgência (curto/médio/longo prazo) "
             "com justificativa baseada nos dados e impacto esperado."),
        ],
        'sistema': [
            ("1. VISÃO GERAL DO PERÍODO\n"
             "Resumo das operações: volume de O.S., taxa de conclusão, sistemas mais acionados.\n\n"
             "2. ANÁLISE TÉCNICA DE FALHAS\n"
             "Para cada sistema: tipo de falha, frequência, equipamentos afetados, "
             "componentes trocados com descrição completa de cada troca."),

            ("3. INDICADORES DE DESEMPENHO\n"
             "MTBF estimado por sistema, taxa de disponibilidade, eficiência da manutenção, "
             "custo estimado por intervenção.\n\n"
             "4. DIAGNÓSTICO POR EQUIPAMENTO\n"
             "Análise individual dos equipamentos com maior número de ocorrências. "
             "Para cada um: histórico, causa raiz provável, risco atual."),

            ("5. PLANO DE AÇÃO TÉCNICO\n"
             "Recomendações técnicas específicas priorizadas por urgência. "
             "Para cada recomendação: ação, recurso necessário, prazo e resultado esperado."),
        ],
        'executivo': [
            ("1. SITUAÇÃO ATUAL\n"
             "Máximo 4 linhas diretas. O que está acontecendo agora na operação.\n\n"
             "2. NÚMEROS-CHAVE DO PERÍODO\n"
             "Os 6-8 indicadores mais importantes com análise do que cada número significa."),

            ("3. O QUE ESTÁ BEM\n"
             "Pontos positivos com dados que sustentam — o que a equipe está fazendo certo.\n\n"
             "4. O QUE PRECISA DE ATENÇÃO IMEDIATA\n"
             "Alertas críticos com impacto financeiro ou operacional estimado. Sem rodeios."),

            ("5. PRÓXIMOS PASSOS\n"
             "5 ações prioritárias ordenadas por urgência. Para cada uma: responsável sugerido, "
             "prazo e resultado esperado em números."),
        ],
    }

    secoes_list = fatias.get(tipo, fatias['mensal'])

    def _chamar_secao(idx, secao_prompt):
        prompt = (
            f"Você é analista sênior de infraestrutura e saneamento com 20 anos de experiência.\n"
            f"{cabecalho}"
            f"Escreva APENAS as seguintes seções do relatório (sem repetir dados de outras seções):\n\n"
            f"{secao_prompt}"
        )
        texto, prov = _iris_call_ai(prompt, max_tokens=1200)
        return idx, texto or '', prov or ''

    # Dispara as 3 chamadas em paralelo
    resultados = {}
    provedor_final = ''
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_chamar_secao, i, s): i for i, s in enumerate(secoes_list)}
        for future in as_completed(futures):
            idx, texto, prov = future.result()
            resultados[idx] = texto
            if prov:
                provedor_final = prov

    # Junta na ordem certa
    texto_final = '\n\n'.join(resultados.get(i, '') for i in range(len(secoes_list))).strip()

    if texto_final:
        print(f'Iris {tipo} gerado via {provedor_final} — {len(texto_final)} chars (3 chamadas paralelas)')
    return texto_final, provedor_final


