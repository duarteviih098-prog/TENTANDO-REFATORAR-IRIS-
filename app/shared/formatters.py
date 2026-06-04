"""Formatação de datas, números e telefones."""
import re
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from app.config import APP_TIMEZONE


def br_now():
    """Hora oficial do app, sempre no fuso do Brasil/São Paulo."""
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.now()


def parse_num(s, default=0.0):
    try:
        txt = str(s or '').replace('R$', '').replace(' ', '')
        if ',' in txt and '.' in txt:
            if txt.rfind(',') > txt.rfind('.'):
                txt = txt.replace('.', '').replace(',', '.')
            else:
                txt = txt.replace(',', '')
        elif ',' in txt:
            txt = txt.replace('.', '').replace(',', '.')
        return float(txt) if txt else default
    except Exception:
        return default


def br_money(value):
    num = parse_num(value) if isinstance(value, str) else float(value or 0)
    return f"R$ {num:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def parse_br_date(raw):
    raw = (raw or '').strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass
    return None


def br_date(value):
    parsed = parse_br_date(str(value or ''))
    return parsed.strftime('%d/%m/%Y') if parsed else str(value or '')


def normalize_phone(raw):
    digits = re.sub(r'\D+', '', str(raw or ''))
    if digits.startswith('55') and len(digits) in (12, 13):
        return digits
    if len(digits) in (10, 11):
        return '55' + digits
    return digits


def format_phone_br(raw):
    digits = normalize_phone(raw)
    d = digits[2:] if digits.startswith('55') else digits
    if len(d) == 11:
        return f'({d[:2]}) {d[2:7]}-{d[7:]}'
    if len(d) == 10:
        return f'({d[:2]}) {d[2:6]}-{d[6:]}'
    return raw or ''


def now_str():
    return br_now().strftime('%d/%m/%Y %H:%M:%S')


def only_time_str(raw):
    raw = str(raw or '').strip()
    if not raw:
        return ''
    for pattern in [r'(\d{2}:\d{2})(?::\d{2})?$', r'\b(\d{2}:\d{2})\b']:
        m = re.search(pattern, raw)
        if m:
            return m.group(1)
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(raw, fmt).strftime('%H:%M')
        except Exception:
            pass
    return raw[:5] if len(raw) >= 5 and ':' in raw else raw


def time_diff_minutes(start_raw, end_raw=''):
    start_h = only_time_str(start_raw)
    end_h = only_time_str(end_raw)
    if not start_h or not end_h:
        return None
    try:
        start_dt = datetime.strptime(start_h, '%H:%M')
        end_dt = datetime.strptime(end_h, '%H:%M')
    except Exception:
        return None
    minutes = int((end_dt - start_dt).total_seconds() // 60)
    if minutes < 0:
        minutes += 24 * 60
    return minutes


def minutes_to_label(total_minutes):
    total_minutes = int(total_minutes or 0)
    h, m = divmod(max(total_minutes, 0), 60)
    return f'{h:02d}:{m:02d}'


def elapsed_label(start_raw, end_raw='', accumulated_minutes=0, running=False):
    accumulated_minutes = int(accumulated_minutes or 0)
    start_h = only_time_str(start_raw)
    end_h = only_time_str(end_raw)
    if running and start_h:
        extra = time_diff_minutes(start_h, br_now().strftime('%H:%M')) or 0
        return minutes_to_label(accumulated_minutes + extra)
    if accumulated_minutes > 0:
        return minutes_to_label(accumulated_minutes)
    if start_h and end_h:
        return minutes_to_label(time_diff_minutes(start_h, end_h) or 0)
    if start_h:
        return '00:00'
    return ''
