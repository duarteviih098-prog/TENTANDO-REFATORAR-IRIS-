"""PDF de O.S. — geração, cache e jobs em background."""
import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from app.auth import owned_by_current_company, user_has
from app.auth.decorators import is_mobile_request
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_money, br_now, elapsed_label, now_str, only_time_str, parse_br_date, parse_num, time_diff_minutes
from app.shared.months import normalize_month_reference
from app.shared.queries import fetch_sistemas_map, list_page, reset_sqlite_sequence_if_empty
from app.shared.rows import row_get_value, row_matches_month, row_to_dict
from app.storage import backup_company_data

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from PIL import Image as PILImage

from app.auth.decorators import require_permission
from app.os.services import attach_os_display_numbers
from app.storage import (
    _upload_pdf_bytes_to_supabase,
    company_folder_name,
    company_identity_dir,
    company_identity_file,
    load_company_identity_config,
    sync_os_attachments,
)
from app.storage.attachments import read_attachment_bytes_fast, resolve_os_upload_path, storage_or_local_response
from app.storage.paths import BASE_DIR, normalize_storage_path


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


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


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)



def _flask_app():
    from app.runtime import flask_app
    return flask_app()


def _bg():
    from app.runtime import BACKGROUND_COMPANY_CONTEXT
    return BACKGROUND_COMPANY_CONTEXT


# PDF PERFORMANCE
# ===============================
_PDF_IMAGE_CACHE = {}
_PDF_IMAGE_CACHE_LOCK = threading.Lock()
_PDF_BYTES_CACHE = {}
_PDF_CACHE_LOCK = threading.Lock()
PDF_CACHE_TTL_SECONDS = int(os.getenv('PDF_CACHE_TTL_SECONDS', '600') or 600)
PDF_IMAGE_TIMEOUT_SECONDS = int(os.getenv('PDF_IMAGE_TIMEOUT_SECONDS', '5') or 5)
PDF_IMAGE_SIZE_PX = int(os.getenv('PDF_IMAGE_SIZE_PX', '200') or 200)
PDF_MAX_IMAGES_PER_OS = int(os.getenv('PDF_MAX_IMAGES_PER_OS', '3') or 3)
PDF_MONTH_MAX_IMAGES_PER_OS = int(os.getenv('PDF_MONTH_MAX_IMAGES_PER_OS', '2') or 2)
PDF_MONTH_MAX_OS = int(os.getenv('PDF_MONTH_MAX_OS', '80') or 80)
PDF_MONTH_BATCH_SIZE = int(os.getenv('PDF_MONTH_BATCH_SIZE', '20') or 20)

