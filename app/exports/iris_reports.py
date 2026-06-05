"""Geração de PDF/Excel — relatórios Iris e mensais."""
import os
import re
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import (
    Image as RLImage,
)

from app.config import PROJECT_ROOT
from app.exports.iris_ai import (
    _iris_generate_ai_report,
)
from app.exports.iris_data import (
    _iris_collect_context,
    _iris_month_label,
    _iris_parse_br_float,
    _iris_payment_is_approved,
    _iris_payment_status,
)
from app.os.services import os_is_overdue
from app.shared.formatters import br_money, br_now
from app.shared.rows import row_to_dict
from app.storage import (
    SUPABASE_STORAGE_KEY,
    _upload_pdf_bytes_to_supabase,
    company_folder_name,
    load_company_identity_config,
    slugify_company_name,
)
from app.storage.company import company_identity_file

BASE_DIR = PROJECT_ROOT

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


def _iris_make_ai_pdf(tipo, month_ref='', year='', sistema='', upload_supabase=False):
    """Gera PDF 100% profissional — capa de diretoria + análise completa da IA."""
    from reportlab.graphics.shapes import Drawing, Rect, String

    # ── COLETA DE DADOS ────────────────────────────────────────────────────
    if tipo == 'anual' and year:
        # Coleta DIRETA do banco — não filtra por pagamento_mes exato
        # Isso garante que pagamentos com mês "ABRIL", "04/2026", "4/2026" etc. todos entram
        empresa_id = current_company_id()
        where_empresa = 'AND empresa_id=?' if empresa_id else ''
        params_e = (empresa_id,) if empresa_id else ()

        # O.S. do ano — filtra pela data dd/mm/yyyy
        os_cols = select_existing_columns('os_ordens', [
            'id','data','sistema','equipamento','ativo_nome','status','finalizada',
            'criticidade','responsavel','data_inicio','data_fim','acumulado_minutos',
            'troca_componentes','componentes_descricao','descricao','servico_executado',
            'imagens','teve_terceiro','quem_foi_terceiro','empresa_id'
        ])
        os_rows_raw = query_all(
            f"SELECT {os_cols} FROM os_ordens WHERE COALESCE(data,'') LIKE ? {where_empresa} ORDER BY id ASC",
            (f'%/{year}',) + params_e
        )
        os_rows = [row_to_dict(r) for r in os_rows_raw]

        # Pagamentos do ano — pega TODOS com qualquer referência ao ano
        pag_cols = select_existing_columns('pagamentos', [
            'id','fornecedor','descricao_servico','valor','status','pagamento_mes',
            'tipo_lancamento','numero_documento','sc_pedido','empresa_id'
        ])
        pag_rows_raw = query_all(
            f"""SELECT {pag_cols} FROM pagamentos
                WHERE (
                    COALESCE(pagamento_mes,'') LIKE ?
                    OR COALESCE(pagamento_mes,'') LIKE ?
                ) {where_empresa} ORDER BY id ASC""",
            (f'%/{year}', f'%{year}%') + params_e
        )
        pag_rows = [row_to_dict(r) for r in pag_rows_raw]

        # Combustível do ano
        comb_cols = select_existing_columns('combustivel', [
            'id','data','mes_ref','motorista','modelo_veiculo','placa','custo','empresa_id'
        ])
        comb_rows_raw = query_all(
            f"""SELECT {comb_cols} FROM combustivel
                WHERE (
                    COALESCE(mes_ref,'') LIKE ?
                    OR COALESCE(data,'') LIKE ?
                ) {where_empresa} ORDER BY id ASC""",
            (f'%/{year}', f'%/{year}') + params_e
        )
        comb_rows = [row_to_dict(r) for r in comb_rows_raw]

        # Custos do ano
        cust_cols = select_existing_columns('custos', [
            'id','sistema','equipamento','nr_os','descricao_os','mes','empresa_id'
        ])
        cust_rows = [row_to_dict(r) for r in query_all(
            f"SELECT {cust_cols} FROM custos WHERE COALESCE(mes,'') LIKE ? {where_empresa}",
            (f'%/{year}',) + params_e
        )]

        # Calcula totais financeiros reais
        pags_aprovados = [p for p in pag_rows if _iris_payment_is_approved(p)]
        pags_abertos = [p for p in pag_rows if not _iris_payment_is_approved(p)]
        pagamentos_total = sum(_iris_parse_br_float(p.get('valor')) for p in pags_aprovados)
        pagamentos_aberto = sum(_iris_parse_br_float(p.get('valor')) for p in pags_abertos)
        combustivel_total = sum(_iris_parse_br_float(r.get('custo')) for r in comb_rows)

        ctx = {
            'os_rows': os_rows,
            'pagamentos': pags_aprovados,
            'pagamentos_abertos_rows': pags_abertos,
            'combustivel_rows': comb_rows,
            'custos_rows': cust_rows,
            'pagamentos_total': pagamentos_total,
            'pagamentos_aberto': pagamentos_aberto,
            'combustivel_total': combustivel_total,
            'gasto_realizado_total': pagamentos_total + combustivel_total,
            'pagamentos_pago': pagamentos_total,
            'os_total': len(os_rows),
            'os_custo_total': 0,
            'by_system_os': [], 'by_unit_os': [],
            'component_by_system': [], 'by_system_cost': [], 'by_system_os_cost': [],
        }

        # Rankings
        sys_os, unit_os, comp_sys = {}, {}, {}
        for r in os_rows:
            s = (r.get('sistema') or 'Não informado').strip()
            u = (r.get('equipamento') or r.get('ativo_nome') or 'Não informado').strip()
            sys_os[s] = sys_os.get(s, 0) + 1
            unit_os[u] = unit_os.get(u, 0) + 1
            if str(r.get('troca_componentes') or '').lower() == 'sim':
                comp_sys[s] = comp_sys.get(s, 0) + 1
        ctx['by_system_os'] = sorted(sys_os.items(), key=lambda x: x[1], reverse=True)
        ctx['by_unit_os'] = sorted(unit_os.items(), key=lambda x: x[1], reverse=True)
        ctx['component_by_system'] = sorted(comp_sys.items(), key=lambda x: x[1], reverse=True)

        # Período real
        _mes_real = br_now().month
        _meses_pt = {1:'Janeiro',2:'Fevereiro',3:'Março',4:'Abril',5:'Maio',6:'Junho',
                     7:'Julho',8:'Agosto',9:'Setembro',10:'Outubro',11:'Novembro',12:'Dezembro'}
        periodo_label = f'Janeiro a {_meses_pt.get(_mes_real, "")} de {year}'

        print(f'Iris anual {year}: {len(os_rows)} O.S., {len(pag_rows)} pagamentos, R$ {pagamentos_total:,.2f}')
    elif tipo == 'sistema' and sistema:
        ctx = _iris_collect_context(month_ref)
        ctx['os_rows'] = [r for r in ctx['os_rows'] if sistema.lower() in (r.get('sistema') or '').lower()]
        periodo_label = f'{sistema} — {_iris_month_label(month_ref) if month_ref else "Histórico geral"}'
    else:
        ctx = _iris_collect_context(month_ref)
        periodo_label = _iris_month_label(month_ref) if month_ref else 'Período geral'

    empresa = current_company() or {}
    empresa_nome = empresa.get('nome') or 'Empresa'
    empresa_slug = slugify_company_name(empresa_nome)
    cfg_pdf = load_company_identity_config(current_company_id())

    # ── GERAR TEXTO COM IA ────────────────────────────────────────────────
    texto_ia, provedor = _iris_generate_ai_report(tipo, ctx, periodo_label, empresa_nome)

    # ── CONFIGURAR PDF ────────────────────────────────────────────────────
    tmp = BASE_DIR / 'static' / 'exports'
    tmp.mkdir(parents=True, exist_ok=True)
    tipo_slug = {'mensal': 'mensal', 'anual': 'anual', 'sistema': 'sistema', 'executivo': 'executivo'}.get(tipo, tipo)
    ref_slug = (year or month_ref or 'geral').replace('/', '-')
    out = tmp / f'iris_{tipo_slug}_{empresa_slug}_{ref_slug}.pdf'

    # Página personalizada sem margens para capa
    W, H = A4
    AZUL_ESCURO = colors.HexColor('#0d2461')
    AZUL_MEDIO = colors.HexColor('#1a4a8a')
    AZUL_CLARO = colors.HexColor('#e8f0fb')
    VERDE = colors.HexColor('#2d7a3a')
    CINZA = colors.HexColor('#6b7a90')
    BRANCO = colors.white

    # ── ESTILOS ───────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def st(name, **kw):
        return ParagraphStyle(name, **kw)

    # Estilos de conteúdo
    st_h1 = st('H1', fontName='Helvetica-Bold', fontSize=14,
               textColor=AZUL_ESCURO, spaceBefore=14*mm, spaceAfter=4*mm, leading=18)
    st_h2 = st('H2', fontName='Helvetica-Bold', fontSize=11,
               textColor=AZUL_MEDIO, spaceBefore=8*mm, spaceAfter=3*mm, leading=15)
    st_h3 = st('H3', fontName='Helvetica-Bold', fontSize=10,
               textColor=AZUL_MEDIO, spaceBefore=5*mm, spaceAfter=2*mm, leading=13)
    st_body = st('Body', fontName='Helvetica', fontSize=9.5,
                 textColor=colors.HexColor('#1f2d3d'), leading=14, spaceAfter=4*mm,
                 alignment=TA_JUSTIFY)
    st_bullet = st('Bullet', fontName='Helvetica', fontSize=9.5,
                   textColor=colors.HexColor('#1f2d3d'), leading=13,
                   leftIndent=10, firstLineIndent=-10, spaceAfter=2*mm)
    st_caption = st('Caption', fontName='Helvetica', fontSize=8,
                    textColor=CINZA, leading=11, spaceAfter=2*mm)
    st_label_tbl = st('LabelTbl', fontName='Helvetica-Bold', fontSize=8.5,
                      textColor=AZUL_ESCURO, alignment=TA_LEFT)
    st_data_tbl = st('DataTbl', fontName='Helvetica', fontSize=8.5,
                     textColor=colors.HexColor('#1f2d3d'), alignment=TA_LEFT)

    # ── HELPERS ───────────────────────────────────────────────────────────
    def divider(color=AZUL_CLARO, thickness=0.5):
        return HRFlowable(width='100%', thickness=thickness, color=color,
                          spaceAfter=4*mm, spaceBefore=2*mm)

    def section_badge(texto, cor=AZUL_ESCURO):
        """Box colorido com número/título da seção."""
        d = Drawing(170*mm, 10*mm)
        d.add(Rect(0, 0, 170*mm, 10*mm, fillColor=cor, strokeColor=None))
        d.add(String(5*mm, 2.5*mm, texto, fontName='Helvetica-Bold',
                     fontSize=9, fillColor=BRANCO))
        return d

    def kpi_card(valor, label, cor_fundo=AZUL_CLARO, cor_valor=AZUL_ESCURO):
        st_v = st(f'KV_{label}', fontName='Helvetica-Bold', fontSize=14,
                  textColor=cor_valor, alignment=TA_CENTER, leading=17)
        st_l = st(f'KL_{label}', fontName='Helvetica', fontSize=7.5,
                  textColor=CINZA, alignment=TA_CENTER, leading=10)
        inner = Table(
            [[Paragraph(str(valor), st_v)], [Paragraph(label, st_l)]],
            colWidths=[38*mm]
        )
        inner.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), cor_fundo),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ('ROUNDEDCORNERS', [4,4,4,4]),
        ]))
        return inner

    def make_table(headers, rows, col_widths=None, zebra=True):
        """Cria tabela profissional com cabeçalho azul e zebra."""
        data = [[Paragraph(h, st_label_tbl) for h in headers]]
        for row in rows:
            data.append([Paragraph(str(c), st_data_tbl) for c in row])
        if not col_widths:
            total = 170*mm
            col_widths = [total / len(headers)] * len(headers)
        t = Table(data, colWidths=col_widths, repeatRows=1)
        style = [
            ('BACKGROUND', (0,0), (-1,0), AZUL_ESCURO),
            ('TEXTCOLOR', (0,0), (-1,0), BRANCO),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#c5d5ea')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]
        if zebra:
            for i in range(1, len(data)):
                if i % 2 == 0:
                    style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#f0f5fc')))
                else:
                    style.append(('BACKGROUND', (0,i), (-1,i), BRANCO))
        t.setStyle(TableStyle(style))
        return t

    def parse_ai_text(texto):
        """Converte texto da IA em elementos ReportLab sem markdown cru."""
        elems = []
        if not texto:
            return elems
        linhas = texto.split('\n')
        i = 0
        while i < len(linhas):
            linha = linhas[i].rstrip()
            linha_strip = linha.strip()

            if not linha_strip:
                elems.append(Spacer(1, 3*mm))
                i += 1
                continue

            # Remove markdown de tabelas
            if linha_strip.startswith('|') and '|' in linha_strip[1:]:
                i += 1
                continue
            if re.match(r'^[\|\-\s]+$', linha_strip):
                i += 1
                continue

            # Título nível 1: ##, ###, ou "1. TITULO" ou "TITULO MAIÚSCULO"
            clean = re.sub(r'^#{1,4}\s*', '', linha_strip)
            clean_bold = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', clean)
            clean_bold = re.sub(r'\*(.+?)\*', r'<i>\1</i>', clean_bold)

            is_h1 = (
                re.match(r'^\d+\.\s+[A-ZÁÉÍÓÚÀÂÃÊÕÇ]', linha_strip) or
                re.match(r'^#{1,2}\s+', linha) or
                (linha_strip.isupper() and 5 < len(linha_strip) < 70 and not linha_strip.startswith('-'))
            )
            is_h2 = (
                re.match(r'^\d+\.\d+\s+[A-ZÁÉÍÓÚ]', linha_strip) or
                re.match(r'^#{3,4}\s+', linha)
            )
            is_h3 = re.match(r'^\d+\.\d+\.\d+', linha_strip)
            is_bullet = (
                linha_strip.startswith(('- ', '• ', '* ', '· ')) or
                re.match(r'^\d+[\)\.]\s+', linha_strip)
            )

            if is_h3:
                elems.append(Paragraph(clean_bold, st_h3))
            elif is_h2:
                elems.append(divider())
                elems.append(Paragraph(clean_bold, st_h2))
            elif is_h1:
                elems.append(Spacer(1, 2*mm))
                elems.append(Paragraph(clean_bold, st_h1))
                elems.append(HRFlowable(width='100%', thickness=1.5,
                                        color=AZUL_ESCURO, spaceAfter=3*mm))
            elif is_bullet:
                txt = re.sub(r'^[-•*·]\s+', '', linha_strip)
                txt = re.sub(r'^\d+[\)\.]\s+', '', txt)
                txt_bold = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', txt)
                txt_bold = re.sub(r'\*(.+?)\*', r'<i>\1</i>', txt_bold)
                elems.append(Paragraph(f'<bullet>•</bullet>{txt_bold}', st_bullet))
            else:
                elems.append(Paragraph(clean_bold, st_body))
            i += 1
        return elems

    # ── MONTAGEM DO PDF ───────────────────────────────────────────────────
    tipo_label = {
        'mensal': 'RELATÓRIO MENSAL',
        'anual': 'RELATÓRIO ANUAL',
        'sistema': 'RELATÓRIO POR SISTEMA',
        'executivo': 'RELATÓRIO EXECUTIVO'
    }.get(tipo, 'RELATÓRIO')

    # Logos
    logo_esq = (company_identity_file('logo_esquerda.png', current_company_id()) or
                company_identity_file('logo.png', current_company_id()))
    logo_dir = company_identity_file('logo_direita.png', current_company_id())
    logo_sidebar = BASE_DIR / 'static' / 'logo_sidebar.png'

    def _on_capa(canvas, doc):
        """Desenha a capa profissional diretamente no canvas."""
        canvas.saveState()
        # Fundo azul escuro cobrindo toda a página
        canvas.setFillColor(AZUL_ESCURO)
        canvas.rect(0, 0, W, H, fill=1, stroke=0)

        # Faixa azul claro superior (área de logos)
        canvas.setFillColor(colors.HexColor('#f0f5fc'))
        canvas.rect(0, H - 55*mm, W, 55*mm, fill=1, stroke=0)

        # Círculos decorativos (canto superior direito — estilo da referência)
        canvas.setFillColor(colors.HexColor('#1a4a8a'))
        canvas.setStrokeColor(colors.HexColor('#2d6bb5'))
        canvas.setLineWidth(2)
        canvas.circle(W - 10*mm, H - 10*mm, 60*mm, fill=0, stroke=1)
        canvas.circle(W - 10*mm, H - 10*mm, 45*mm, fill=0, stroke=1)
        canvas.setFillColor(colors.HexColor('#2d6bb5'))
        canvas.circle(W - 5*mm, H + 5*mm, 30*mm, fill=1, stroke=0)

        # Círculos decorativos verdes (canto superior direito)
        canvas.setStrokeColor(colors.HexColor('#2d7a3a'))
        canvas.setLineWidth(2.5)
        canvas.setFillColor(colors.HexColor('#2d7a3a'))
        canvas.circle(W - 8*mm, H - 8*mm, 25*mm, fill=0, stroke=1)

        # Grid de pontos (canto superior esquerdo — estilo da referência)
        canvas.setFillColor(colors.HexColor('#2d6bb5'))
        for row in range(5):
            for col in range(5):
                canvas.circle(12*mm + col*5*mm, H - 12*mm - row*5*mm, 1.5, fill=1, stroke=0)

        # Logos no topo (sobre fundo claro)
        logo_y = H - 48*mm
        logo_h = 20*mm
        if logo_esq and Path(str(logo_esq)).exists():
            try:
                img = ImageReader(str(logo_esq))
                iw, ih = img.getSize()
                scale = logo_h / ih
                canvas.drawImage(str(logo_esq), 14*mm, logo_y,
                                 width=iw*scale, height=logo_h,
                                 preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        if logo_dir and Path(str(logo_dir)).exists():
            try:
                img = ImageReader(str(logo_dir))
                iw, ih = img.getSize()
                scale = logo_h / ih
                draw_w = iw * scale
                canvas.drawImage(str(logo_dir), W - 14*mm - draw_w, logo_y,
                                 width=draw_w, height=logo_h,
                                 preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        # Separador entre logos
        canvas.setStrokeColor(colors.HexColor('#c5d5ea'))
        canvas.setLineWidth(0.5)
        canvas.line(W/2, H - 50*mm, W/2, H - 32*mm)

        # Título principal (grande, branco, lado esquerdo)
        canvas.setFillColor(BRANCO)
        canvas.setFont('Helvetica-Bold', 42)
        titulo_partes = tipo_label.split()
        y_titulo = H * 0.68
        for parte in titulo_partes:
            canvas.drawString(14*mm, y_titulo, parte)
            y_titulo -= 46

        # Linha decorativa (verde + azul, como na referência)
        canvas.setLineWidth(4)
        canvas.setStrokeColor(AZUL_MEDIO)
        canvas.line(14*mm, y_titulo - 2*mm, 80*mm, y_titulo - 2*mm)
        canvas.setStrokeColor(VERDE)
        canvas.line(80*mm, y_titulo - 2*mm, 110*mm, y_titulo - 2*mm)

        # Período
        canvas.setFont('Helvetica-Bold', 18)
        canvas.setFillColor(colors.HexColor('#a8c8f0'))
        canvas.drawString(14*mm, y_titulo - 16*mm, periodo_label)

        # Empresa
        canvas.setFont('Helvetica', 13)
        canvas.setFillColor(colors.HexColor('#d0e4f8'))
        canvas.drawString(14*mm, y_titulo - 28*mm, empresa_nome)

        # Data de geração
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(colors.HexColor('#8ab0d0'))
        canvas.drawString(14*mm, y_titulo - 40*mm,
                          f'Gerado em {br_now().strftime("%d/%m/%Y")}')

        # Faixa inferior azul escura com ícones e assinaturas
        faixa_h = 48*mm
        canvas.setFillColor(colors.HexColor('#091d4a'))
        canvas.rect(0, 0, W, faixa_h, fill=1, stroke=0)

        # Ícones e labels de seção (estilo referência)
        icones = [
            ('▲', 'DESEMPENHO\nOPERACIONAL', 18*mm),
            ('◉', 'QUALIDADE\nDA OPERAÇÃO', 72*mm),
            ('⚙', 'EFICIÊNCIA E\nCONTROLE', 126*mm),
        ]
        for ico, label, x in icones:
            canvas.setFont('Helvetica', 16)
            canvas.setFillColor(BRANCO)
            canvas.drawString(x, 30*mm, ico)
            canvas.setFont('Helvetica', 7)
            canvas.setFillColor(colors.HexColor('#8ab0d0'))
            for i, linha in enumerate(label.split('\n')):
                canvas.drawString(x + 8*mm, 30*mm - i * 8, linha)

        # Campos de assinatura
        assin_y = 10*mm
        assin_labels = [
            (cfg_pdf.get('assinatura_esquerda_label') or empresa_nome, 20*mm),
            (cfg_pdf.get('assinatura_direita_label') or 'SAAE', 110*mm),
        ]
        canvas.setLineWidth(0.5)
        canvas.setStrokeColor(colors.HexColor('#3a5a9a'))
        for label, x in assin_labels:
            canvas.line(x, assin_y + 8*mm, x + 65*mm, assin_y + 8*mm)
            canvas.setFont('Helvetica', 7)
            canvas.setFillColor(colors.HexColor('#8ab0d0'))
            canvas.drawString(x, assin_y + 3*mm, f'ASSINATURA {label.upper()}')

        # Slogan (canto inferior direito)
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(BRANCO)
        canvas.drawRightString(W - 14*mm, 22*mm, 'Cada gota')
        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(VERDE)
        canvas.drawRightString(W - 14*mm, 13*mm, 'faz a diferença.')

        canvas.restoreState()

    def _on_page_content(canvas, doc):
        """Cabeçalho e rodapé em todas as páginas de conteúdo."""
        canvas.saveState()

        # Cabeçalho
        canvas.setFillColor(AZUL_ESCURO)
        canvas.rect(0, H - 14*mm, W, 14*mm, fill=1, stroke=0)

        # Logo pequena no cabeçalho
        if logo_esq and Path(str(logo_esq)).exists():
            try:
                canvas.drawImage(str(logo_esq), 8*mm, H - 12*mm,
                                 width=20*mm, height=10*mm,
                                 preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(BRANCO)
        canvas.drawCentredString(W/2, H - 9*mm, f'IRIS — {tipo_label}')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#a8c8f0'))
        canvas.drawRightString(W - 8*mm, H - 9*mm, periodo_label)

        # Linha separadora
        canvas.setStrokeColor(colors.HexColor('#c5d5ea'))
        canvas.setLineWidth(0.3)
        canvas.line(8*mm, H - 15*mm, W - 8*mm, H - 15*mm)

        # Rodapé
        canvas.setFillColor(colors.HexColor('#f5f8fc'))
        canvas.rect(0, 0, W, 10*mm, fill=1, stroke=0)
        canvas.setStrokeColor(colors.HexColor('#c5d5ea'))
        canvas.setLineWidth(0.3)
        canvas.line(8*mm, 10*mm, W - 8*mm, 10*mm)
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(CINZA)
        canvas.drawString(8*mm, 3.5*mm,
                          f'IRIS Sistema de Gestão • {empresa_nome} • {br_now().strftime("%d/%m/%Y")}')
        canvas.drawRightString(W - 8*mm, 3.5*mm, f'Página {doc.page}')

        canvas.restoreState()

    # ── CONSTRUÇÃO DO CONTEÚDO ────────────────────────────────────────────
    elems_capa = [PageBreak()]  # A capa é desenhada no canvas, não em flowables

    # KPIs — bloco de indicadores
    os_total = ctx.get('os_total', 0)
    finalizadas_n = sum(1 for r in ctx.get('os_rows', []) if str(r.get('finalizada') or '').lower() == 'sim')
    taxa_conclusao = f"{round(finalizadas_n/os_total*100,1)}%" if os_total else "—"
    atrasadas_n = sum(1 for r in ctx.get('os_rows', []) if os_is_overdue(r))

    kpi_data = [[
        kpi_card(str(os_total), 'O.S. no período'),
        kpi_card(taxa_conclusao, 'Taxa de conclusão', cor_valor=VERDE),
        kpi_card(br_money(ctx.get('gasto_realizado_total', 0)), 'Gasto total'),
        kpi_card(br_money(ctx.get('pagamentos_total', 0)), 'Pagamentos'),
        kpi_card(br_money(ctx.get('combustivel_total', 0)), 'Combustível'),
    ]]
    kpi_tbl = Table(kpi_data, colWidths=[34*mm]*5)
    kpi_tbl.setStyle(TableStyle([
        ('LEFTPADDING', (0,0), (-1,-1), 1),
        ('RIGHTPADDING', (0,0), (-1,-1), 1),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))

    elems_content = [
        Spacer(1, 5*mm),
        Paragraph(f'{tipo_label} — {periodo_label}', st('PageTitle',
            fontName='Helvetica-Bold', fontSize=16, textColor=AZUL_ESCURO,
            spaceAfter=3*mm, leading=20)),
        Paragraph(empresa_nome, st('SubTitle',
            fontName='Helvetica', fontSize=11, textColor=CINZA,
            spaceAfter=5*mm, leading=14)),
        HRFlowable(width='100%', thickness=1.5, color=AZUL_ESCURO, spaceAfter=5*mm),
        kpi_tbl,
        Spacer(1, 6*mm),
    ]

    # Análise da IA
    if texto_ia:
        elems_content.extend(parse_ai_text(texto_ia))
    else:
        elems_content.append(Paragraph('Análise do período', st_h1))
        elems_content.append(Paragraph(
            f'O período {periodo_label} registrou {os_total} ordens de serviço, '
            f'com gasto total de {br_money(ctx.get("gasto_realizado_total", 0))}.',
            st_body))

    elems_content.append(Spacer(1, 8*mm))

    # ── TABELAS DE DADOS ──────────────────────────────────────────────────
    # Sistemas e O.S.
    if ctx.get('by_system_os'):
        elems_content.append(PageBreak())
        elems_content.append(Paragraph('DADOS: SISTEMAS E ORDENS DE SERVIÇO', st_h1))
        elems_content.append(HRFlowable(width='100%', thickness=1.5,
                                         color=AZUL_ESCURO, spaceAfter=4*mm))
        comp_map = dict(ctx.get('component_by_system', []))

        # Monta detalhamento de componentes por sistema
        comp_detail = {}
        for r in ctx.get('os_rows', []):
            if str(r.get('troca_componentes') or '').lower() == 'sim':
                s = (r.get('sistema') or 'Não informado').strip()
                desc = (r.get('componentes_descricao') or r.get('componentes') or '').strip()
                if desc:
                    comp_detail.setdefault(s, [])
                    if desc not in comp_detail[s]:
                        comp_detail[s].append(desc[:50])

        rows_sys = []
        for sys, qtd in ctx['by_system_os']:
            trocas = comp_map.get(sys, 0)
            detalhes = '; '.join(comp_detail.get(sys, [])) or '—'
            rows_sys.append([sys[:45], str(qtd), str(trocas), detalhes[:60]])

        elems_content.append(make_table(
            ['Sistema', 'O.S.', 'Trocas', 'Componentes trocados'],
            rows_sys,
            col_widths=[62*mm, 15*mm, 15*mm, 78*mm]
        ))

    # Equipamentos mais acionados
    if ctx.get('by_unit_os'):
        elems_content.append(Spacer(1, 8*mm))
        elems_content.append(Paragraph('EQUIPAMENTOS MAIS ACIONADOS', st_h2))
        rows_unit = []
        for unit, qtd in ctx['by_unit_os'][:20]:
            perc = f"{round(qtd/os_total*100,1)}%" if os_total else "—"
            rows_unit.append([unit[:60], str(qtd), perc])
        elems_content.append(make_table(
            ['Equipamento / Unidade', 'Ocorrências', '% do total'],
            rows_unit,
            col_widths=[110*mm, 30*mm, 30*mm]
        ))

    # Pagamentos — TODOS
    pags = ctx.get('pagamentos', [])
    if pags:
        elems_content.append(PageBreak())
        elems_content.append(Paragraph('DADOS: FORNECEDORES E PAGAMENTOS', st_h1))
        elems_content.append(HRFlowable(width='100%', thickness=1.5,
                                         color=AZUL_ESCURO, spaceAfter=4*mm))

        # Totais por fornecedor
        por_forn = {}
        for p in pags:
            f = (p.get('fornecedor') or 'Não informado').strip()
            por_forn[f] = por_forn.get(f, 0) + _iris_parse_br_float(p.get('valor'))

        rows_forn = []
        total_geral = sum(por_forn.values())
        for forn, val in sorted(por_forn.items(), key=lambda x: x[1], reverse=True):
            perc = f"{round(val/total_geral*100,1)}%" if total_geral else "—"
            rows_forn.append([forn[:50], br_money(val), perc])
        elems_content.append(Paragraph('Investimentos por Fornecedor', st_h2))
        elems_content.append(make_table(
            ['Fornecedor', 'Valor total', '% do total'],
            rows_forn,
            col_widths=[100*mm, 40*mm, 30*mm]
        ))

    # Pagamentos pendentes
    abertos = ctx.get('pagamentos_abertos_rows', [])
    if abertos:
        elems_content.append(Spacer(1, 8*mm))
        elems_content.append(Paragraph(
            f'Pagamentos Pendentes ({len(abertos)} lançamentos — {br_money(ctx.get("pagamentos_aberto",0))})',
            st_h2))
        rows_pend = []
        for p in abertos:
            forn = (p.get('fornecedor') or 'Sem fornecedor').strip()[:35]
            desc = (p.get('descricao_servico') or '').strip()[:50]
            val = br_money(_iris_parse_br_float(p.get('valor')))
            mes = p.get('pagamento_mes') or ''
            rows_pend.append([forn, desc, val, mes])
        elems_content.append(make_table(
            ['Fornecedor', 'Descrição', 'Valor', 'Mês'],
            rows_pend,
            col_widths=[50*mm, 70*mm, 30*mm, 20*mm]
        ))

    # Combustível
    comb_rows = ctx.get('combustivel_rows', [])
    if comb_rows:
        elems_content.append(Spacer(1, 8*mm))
        elems_content.append(Paragraph('Combustível por Motorista', st_h2))
        por_mot = {}
        for r in comb_rows:
            m = (r.get('motorista') or 'Não informado').strip()
            por_mot[m] = por_mot.get(m, 0) + _iris_parse_br_float(r.get('custo'))
        total_comb = sum(por_mot.values())
        rows_comb = []
        for mot, val in sorted(por_mot.items(), key=lambda x: x[1], reverse=True):
            perc = f"{round(val/total_comb*100,1)}%" if total_comb else "—"
            rows_comb.append([mot, br_money(val), perc])
        elems_content.append(make_table(
            ['Motorista / Veículo', 'Total combustível', '%'],
            rows_comb,
            col_widths=[90*mm, 50*mm, 30*mm]
        ))

    # ── BUILD DO PDF ──────────────────────────────────────────────────────
    # Página 1 = capa (sem margens, desenhada no canvas)
    # Página 2+ = conteúdo com margens e cabeçalho/rodapé

    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    class IrisDocTemplate(BaseDocTemplate):
        def __init__(self, filename, **kwargs):
            BaseDocTemplate.__init__(self, filename, **kwargs)
            # Template da capa (sem margem, sem cabeçalho)
            frame_capa = Frame(0, 0, W, H, leftPadding=0, rightPadding=0,
                               topPadding=0, bottomPadding=0, id='capa')
            # Template do conteúdo
            frame_content = Frame(14*mm, 12*mm, W - 28*mm, H - 28*mm,
                                  leftPadding=0, rightPadding=0,
                                  topPadding=0, bottomPadding=0, id='content')
            self.addPageTemplates([
                PageTemplate(id='Capa', frames=[frame_capa], onPage=_on_capa),
                PageTemplate(id='Content', frames=[frame_content], onPage=_on_page_content),
            ])

    doc = IrisDocTemplate(str(out))

    # Todos os elementos: primeiro a capa (PageBreak muda para Content), depois conteúdo
    from reportlab.platypus import NextPageTemplate
    all_elems = [
        NextPageTemplate('Content'),
        PageBreak(),
    ] + elems_content

    doc.build(all_elems)

    # Upload Supabase
    # URL sem url_for — funciona dentro e fora de request (worker background)
    _base = (os.environ.get('PUBLIC_BASE_URL') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
    arquivo_url = f'{_base}/static/exports/{out.name}' if _base else f'/static/exports/{out.name}'
    if upload_supabase and SUPABASE_STORAGE_KEY:
        try:
            folder = company_folder_name(current_company_id())
            storage_path = f'empresas/{folder}/pdfs/{out.name}'
            arquivo_url = _upload_pdf_bytes_to_supabase(out.read_bytes(), storage_path)
        except Exception as exc:
            print(f'Upload PDF IA para Supabase falhou: {exc}')

    return out, arquivo_url


def _iris_simple_bar_drawing(title, data, color=colors.HexColor('#3f8edb'), width=170*mm, height=70*mm, max_items=6):
    from reportlab.graphics.shapes import Drawing, Rect, String
    d = Drawing(width, height)
    d.add(String(0, height-12, title, fontName='Helvetica-Bold', fontSize=9, fillColor=colors.HexColor('#0b2d4d')))
    data = data[:max_items]
    if not data:
        d.add(String(8, height/2, 'Sem dados no recorte', fontSize=8, fillColor=colors.HexColor('#6b7a90')))
        return d
    maxv = max(float(v or 0) for _, v in data) or 1
    y = height - 26
    label_w = 62*mm
    bar_w = width - label_w - 14*mm
    for label, val in data:
        label = str(label)[:28]
        v = float(val or 0)
        d.add(String(0, y+3, label, fontSize=6.5, fillColor=colors.HexColor('#27405f')))
        bw = max(1, (v/maxv)*bar_w)
        d.add(Rect(label_w, y, bw, 4.3*mm, fillColor=color, strokeColor=None))
        d.add(String(label_w+bw+2, y+2, f'{int(v) if v.is_integer() else v:.0f}', fontSize=6.5, fillColor=colors.HexColor('#0b2d4d')))
        y -= 8*mm
        if y < 2*mm: break
    return d



def _iris_make_monthly_pdf(month_ref):
    ctx = _iris_collect_context(month_ref)
    tmp = BASE_DIR / 'static' / 'exports'
    tmp.mkdir(parents=True, exist_ok=True)
    empresa = current_company() or {}
    empresa_slug = slugify_company_name(empresa.get('nome') or 'unidade')
    out = tmp / f"relatorio_mensal_{empresa_slug}_{(month_ref or 'todos').replace('/','-')}.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle('irisTitle', parent=styles['Title'], fontSize=22, textColor=colors.HexColor('#0b2d4d'), spaceAfter=8, alignment=1)
    h2 = ParagraphStyle('irisH2', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#0b2d4d'), spaceBefore=10, spaceAfter=6)
    normal = ParagraphStyle('irisNormal', parent=styles['BodyText'], fontSize=8.5, leading=11, textColor=colors.HexColor('#263b54'))
    elems = []
    logo = BASE_DIR / 'static' / 'logo_sidebar.png'
    if logo.exists():
        elems.append(RLImage(str(logo), width=24*mm, height=24*mm))
    empresa_nome = (current_company() or {}).get('nome') or 'Unidade ativa'
    elems += [Paragraph('IRIS', title), Paragraph(f'{empresa_nome} • Relatório mensal • {month_ref or "Todos os períodos"}', ParagraphStyle('sub', parent=normal, alignment=1, fontSize=10)), Spacer(1,8*mm)]

    top_cost = ctx['by_system_cost'][0] if ctx['by_system_cost'] else ('Sem dados', 0)
    top_os = ctx['by_system_os'][0] if ctx['by_system_os'] else ('Sem dados', 0)
    top_unit = ctx['by_unit_os'][0] if ctx['by_unit_os'] else ('Sem dados', 0)
    obs = [
        f"Total de O.S. no recorte: <b>{ctx['os_total']}</b>.",
        f"Gasto financeiro: pagamentos <b>{br_money(ctx['pagamentos_total'])}</b> + combustível <b>{br_money(ctx['combustivel_total'])}</b> = <b>{br_money(ctx['gasto_realizado_total'])}</b>.",
        f"Pagamentos em aberto: <b>{br_money(ctx['pagamentos_aberto'])}</b>.",
        f"Sistema que mais gerou O.S.: <b>{top_os[0]}</b> com <b>{top_os[1]}</b> O.S.",
        f"Local/unidade com mais incidentes: <b>{top_unit[0]}</b> com <b>{top_unit[1]}</b> ocorrência(s).",
    ]
    elems.append(Paragraph('Observações executivas', h2))
    for o in obs:
        elems.append(Paragraph('• ' + o, normal))
    elems.append(Spacer(1,5*mm))

    cards = [
        ['O.S.', str(ctx['os_total'])],
        ['Gasto total', br_money(ctx['gasto_realizado_total'])],
        ['Pagamentos', br_money(ctx['pagamentos_total'])],
        ['Combustível', br_money(ctx['combustivel_total'])],
    ]
    tbl = Table(cards, colWidths=[35*mm, 45*mm], hAlign='LEFT')
    tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f2f7ff')),
        ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#c9d8ea')),
        ('INNERGRID',(0,0),(-1,-1),0.25,colors.HexColor('#dbe6f3')),
        ('FONT',(0,0),(-1,-1),'Helvetica-Bold'),
        ('TEXTCOLOR',(0,0),(-1,-1),colors.HexColor('#0b2d4d')),
        ('PADDING',(0,0),(-1,-1),6),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1,7*mm))

    g1 = _iris_simple_bar_drawing('Locais/unidades com mais incidentes (O.S.)', ctx['by_unit_os'], colors.HexColor('#f59e0b'), width=82*mm, height=62*mm)
    g2 = _iris_simple_bar_drawing('Sistemas com mais O.S.', ctx['by_system_os'], colors.HexColor('#6d5dfc'), width=82*mm, height=62*mm)
    g3 = _iris_simple_bar_drawing('Sistemas com troca de componentes', ctx['component_by_system'], colors.HexColor('#16a34a'), width=82*mm, height=62*mm)
    status_pay = [('Pago', len([p for p in ctx['pagamentos'] if _iris_payment_status(p)=='Pago'])), ('Em aberto', len(ctx['pagamentos_abertos_rows']))]
    g4 = _iris_simple_bar_drawing('Status de pagamento', status_pay, colors.HexColor('#ef4444'), width=82*mm, height=62*mm)
    grid = Table([[g1,g2],[g3,g4]], colWidths=[88*mm,88*mm], rowHeights=[66*mm,66*mm])
    grid.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),0)]))
    elems.append(Paragraph('Gráficos do período', h2))
    elems.append(grid)
    elems.append(PageBreak())

    elems.append(Paragraph('Pagamentos em aberto', h2))
    open_rows = ctx['pagamentos_abertos_rows'][:40]
    data = [['ID','Sistema','Fornecedor','Descrição','Valor']]
    for r in open_rows:
        data.append([str(r.get('id','')), str(r.get('sistema',''))[:22], str(r.get('fornecedor',''))[:22], str(r.get('descricao_servico',''))[:42], br_money(_iris_parse_br_float(r.get('valor')))])
    if len(data)==1: data.append(['—','—','—','Nenhum pagamento em aberto','—'])
    t = Table(data, colWidths=[12*mm,32*mm,32*mm,70*mm,28*mm], repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf3ff')),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#b9c8d8')),('FONT',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),6.5),('VALIGN',(0,0),(-1,-1),'TOP')]))
    elems.append(t)
    doc.build(elems)
    return out



def _iris_make_payments_excel(month_ref=''):
    ctx = _iris_collect_context(month_ref)
    out_dir = BASE_DIR / 'static' / 'exports'
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"pagamentos_iris_{(month_ref or 'todos').replace('/','-')}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = 'Pagamentos'
    ws.append(['ID','Sistema','Equipamento','Fornecedor','Descrição','Status','Valor','Mês','Pedido','Documento'])
    for r in ctx['pagamentos']:
        ws.append([r.get('id'), r.get('sistema'), r.get('equipamento'), r.get('fornecedor'), r.get('descricao_servico'), _iris_payment_status(r), _iris_parse_br_float(r.get('valor')), r.get('pagamento_mes'), r.get('sc_pedido'), r.get('numero_documento')])
    wb.save(out)
    return out

