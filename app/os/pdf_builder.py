"""Montagem do PDF de O.S. (dia/mês) e exportações tabulares."""
import io
import json
import os
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.os.pdf_common import (
    PDF_MAX_IMAGES_PER_OS,
    PDF_MONTH_MAX_IMAGES_PER_OS,
    _bg,
    company_where,
    current_company,
    current_company_id,
    query_all,
    query_one,
    select_existing_columns,
    table_columns,
)
from app.os.pdf_support import (
    _draw_pdf_header,
    _img_square_rlimage,
    _pdf_cache_get,
    _pdf_cache_set,
    _pdf_clean_row,
    _pdf_collect_hist_dates,
    _pdf_collect_os_image_paths,
    _pdf_datetime_label,
    _pdf_fim_label,
    _pdf_hist_needs_detail_rows,
    _pdf_historico_for_display,
    _pdf_para_text,
    _pdf_safe_text,
    _pdf_time_label,
    _prefetch_os_images_parallel,
)
from app.os.services import attach_os_display_numbers
from app.shared.formatters import elapsed_label, parse_br_date
from app.shared.months import normalize_month_reference
from app.shared.rows import row_get_value, row_matches_month, row_to_dict
from app.storage import company_identity_dir, company_identity_file, load_company_identity_config, sync_os_attachments