def _pdf_safe_text(value, max_len=None):
    """Texto seguro para ReportLab/Helvetica.

    Evita crash do PDF com emoji, caracteres fora do WinAnsi e textos gigantes.
    Mantém acentos comuns em PT-BR.
    """
    if value is None:
        return ''
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    repl = {
        '\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2022': '-', '\u2026': '...',
        '\u00a0': ' ', '\ufe0f': '',
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    # Helvetica padrão do ReportLab não aceita emoji/símbolos fora do Latin-1.
    text = text.encode('latin-1', 'replace').decode('latin-1')
    text = text.replace('?', '')
    if max_len and len(text) > int(max_len):
        text = text[:int(max_len)] + '...'
    return text

def _pdf_para_text(value, max_len=None):
    text = _pdf_safe_text(value, max_len=max_len)
    text = (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
    return text.replace('\n', '<br/>') if text else '&nbsp;'

def _pdf_clean_row(row):
    """Limpa só campos textuais usados no PDF, sem alterar banco."""
    try:
        out = dict(row or {})
    except Exception:
        return row
    for key in ('sistema','equipamento','ativo_nome','status','finalizada','criticidade','responsavel',
                'descricao','servico_executado','teve_terceiro','quem_foi_terceiro','data','data_inicio','data_fim'):
        if key in out and not isinstance(out.get(key), (list, tuple, dict)):
            out[key] = _pdf_safe_text(out.get(key), max_len=2500 if key in ('descricao','servico_executado') else 220)
    return out

def _pdf_cache_get(key):
    now = time.time()
    with _PDF_CACHE_LOCK:
        item = _PDF_BYTES_CACHE.get(key)
        if item and now - item.get('ts', 0) < PDF_CACHE_TTL_SECONDS:
            return io.BytesIO(item['data'])
    return None

def _pdf_cache_set(key, pdf_buf):
    try:
        pos = pdf_buf.tell()
    except Exception:
        pos = 0
    try:
        pdf_buf.seek(0)
        data = pdf_buf.read()
        with _PDF_CACHE_LOCK:
            _PDF_BYTES_CACHE[key] = {'ts': time.time(), 'data': data}
        pdf_buf.seek(pos)
    except Exception:
        pass
    try:
        pdf_buf.seek(0)
    except Exception:
        pass
    return pdf_buf




def _pdf_jsonish_list(value):
    """Converte listas antigas/novas de anexos em lista real, sem quebrar strings em letras."""
    if value in (None, ''):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    raw = str(value or '').strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass
    # fallback para dados legados separados por ; ou quebra de linha
    if any(sep in raw for sep in (';', '\n', '|')):
        parts = re.split(r'[;\n|]+', raw)
        return [p.strip() for p in parts if p.strip()]
    return [raw]


def _pdf_item_to_path(item):
    """Extrai caminho/url de uma foto, aceitando string ou dict legado."""
    if not item:
        return ''
    if isinstance(item, dict):
        for key in ('path', 'url', 'src', 'href', 'storage_path', 'arquivo', 'file', 'filename', 'nome', 'name'):
            val = item.get(key)
            if val:
                return str(val).strip()
        return ''
    return str(item).strip()


def _pdf_looks_like_image_path(value):
    raw = str(value or '').strip()
    if not raw:
        return False
    low = raw.lower()
    if low.startswith('data:image/'):
        return True
    image_exts = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff')
    if any(low.split('?', 1)[0].endswith(ext) for ext in image_exts):
        return True
    # caminhos do Supabase/local usados no app
    return any(token in low for token in ('/os/', 'foto_os', 'campo_', 'storage/v1/object')) and not low.endswith('.pdf')


def _pdf_collect_os_image_paths(row):
    """Coleta fotos da O.S. de forma agressiva e compatível com dados antigos.

    Motivo: algumas O.S. antigas ou vindas do Campo podem ter fotos salvas em campos
    diferentes de `imagens`, ou como JSON string. O PDF mensal agora caça todos esses
    formatos antes de desistir.
    """
    try:
        data = dict(row or {})
    except Exception:
        data = {}

    candidates = []

    # Campo oficial.
    for item in _pdf_jsonish_list(data.get('imagens')):
        p = _pdf_item_to_path(item)
        if p:
            candidates.append(p)

    # Campos alternativos/legados comuns.
    possible_keys = (
        'imagem', 'foto', 'fotos', 'foto1', 'foto2', 'foto3', 'foto_1', 'foto_2', 'foto_3',
        'anexos', 'anexos_os', 'arquivos', 'attachments', 'attachments_os', 'evidencias',
        'evidencias_fotos', 'campo_fotos', 'campo_imagens', 'detalhes_json'
    )
    for key, val in data.items():
        key_low = str(key or '').lower()
        should_scan = key_low in possible_keys or any(tok in key_low for tok in ('foto', 'imagem', 'image', 'img', 'evidencia'))
        # não confundir orçamento/pdf financeiro com foto da O.S.
        if any(block in key_low for block in ('orcamento', 'orçamento', 'boleto', 'nf_', 'nota')):
            should_scan = False
        if not should_scan:
            continue
        for item in _pdf_jsonish_list(val):
            p = _pdf_item_to_path(item)
            if p:
                candidates.append(p)

    out, seen = [], set()
    for p in candidates:
        p = str(p or '').strip()
        if not p:
            continue
        if not _pdf_looks_like_image_path(p) and not p.startswith(('empresas/', 'static/uploads/', 'uploads/empresas/')):
            continue
        key = normalize_storage_path(p) if not p.startswith(('http://', 'https://')) else p
        if key not in seen:
            out.append(p)
            seen.add(key)
    return out

def _img_square_rlimage(path_str, size_px=None):
    raw = str(path_str or '').strip()
    if not raw:
        return None
    size_px = int(size_px or PDF_IMAGE_SIZE_PX or 300)
    try:
        data, _name = read_attachment_bytes_fast(raw)
        if not data:
            return None
        with PILImage.open(io.BytesIO(data)) as img:
            img = img.convert('RGB')
            # Reduz antes de recortar preservando qualidade
            img.thumbnail((size_px * 2, size_px * 2), PILImage.LANCZOS)
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize((size_px, size_px), PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=72, optimize=True, progressive=True)
            buf.seek(0)
    except Exception as exc:
        print('Falha ao preparar imagem do PDF:', exc)
        return None
    size_mm = 54 * mm
    return RLImage(buf, width=size_mm, height=size_mm)


def _prefetch_os_images_parallel(rows, max_workers=6):
    """Baixa todas as fotos de todas as O.S. em paralelo antes de gerar o PDF.

    Isso elimina o gargalo de baixar foto por foto sequencialmente do Supabase.
    Com 60 O.S. e 3 fotos cada = ~180 downloads em paralelo em vez de sequencial.
    """
    all_paths = []
    for row in rows:
        for p in _pdf_collect_os_image_paths(row):
            all_paths.append(p)

    if not all_paths:
        return

    def _fetch_one(path):
        try:
            read_attachment_bytes_fast(path)
        except Exception:
            pass

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_fetch_one, all_paths))


