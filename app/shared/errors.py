"""Helpers para páginas de erro amigáveis (P2)."""
from flask import render_template, session, url_for


def _fallback_error_html(code, title, message, back_url=None):
    back = f'<p><a href="{back_url}">Voltar</a></p>' if back_url else ''
    return (
        f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        f'<title>IRIS — {title}</title></head><body>'
        f'<h1>{code} — {title}</h1><p>{message}</p>{back}</body></html>'
    )


def render_error_page(code, title, message, tone='danger', back_url=None, back_label=None):
    show_login = not session.get('user_id')
    if back_url is None and session.get('user_id'):
        try:
            back_url = url_for('dashboard')
        except Exception:
            try:
                from app.auth.services import default_landing_url
                back_url = default_landing_url()
            except Exception:
                back_url = url_for('login')
    try:
        return render_template(
            'errors/page.html',
            code=code,
            title=title,
            message=message,
            tone=tone,
            back_url=back_url,
            back_label=back_label,
            show_login=show_login,
        ), int(code)
    except Exception:
        return _fallback_error_html(code, title, message, back_url), int(code)