def _build_os_pdf(ordens, titulo='RDO - RELATÓRIO DIÁRIO', subtitulo=''):
    if ordens:
        workers = int(os.getenv('PDF_PREFETCH_WORKERS', '8') or 8)
        _prefetch_os_images_parallel(ordens, max_workers=max(1, workers))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=24*mm, bottomMargin=25*mm)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle('normal', parent=styles['Normal'], fontSize=9, leading=11, leftIndent=0, firstLineIndent=0, spaceBefore=0, spaceAfter=0)
    cell_para = ParagraphStyle('cell_para', parent=normal, wordWrap='CJK')
    title_style = ParagraphStyle('title', parent=styles['Heading1'], fontSize=14, alignment=1, leading=16, spaceAfter=0)
    subtitle_style = ParagraphStyle('subtitle', parent=styles['Normal'], fontSize=9, alignment=1, textColor=colors.HexColor('#44546a'), leading=11, spaceAfter=0)
    small = ParagraphStyle('small', parent=styles['Normal'], fontSize=8.5, leading=10)
    elems = []
    def _assinar(canvas, _doc):
        canvas.saveState()
        y = 18 * mm
        left_x = 40 * mm
        right_x = 120 * mm
        line_w = 55 * mm
        canvas.setLineWidth(0.5)
        canvas.line(left_x, y, left_x + line_w, y)
        canvas.line(right_x, y, right_x + line_w, y)

        cfg_pdf = load_company_identity_config(current_company_id())
        assinatura_path = company_identity_file('assinatura.png', current_company_id())
        # Se arquivo não existe no disco (Render restart), tenta restaurar do base64 salvo no config
        if not assinatura_path and cfg_pdf.get('assinatura_b64'):
            try:
                import base64 as _b64
                b64data = cfg_pdf['assinatura_b64']
                if ',' in b64data:
                    b64data = b64data.split(',', 1)[1]
                img_bytes = _b64.b64decode(b64data)
                # Restaura no disco para uso futuro
                dest = company_identity_dir(current_company_id()) / 'assinatura.png'
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(img_bytes)
                assinatura_path = dest
            except Exception as exc:
                print('Falha ao restaurar assinatura do base64:', exc)
        if assinatura_path:
            try:
                img = ImageReader(str(assinatura_path))
                iw, ih = img.getSize()
                if iw and ih:
                    target_w = 46 * mm
                    target_h = target_w * (ih / iw)
                    if target_h > 12 * mm:
                        target_h = 12 * mm
                        target_w = target_h * (iw / ih)
                    draw_x = left_x + (line_w - target_w) / 2
                    draw_y = y + 0.2 * mm
                    canvas.drawImage(
                        str(assinatura_path),
                        draw_x,
                        draw_y,
                        width=target_w,
                        height=target_h,
                        preserveAspectRatio=True,
                        mask='auto'
                    )
            except Exception:
                pass

        canvas.setFont('Helvetica', 9)
        left_label = _pdf_safe_text(cfg_pdf.get('assinatura_esquerda_label') or '')
        right_label = _pdf_safe_text(cfg_pdf.get('assinatura_direita_label') or 'Fiscalização SAAE')
        if left_label:
            canvas.drawCentredString(left_x + line_w / 2, y - 12, left_label)
        if right_label:
            canvas.drawCentredString(right_x + line_w / 2, y - 12, right_label)
        canvas.restoreState()

    def _os_sort_key_pdf(item):
        try:
            data_txt = item['data'] if hasattr(item, 'keys') and 'data' in item.keys() else ''
        except Exception:
            data_txt = ''
        parsed = parse_br_date(str(data_txt or '')) or datetime.min
        try:
            rid_raw = item['id'] if hasattr(item, 'keys') and 'id' in item.keys() else 0
            rid = int(rid_raw or 0)
        except Exception:
            rid = 0
        return (parsed, rid)

    numbered_ordens = [_pdf_clean_row(x) for x in attach_os_display_numbers(sorted(ordens, key=_os_sort_key_pdf))]
    for idx, r in enumerate(numbered_ordens):
        if idx:
            elems.append(PageBreak())

        elems.append(Spacer(1, 2*mm))

        cfg_pdf = load_company_identity_config(current_company_id())
        empresa_pdf = current_company() or {}
        cabe_esq = [
            ['CLIENTE', _pdf_safe_text(cfg_pdf.get('cliente') or '')],
            ['CONTRATADA', _pdf_safe_text(cfg_pdf.get('contratada') or empresa_pdf.get('nome') or '')],
            ['CNPJ', _pdf_safe_text(cfg_pdf.get('cnpj') or '')],
            ['CIDADE', _pdf_safe_text(cfg_pdf.get('cidade') or empresa_pdf.get('cidade') or '')],
            ['RESPONSÁVEL', _pdf_safe_text(cfg_pdf.get('responsavel') or '')],
        ]
        terceiro = (row_get_value(r, 'quem_foi_terceiro', '') or '').strip() if str(row_get_value(r, 'teve_terceiro', '') or '').lower() == 'sim' else 'Não houve'
        data_os = _pdf_safe_text(row_get_value(r, 'data', '') or '')
        cabe_dir = [
            ['EQUIPE TERCEIRA:', ''],
            [_pdf_safe_text(terceiro), ''],
            ['', ''],
            ['DATA:', ''],
            [data_os, ''],
        ]
        left_tbl = Table(cabe_esq, colWidths=[28*mm, 106*mm])
        left_tbl.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.35, colors.HexColor('#9aa7ba')),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f7f9fc')),
            ('BACKGROUND', (1,0), (1,-1), colors.white),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        right_tbl = Table(cabe_dir, colWidths=[38*mm, 24*mm])
        right_tbl.setStyle(TableStyle([
            ('SPAN', (0,0), (1,0)),
            ('SPAN', (0,1), (1,1)),
            ('SPAN', (0,2), (1,2)),
            ('SPAN', (0,4), (1,4)),
            ('FONTNAME', (0,0), (1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,3), (0,3), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.35, colors.HexColor('#9aa7ba')),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#dbe9fb')),
            ('BACKGROUND', (0,1), (-1,-1), colors.white),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        head_wrap = Table([[left_tbl, right_tbl]], colWidths=[134*mm, 62*mm])
        head_wrap.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        elems.append(head_wrap)
        elems.append(Spacer(1, 7*mm))

        finalizada_pdf = (r.get('finalizada') or ('Sim' if str(r.get('status') or '').strip().lower() == 'finalizada' else 'Não')).strip().title()
        _finalizada_sim = str(finalizada_pdf).strip().lower() == 'sim'

        try:
            _hist = _pdf_historico_for_display(
                json.loads(r.get('historico_pausas') or '[]'),
                finalizada=_finalizada_sim,
            )
        except Exception:
            _hist = []

        os_data = _pdf_safe_text(row_get_value(r, 'data', '') or '')
        _hist_multiday = len(_pdf_collect_hist_dates(
            _hist, r.get('data_inicio'), r.get('data_fim'), os_data,
        )) > 1
        _show_hist = _pdf_hist_needs_detail_rows(_hist, _hist_multiday)
        _di_label = _pdf_time_label(r.get('data_inicio'), _hist)
        _df_label = _pdf_fim_label(
            r.get('data_fim'),
            _hist,
            finalizada=_finalizada_sim,
        )
        _tempo = elapsed_label(r.get('data_inicio'), r.get('data_fim'), r.get('acumulado_minutos') or 0, running=False) or '-'

        info = [
            ['O.S.', _pdf_safe_text(r.get('numero_os') or r.get('id') or ''), 'Sistema', _pdf_safe_text(row_get_value(r, 'sistema', '') or '')],
            ['Equipamento', _pdf_safe_text(row_get_value(r, 'equipamento', '') or row_get_value(r, 'ativo_nome', '') or ''), 'Finalizada', _pdf_safe_text(finalizada_pdf)],
            ['Criticidade', _pdf_safe_text(row_get_value(r, 'criticidade', '') or ''), 'Responsável', _pdf_safe_text(row_get_value(r, 'responsavel', '') or '')],
            ['Início', _pdf_safe_text(_di_label), 'Fim', _pdf_safe_text(_df_label)],
        ]
        _motivo_span_rows = []
        _motivo_no_hist = True

        if _show_hist:
            for _ev in _hist:
                _acao = str(_ev.get('acao') or '').strip().lower()
                _quando = _pdf_datetime_label(_ev.get('quando'), os_date=os_data, multiday=_hist_multiday)
                _motivo_ev = _pdf_safe_text(_ev.get('motivo') or '')
                if _acao == 'iniciado':
                    info.append(['Iniciado em', _quando, '', ''])
                elif _acao == 'pausado':
                    info.append(['Pausado em', _quando, '', ''])
                    _motivo_show = _motivo_ev or _pdf_safe_text((r.get('motivo_pausa') or '').strip())
                    if _motivo_show:
                        _motivo_no_hist = False
                        info.append([
                            'Motivo',
                            Paragraph(_pdf_para_text(_motivo_show, max_len=800), cell_para),
                            '',
                            '',
                        ])
                        _motivo_span_rows.append(len(info) - 1)
                elif _acao == 'retomado':
                    info.append(['Retomado em', _quando, '', ''])
                elif _acao == 'finalizado':
                    info.append(['Finalizado em', _quando, 'Tempo total', _tempo])

            _has_finalizado_hist = any(str(e.get('acao', '')).lower() == 'finalizado' for e in _hist)
            if not _has_finalizado_hist and r.get('acumulado_minutos') and _finalizada_sim:
                info.append(['Tempo total', _tempo, '', ''])

        info_tbl = Table(info, colWidths=[30*mm, 68*mm, 30*mm, 68*mm])
        _info_style = [
            ('GRID', (0,0), (-1,-1), 0.35, colors.HexColor('#9aa7ba')),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f7f9fc')),
            ('BACKGROUND', (2,0), (2,-1), colors.HexColor('#f7f9fc')),
            ('BACKGROUND', (1,0), (1,-1), colors.white),
            ('BACKGROUND', (3,0), (3,-1), colors.white),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]
        for row_idx in _motivo_span_rows:
            _info_style.append(('SPAN', (1, row_idx), (3, row_idx)))
            _info_style.append(('VALIGN', (0, row_idx), (-1, row_idx), 'TOP'))
        # Destaca linha de pausa em amarelo claro
        for i, row_info in enumerate(info):
            if i >= 4:  # linhas do histórico
                _acao_row = str(row_info[0]).lower()
                if isinstance(row_info[0], Paragraph):
                    _acao_row = ''
                if 'iniciado' in _acao_row:
                    _info_style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#ecfdf5')))
                elif 'pausado' in _acao_row:
                    _info_style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#fffbeb')))
                elif 'motivo' in _acao_row:
                    _info_style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#fffbeb')))
                elif 'retomado' in _acao_row:
                    _info_style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#f0fdf4')))
                elif 'finalizado' in _acao_row:
                    _info_style.append(('BACKGROUND', (0,i), (-1,i), colors.HexColor('#eff6ff')))

        info_tbl.setStyle(TableStyle(_info_style))
        elems.append(info_tbl)
        elems.append(Spacer(1, 6*mm))

        def _box_section(title, content, min_height_mm=10):
            body = Paragraph(_pdf_para_text(content, max_len=1800), normal)
            safe_title = _pdf_para_text(title, max_len=80)
            box = Table(
                [[Paragraph(f"<b>{safe_title}</b>", normal)], [body]],
                colWidths=[196*mm]
            )
            box.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 0.35, colors.HexColor('#9aa7ba')),
                ('BACKGROUND', (0,0), (-1,0), colors.white),
                ('BACKGROUND', (0,1), (-1,-1), colors.white),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('TOPPADDING', (0,0), (0,0), 4),
                ('BOTTOMPADDING', (0,0), (0,0), 2),
                ('TOPPADDING', (0,1), (0,1), 2),
                ('BOTTOMPADDING', (0,1), (0,1), min_height_mm * mm / 2.834645669),
            ]))
            return box

        # Motivo da pausa — só se não entrou no histórico da tabela acima
        _motivo_pausa = (r.get('motivo_pausa') or '').strip()
        if _motivo_pausa and _motivo_no_hist:
            elems.append(_box_section('Motivo da pausa:', _motivo_pausa, min_height_mm=10))
            elems.append(Spacer(1, 4*mm))

        elems.append(_box_section('Descrição:', r.get('descricao') or '', min_height_mm=12))
        elems.append(Spacer(1, 4*mm))
        elems.append(_box_section('Serviço executado:', r.get('servico_executado') or '', min_height_mm=20))
        elems.append(Spacer(1, 10*mm))

        # Coleta robusta de fotos: `imagens` oficial + campos legados/alternativos.
        paths = _pdf_collect_os_image_paths(r)

        # Em tarefas de PDF mensal em background, a Vi pediu TODAS as fotos.
        # Não apagamos nada: apenas comprimimos cada imagem temporariamente para caber no PDF.
        force_all_imgs = bool(getattr(_bg(), 'pdf_all_images', False))
        if force_all_imgs:
            paths = list(paths or [])
        else:
            if 'MENSAL' in str(titulo).upper():
                max_imgs = max(0, int(os.getenv('PDF_MONTH_MAX_IMAGES_PER_OS', str(PDF_MONTH_MAX_IMAGES_PER_OS)) or PDF_MONTH_MAX_IMAGES_PER_OS))
            else:
                max_imgs = max(0, int(os.getenv('PDF_MAX_IMAGES_PER_OS', str(PDF_MAX_IMAGES_PER_OS)) or PDF_MAX_IMAGES_PER_OS))
            if max_imgs:
                paths = list(paths or [])[:max_imgs]
            else:
                paths = []
        imgs = [im for p in paths if (im := _img_square_rlimage(p))]
        if imgs:
            fotos_por_linha = 3
            largura_foto = 54 * mm
            espaco_entre_fotos = 9 * mm
            col_widths = [largura_foto, espaco_entre_fotos, largura_foto, espaco_entre_fotos, largura_foto]
            rows = []
            for inicio in range(0, len(imgs), fotos_por_linha):
                grupo = imgs[inicio:inicio + fotos_por_linha]
                row = []
                for i in range(fotos_por_linha):
                    row.append(grupo[i] if i < len(grupo) else '')
                    if i < fotos_por_linha - 1:
                        row.append('')
                rows.append(row)

            tbl = Table(rows, colWidths=col_widths, hAlign='CENTER', repeatRows=0)
            tbl.setStyle(TableStyle([
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOX', (0,0), (-1,-1), 0, colors.white),
                ('GRID', (0,0), (-1,-1), 0, colors.white),
            ]))
            elems.append(tbl)
        else:
            elems.append(Spacer(1, 55*mm))

        elems.append(Spacer(1, 20*mm))

    def _on_first_page(canvas, _doc):
        _draw_pdf_header(canvas, _doc, titulo, subtitulo)
        _assinar(canvas, _doc)

    def _on_later_pages(canvas, _doc):
        _draw_pdf_header(canvas, _doc, titulo, subtitulo)
        _assinar(canvas, _doc)

    doc.build(elems, onFirstPage=_on_first_page, onLaterPages=_on_later_pages)
    buf.seek(0)
    return buf