def _draw_pdf_header(canvas, doc, title='', subtitle=''):
    canvas.saveState()
    page_w, page_h = doc.pagesize
    margin_x = doc.leftMargin
    right_x = page_w - doc.rightMargin
    top_y = page_h - 6 * mm
    logo_box_w = 34 * mm
    logo_box_h = 12 * mm

    left_logo = company_identity_file('logo_esquerda.png', current_company_id()) or company_identity_file('logo.png', current_company_id())
    right_logo = company_identity_file('logo_direita.png', current_company_id())

    fallback_left = BASE_DIR / 'static' / 'logo_esquerda.png'
    fallback_right = BASE_DIR / 'static' / 'logo_direita.png'

    def _draw_logo(path_obj, box_x, fallback_path):
        if not path_obj:
            path_obj = fallback_path

        path_obj = Path(path_obj)

        if not path_obj.exists():
            path_obj = Path(fallback_path)

        if not path_obj.exists():
            return

        try:
            img = ImageReader(str(path_obj))
            w, h = img.getSize()
            if not w or not h:
                return

            scale = min(logo_box_w / w, logo_box_h / h)
            draw_w = w * scale
            draw_h = h * scale
            draw_x = box_x + (logo_box_w - draw_w) / 2
            draw_y = (top_y - logo_box_h) + (logo_box_h - draw_h) / 2

            canvas.drawImage(
                str(path_obj),
                draw_x,
                draw_y,
                width=draw_w,
                height=draw_h,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception:
            return

    _draw_logo(left_logo, margin_x, fallback_left)
    _draw_logo(right_logo, right_x - logo_box_w, fallback_right)

    if title:
        canvas.setFillColor(colors.black)
        canvas.setFont('Helvetica-Bold', 14)
        title_y = top_y - (logo_box_h / 2) + 3
        canvas.drawCentredString(page_w / 2, title_y, title)
        if subtitle:
            canvas.setFont('Helvetica-Bold', 10)
            canvas.drawCentredString(page_w / 2, title_y - 12, subtitle)

    canvas.setStrokeColor(colors.HexColor('#9aa7ba'))
    canvas.setLineWidth(0.7)
    canvas.line(margin_x, top_y - logo_box_h - 5 * mm, right_x, top_y - logo_box_h - 5 * mm)
    canvas.restoreState()


def _build_os_pdf(ordens, titulo='RDO - RELATÓRIO DIÁRIO', subtitulo=''):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=24*mm, bottomMargin=25*mm)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle('normal', parent=styles['Normal'], fontSize=9, leading=11, leftIndent=0, firstLineIndent=0, spaceBefore=0, spaceAfter=0)
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
                import base64 as _b64, io as _io
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

        # Dados de data+hora completos (novo formato) ou hora simples (legado)
        _di_raw = r.get('data_inicio') or ''
        _df_raw = r.get('data_fim') or ''
        _di_label = _di_raw if _di_raw else '-'
        _df_label = _df_raw if _df_raw else '-'
        _tempo = elapsed_label('', '', r.get('acumulado_minutos') or 0, running=False) or '-'

        info = [
            ['O.S.', _pdf_safe_text(r.get('numero_os') or r.get('id') or ''), 'Sistema', _pdf_safe_text(row_get_value(r, 'sistema', '') or '')],
            ['Equipamento', _pdf_safe_text(row_get_value(r, 'equipamento', '') or row_get_value(r, 'ativo_nome', '') or ''), 'Finalizada', _pdf_safe_text(finalizada_pdf)],
            ['Criticidade', _pdf_safe_text(row_get_value(r, 'criticidade', '') or ''), 'Responsável', _pdf_safe_text(row_get_value(r, 'responsavel', '') or '')],
            ['Início', _pdf_safe_text(_di_label), 'Fim', _pdf_safe_text(_df_label)],
        ]

        # Histórico de pausas/retomadas
        try:
            _hist = json.loads(r.get('historico_pausas') or '[]')
        except Exception:
            _hist = []

        # Adiciona linhas de pausa/retomada/finalizado ao info
        for _ev in _hist:
            _acao = str(_ev.get('acao') or '').strip().lower()
            _quando = _pdf_safe_text(_ev.get('quando') or '')
            _motivo_ev = _pdf_safe_text(_ev.get('motivo') or '')
            if _acao == 'pausado':
                info.append(['Pausado em', _quando, 'Motivo', _motivo_ev or '-'])
            elif _acao == 'retomado':
                info.append(['Retomado em', _quando, '', ''])
            elif _acao == 'finalizado':
                info.append(['Finalizado em', _quando, 'Tempo total', _tempo])

        # Se não tem histórico de finalizado mas tem tempo acumulado, mostra tempo total
        _has_finalizado_hist = any(str(e.get('acao','')).lower() == 'finalizado' for e in _hist)
        if not _has_finalizado_hist and r.get('acumulado_minutos'):
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
        # Destaca linha de pausa em amarelo claro
        for i, row_info in enumerate(info):
            if i >= 4:  # linhas do histórico
                _acao_row = str(row_info[0]).lower()
                if 'pausado' in _acao_row:
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

        # Motivo da pausa (se houver)
        _motivo_pausa = (r.get('motivo_pausa') or '').strip()
        if _motivo_pausa:
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
        'servico_executado', 'imagens', 'teve_terceiro', 'quem_foi_terceiro', 'empresa_id'
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



