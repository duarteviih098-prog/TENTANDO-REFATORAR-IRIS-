"""Helpers para páginas de erro amigáveis (P2)."""
from flask import render_template, session, url_for


def render_error_page(code, title, message, tone='danger', back_url=None, back_label=None):
    show_login = not session.get('user_id')
    if back_url is None and session.get('user_id'):
        try:
            from app.auth.services import default_landing_url
            back_url = default_landing_url()
        except Exception:
            back_url = url_for('login')
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