def table_pdf(title, headers, rows):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=24*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    heading = ParagraphStyle('pdf_heading', parent=styles['Heading2'], fontSize=13, leading=15, alignment=1, spaceAfter=4*mm)
    elems = [Paragraph(title, heading), Spacer(1, 2*mm)]
    data = [headers] + rows
    col_widths = [None] * len(headers)
    if len(headers) == 7:
        col_widths = [12*mm, 42*mm, 56*mm, 24*mm, 18*mm, 20*mm, 20*mm]
    tbl = Table(data, repeatRows=1, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#b8c7da')),
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4fb')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#1e3f66')),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),8),
        ('LEADING',(0,0),(-1,-1),10),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f9fbfe')]),
        ('TOPPADDING',(0,0),(-1,-1),6),
        ('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    elems.append(tbl)
    doc.build(elems, onFirstPage=lambda c,d: _draw_pdf_header(c,d,title), onLaterPages=lambda c,d: _draw_pdf_header(c,d,title))
    buf.seek(0)
    return buf


def excel_file(title, headers, rows):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = title[:31]; ws.append(headers)
    for row in rows: ws.append(list(row))
    buf = io.BytesIO(); wb.save(buf); buf.seek(0); return buf

def _build_os_pdf_mes_buffer(mes, include_all_images=False, use_cache=False):
    """Gera o PDF mensal em memória.

    include_all_images=True mantém todas as fotos no PDF mensal.
    As fotos NÃO são apagadas; só são reduzidas temporariamente dentro do PDF.
    """
    mes = (mes or '').strip()
    if not mes:
        raise ValueError('Informe o mês para gerar o relatório.')

    mes_norm = normalize_month_reference(mes) or mes
    cache_key = f"pdf:mes:{current_company_id()}:{mes_norm}:allimgs{1 if include_all_images else 0}"
    if use_cache:
        cached = _pdf_cache_get(cache_key)
        if cached:
            return cached, mes_norm

    existing = table_columns('os_ordens')
    desired = [
        'id', 'data', 'sistema', 'equipamento', 'ativo_nome', 'status', 'finalizada',
        'criticidade', 'responsavel', 'data_inicio', 'data_fim', 'descricao',
        'servico_executado', 'imagens', 'teve_terceiro', 'quem_foi_terceiro', 'empresa_id',
        'historico_pausas', 'motivo_pausa', 'acumulado_minutos',
    ]
    fields = select_existing_columns('os_ordens', desired, fallback='id')
    where_sql, params = company_where('os_ordens')
    params = list(params)

    if 'data' in existing and re.match(r'^\d{2}/\d{4}$', str(mes_norm)):
        where_sql += (' AND ' if where_sql else ' WHERE ')
        where_sql += "COALESCE(data,'') LIKE ?"
        params.append(f'%/{mes_norm}')

    # Background: sem limite artificial de O.S. para não cortar relatório mensal.
    sql = f"SELECT {fields} FROM os_ordens{where_sql} ORDER BY id ASC"
    rows = [row_to_dict(r) for r in query_all(sql, tuple(params))]

    # Fallback para datas fora do padrão.
    if not rows and 'data' in existing:
        where_sql2, params2 = company_where('os_ordens')
        sql = f"SELECT {fields} FROM os_ordens{where_sql2} ORDER BY id ASC"
        rows = [row_to_dict(r) for r in query_all(sql, tuple(list(params2)))]

    rows = [r for r in rows if row_matches_month(row_get_value(r, 'data', ''), month_ref=mes_norm)]
    if not rows:
        raise ValueError('Nenhuma O.S. encontrada para o mês informado.')

    rows_completas = []
    for r in rows:
        rid = row_get_value(r, 'id')
        full = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or dict(r)
        full = sync_os_attachments(full, persist_db=False)
        rows_completas.append(full)

    rows = attach_os_display_numbers(rows_completas)

    # Pré-baixa fotos em paralelo apenas se houver imagens habilitadas
    if PDF_MONTH_MAX_IMAGES_PER_OS > 0:
        try:
            _prefetch_os_images_parallel(rows, max_workers=3)
        except Exception as exc:
            print('PDF mensal: prefetch de imagens falhou (continuando sem cache):', exc)

    try:
        total_fotos_pdf = sum(len(_pdf_collect_os_image_paths(r)) for r in rows)
        print(f'PDF mensal {mes_norm}: {len(rows)} O.S. encontradas; {total_fotos_pdf} foto(s) candidatas para inserir.')
    except Exception as exc:
        print('PDF mensal: falha ao contar fotos candidatas:', exc)

    ctx = _bg()
    old_all_images = getattr(ctx, 'pdf_all_images', False)
    ctx.pdf_all_images = bool(include_all_images)
    try:
        pdf = _build_os_pdf(rows, titulo='RDO - RELATÓRIO MENSAL', subtitulo=f'Mês: {mes_norm}')
    finally:
        ctx.pdf_all_images = old_all_images

    if use_cache:
        pdf = _pdf_cache_set(cache_key, pdf)
    return pdf, mes_norm