def os_pdf_dia():
    data = (request.args.get('data') or '').strip()
    if not data:
        flash('Informe a data para gerar o relatório.', 'warning')
        return redirect(url_for('os_page'))

    cache_key = f"pdf:dia:{current_company_id()}:{data}:imgs{PDF_MAX_IMAGES_PER_OS}"
    cached = _pdf_cache_get(cache_key)
    if cached:
        return send_file(cached, mimetype='application/pdf', as_attachment=False, download_name=f'rdo_dia_{data.replace("/", "-")}.pdf')

    def _row_date_key(r):
        data_txt = row_get_value(r, 'data', '')
        rid = int(row_get_value(r, 'id', 0) or 0)
        return (parse_br_date(str(data_txt or '')) or datetime.min, rid)

    os_pdf_cols = select_existing_columns('os_ordens', [
        'id','data','sistema','equipamento','ativo_nome','status','finalizada','criticidade','responsavel',
        'data_inicio','data_fim','descricao','servico_executado','imagens','teve_terceiro','quem_foi_terceiro','empresa_id'
    ])
    where_sql, params = company_where('os_ordens')
    params = list(params)
    where_sql += (' AND ' if where_sql else ' WHERE ')
    where_sql += 'data=?'
    params.append(data)

    rows_raw = query_all(f'SELECT {os_pdf_cols} FROM os_ordens{where_sql} ORDER BY id ASC LIMIT 200', tuple(params))
    rows = sorted([sync_os_attachments(row_to_dict(r), persist_db=False) for r in rows_raw], key=_row_date_key)
    rows = attach_os_display_numbers(rows)
    if not rows:
        flash('Nenhuma O.S. encontrada para a data informada.', 'warning')
        return redirect(url_for('os_page'))

    pdf = _build_os_pdf(rows, subtitulo=f'Dia: {data}')
    pdf = _pdf_cache_set(cache_key, pdf)
    return send_file(pdf, mimetype='application/pdf', as_attachment=False, download_name=f'rdo_dia_{data.replace("/", "-")}.pdf')



