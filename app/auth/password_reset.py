"""Recuperação de senha."""
import os
import smtplib
import threading
import time
import uuid
from email.message import EmailMessage

from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.db import execute, query_one

_PASSWORD_RESET_TOKENS = {}
_PASSWORD_RESET_LOCK = threading.Lock()
PASSWORD_RESET_EXPIRY = 3600

def _send_reset_email(to_email, reset_link):
    """Envia e-mail de recuperação de senha via Gmail SMTP."""
    try:
        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com').strip()
        smtp_port = int(os.getenv('SMTP_PORT', '587') or 587)
        smtp_user = os.getenv('SMTP_USER', 'irisgetec@gmail.com').strip()
        smtp_pass = os.getenv('SMTP_PASS', 'eoaspnfgreyltiep').strip()

        msg = EmailMessage()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = 'IRIS — Recuperação de senha'
        msg.set_content(f"""Olá!

Recebemos uma solicitação para redefinir a senha da sua conta no IRIS.

Clique no link abaixo para criar uma nova senha:
{reset_link}

Este link expira em 1 hora.

Se você não solicitou a recuperação de senha, ignore este e-mail.

Atenciosamente,
Equipe IRIS
""")
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as exc:
        print('_send_reset_email falhou:', exc)
        return False


def esqueci_senha():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            flash('Informe seu e-mail.', 'danger')
            return render_template('esqueci_senha.html')

        user = query_one('SELECT id, email, ativo FROM users WHERE lower(trim(email))=lower(trim(?)) AND COALESCE(ativo,1)=1', (email,))
        # Sempre mostra mensagem de sucesso para não revelar se o e-mail existe
        if user:
            token = uuid.uuid4().hex + uuid.uuid4().hex
            expires_at = time.time() + PASSWORD_RESET_EXPIRY
            with _PASSWORD_RESET_LOCK:
                # Limpa tokens antigos
                now = time.time()
                expired = [t for t, v in _PASSWORD_RESET_TOKENS.items() if v['expires_at'] < now]
                for t in expired:
                    _PASSWORD_RESET_TOKENS.pop(t, None)
                _PASSWORD_RESET_TOKENS[token] = {'email': email, 'expires_at': expires_at}
            try:
                base = request.url_root.rstrip('/')
                reset_link = f"{base}/redefinir-senha/{token}"
                _send_reset_email(email, reset_link)
            except Exception as exc:
                print('Erro ao enviar e-mail de recuperação:', exc)

        flash('Se esse e-mail estiver cadastrado, você receberá as instruções em instantes.', 'success')
        return render_template('esqueci_senha.html', enviado=True)

    return render_template('esqueci_senha.html')


def redefinir_senha(token):
    now = time.time()
    with _PASSWORD_RESET_LOCK:
        entry = _PASSWORD_RESET_TOKENS.get(token)

    if not entry or entry['expires_at'] < now:
        flash('Link inválido ou expirado. Solicite um novo.', 'danger')
        return redirect(url_for('esqueci_senha'))

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha') or ''
        confirmar = request.form.get('confirmar_senha') or ''
        if len(nova_senha) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'danger')
            return render_template('redefinir_senha.html', token=token)
        if nova_senha != confirmar:
            flash('As senhas não coincidem.', 'danger')
            return render_template('redefinir_senha.html', token=token)

        email = entry['email']
        execute('UPDATE users SET senha_hash=? WHERE lower(trim(email))=lower(trim(?)) AND COALESCE(ativo,1)=1',
                (generate_password_hash(nova_senha), email))
        with _PASSWORD_RESET_LOCK:
            _PASSWORD_RESET_TOKENS.pop(token, None)
        flash('Senha redefinida com sucesso! Faça login com a nova senha.', 'success')
        return redirect(url_for('login'))

    return render_template('redefinir_senha.html', token=token)
