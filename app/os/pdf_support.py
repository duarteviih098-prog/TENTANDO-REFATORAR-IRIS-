"""Formatação, cache, imagens e cabeçalho do PDF de O.S."""
import io
import json
import re
import time
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage

from app.os.pdf_common import (
    _PDF_BYTES_CACHE,
    _PDF_CACHE_LOCK,
    PDF_CACHE_TTL_SECONDS,
    PDF_IMAGE_SIZE_PX,
    current_company_id,
)
from app.shared.formatters import only_time_str
from app.storage import company_identity_file
from app.storage.attachments import read_attachment_bytes_fast
from app.storage.paths import BASE_DIR, normalize_storage_path


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


def _pdf_parse_when(raw, os_date=''):
    """Converte timestamp de evento em datetime; usa os_date se vier só HH:MM."""
    text = str(raw or '').strip()
    if not text:
        return None
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    hora = only_time_str(text)
    if not hora:
        return None
    base = str(os_date or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        if not base:
            break
        try:
            day = datetime.strptime(base, fmt).date()
            return datetime.combine(day, datetime.strptime(hora, '%H:%M').time())
        except Exception:
            pass
    return None


def _pdf_collect_hist_dates(hist, data_inicio='', data_fim='', os_date=''):
    """Datas distintas do histórico + início/fim — detecta O.S. que atravessa dias."""
    dates = set()
    for raw in (data_inicio, data_fim):
        dt = _pdf_parse_when(raw, os_date)
        if dt:
            dates.add(dt.date())
    for ev in hist or []:
        dt = _pdf_parse_when(ev.get('quando'), os_date)
        if dt:
            dates.add(dt.date())
    return dates


def _pdf_datetime_label(raw, os_date='', multiday=False):
    """Hora do evento; data só quando a O.S. atravessa mais de um dia."""
    dt = _pdf_parse_when(raw, os_date)
    if not dt:
        hora = only_time_str(raw)
        return hora or '-'
    if multiday:
        return dt.strftime('%d/%m/%Y %H:%M')
    return dt.strftime('%H:%M')


def _pdf_time_label(raw, hist=None):
    """Só hora (HH:MM) — a data da O.S. já aparece no cabeçalho."""
    hora = only_time_str(raw)
    if hora:
        return hora
    for ev in hist or []:
        acao = str(ev.get('acao') or '').strip().lower()
        if acao in ('iniciado', 'retomado'):
            hora = only_time_str(ev.get('quando'))
            if hora:
                return hora
    return '-'


def _pdf_fim_label(raw, hist=None, finalizada=False):
    """Hora de término/pausa atual, sem repetir a data do cabeçalho."""
    hora = only_time_str(raw)
    if hora:
        return hora
    if finalizada:
        for ev in reversed(hist or []):
            if str(ev.get('acao') or '').strip().lower() == 'finalizado':
                hora = only_time_str(ev.get('quando'))
                if hora:
                    return hora
    return '-'


def _pdf_historico_for_display(hist, finalizada=False):
    """Remove eventos repetidos e estados inválidos antes de montar o PDF."""
    cleaned = []
    seen = set()
    for ev in hist or []:
        if not isinstance(ev, dict):
            continue
        acao = str(ev.get('acao') or '').strip().lower()
        quando = str(ev.get('quando') or '').strip()
        motivo = str(ev.get('motivo') or '').strip()
        if not acao:
            continue
        key = (acao, quando) if acao in ('iniciado', 'finalizado', 'retomado') else (acao, quando, motivo)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({**ev, 'acao': acao, 'quando': quando, 'motivo': motivo})

    last_finalizado_idx = max(
        (i for i, ev in enumerate(cleaned) if ev.get('acao') == 'finalizado'),
        default=-1,
    )
    out = []
    iniciado_ok = False
    for i, ev in enumerate(cleaned):
        acao = ev.get('acao')
        if acao == 'iniciado':
            if iniciado_ok:
                continue
            iniciado_ok = True
            out.append(ev)
        elif acao == 'finalizado':
            if i != last_finalizado_idx:
                continue
            out.append(ev)
        else:
            out.append(ev)

    if not finalizada and out:
        if out[-1].get('acao') == 'pausado':
            out = [ev for ev in out if ev.get('acao') != 'finalizado']
        else:
            last_pause = max(
                (i for i, ev in enumerate(out) if ev.get('acao') == 'pausado'),
                default=-1,
            )
            if last_pause >= 0:
                out = [
                    ev for i, ev in enumerate(out)
                    if not (ev.get('acao') == 'finalizado' and i < last_pause)
                ]
    return out


def _pdf_hist_needs_detail_rows(hist, multiday=False):
    """Histórico detalhado só quando houve pausa/retomada ou a O.S. atravessa dias."""
    if multiday:
        return True
    return any(str(ev.get('acao') or '').lower() in ('pausado', 'retomado') for ev in (hist or []))


def _pdf_logo_candidates(side='left', empresa_id=None):
    """Candidatos a arquivo de logo — identidade da empresa, depois static/."""
    empresa_id = empresa_id or current_company_id()
    static = BASE_DIR / 'static'
    if side == 'right':
        names = ('logo_direita.png', 'logo_cliente.png', 'logo.png')
        static_names = ('logo_direita.png', 'logo_sidebar.png', 'iris_icon.png')
    else:
        names = ('logo_esquerda.png', 'logo.png')
        static_names = ('logo_esquerda.png', 'logo.png', 'iris_icon.png')
    paths = []
    for name in names:
        found = company_identity_file(name, empresa_id)
        if found:
            paths.append(found)
    for name in static_names:
        paths.append(static / name)
    return paths


def _pdf_draw_logo_in_box(canvas, box_x, box_y, box_w, box_h, candidates):
    """Desenha a primeira logo válida da lista dentro da caixa do cabeçalho."""
    for candidate in candidates:
        path_obj = Path(candidate) if candidate else None
        if not path_obj or not path_obj.exists():
            continue
        try:
            img = ImageReader(str(path_obj))
            w, h = img.getSize()
            if not w or not h:
                continue
            scale = min(box_w / w, box_h / h)
            draw_w = w * scale
            draw_h = h * scale
            draw_x = box_x + (box_w - draw_w) / 2
            draw_y = box_y + (box_h - draw_h) / 2
            for mask in ('auto', None):
                try:
                    canvas.drawImage(
                        str(path_obj),
                        draw_x,
                        draw_y,
                        width=draw_w,
                        height=draw_h,
                        preserveAspectRatio=True,
                        mask=mask,
                    )
                    return True
                except Exception:
                    continue
        except Exception as exc:
            print(f'PDF logo ignorada ({path_obj.name}):', exc)
    return False


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
    logo_box_y = top_y - logo_box_h

    empresa_id = current_company_id()
    _pdf_draw_logo_in_box(
        canvas, margin_x, logo_box_y, logo_box_w, logo_box_h,
        _pdf_logo_candidates('left', empresa_id),
    )
    _pdf_draw_logo_in_box(
        canvas, right_x - logo_box_w, logo_box_y, logo_box_w, logo_box_h,
        _pdf_logo_candidates('right', empresa_id),
    )

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