def os_pdf_mes_sync():
    """Fallback manual: gera PDF mensal na requisição atual.

    Use só para teste/local. No Render, prefira /os/pdf/mes em background.
    """
    mes = (request.args.get('mes') or '').strip()
    if not mes:
        flash('Informe o mês para gerar o relatório.', 'warning')
        return redirect(url_for('os_page'))
    try:
        pdf, mes_norm = _build_os_pdf_mes_buffer(mes, include_all_images=True, use_cache=False)
        return send_file(
            pdf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f"rdo_mes_{str(mes_norm).replace('/', '-')}.pdf"
        )
    except Exception as exc:
        _flask_app().logger.exception('Falha ao gerar PDF mensal síncrono de O.S.')
        flash(f'Não foi possível gerar o PDF mensal: {exc}', 'danger')
        return redirect(url_for('os_page'))




def os_pdf_job_status(job_id):
    """Consulta status do PDF em background."""
    if current_user_is_super_admin():
        job = row_to_dict(query_one('SELECT id, status, arquivo_url, storage_path, erro, mes FROM pdf_jobs WHERE id=?', (job_id,)))
    else:
        job = row_to_dict(query_one(
            'SELECT id, status, arquivo_url, storage_path, erro, mes FROM pdf_jobs WHERE id=? AND empresa_id=?',
            (job_id, current_company_id())
        ))
    if not job:
        return jsonify({'status': 'erro', 'erro': 'Job não encontrado.'}), 404
    return jsonify(job)




def os_pdf_mes_job():
    """Endpoint JSON para botão/ajax criar PDF mensal em background."""
    mes = (request.form.get('mes') or request.args.get('mes') or '').strip()
    if not mes and request.is_json:
        payload = request.get_json(silent=True) or {}
        mes = str(payload.get('mes') or '').strip()
    if not mes:
        return jsonify({'ok': False, 'error': 'Informe o mês.'}), 400
    try:
        job_id, mes_norm = _create_pdf_job('mensal_os', mes)
        _start_pdf_job_thread(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'mes': mes_norm})
    except Exception as exc:
        _flask_app().logger.exception('Falha ao iniciar job JSON de PDF mensal.')
        return jsonify({'ok': False, 'error': str(exc)}), 500




def os_pdf_mes():
    """Cria tarefa em background para PDF mensal e mostra tela de acompanhamento."""
    mes = (request.args.get('mes') or '').strip()
    if not mes:
        flash('Informe o mês para gerar o relatório.', 'warning')
        return redirect(url_for('os_page'))

    try:
        job_id, mes_norm = _create_pdf_job('mensal_os', mes)
        _start_pdf_job_thread(job_id)
        return _render_pdf_job_wait_page(job_id, mes_norm)
    except Exception as exc:
        _flask_app().logger.exception('Falha ao iniciar job de PDF mensal de O.S.')
        flash(f'Não foi possível iniciar o PDF mensal: {exc}', 'danger')
        return redirect(url_for('os_page'))






def register_pdf_routes(app):
    rules = [
        ('/os/pdf/dia', 'os_pdf_dia', os_pdf_dia, ['GET']),
        ('/os/pdf/mes', 'os_pdf_mes', os_pdf_mes, ['GET']),
        ('/os/pdf/mes/job', 'os_pdf_mes_job', os_pdf_mes_job, ['POST']),
        ('/os/pdf/job/<int:job_id>/status', 'os_pdf_job_status', os_pdf_job_status, ['GET']),
        ('/os/pdf/mes/sync', 'os_pdf_mes_sync', os_pdf_mes_sync, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, require_permission('generate_pdf')(view), methods=methods)
