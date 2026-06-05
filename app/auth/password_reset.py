"""Recuperação de senha."""
import os
import smtplib
import time
import uuid
from email.message import EmailMessage

from flask import current_app, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.auth.security_store import (
    delete_password_reset_token,
    get_password_reset_token,
    save_password_reset_token,
)
from app.db import execute, query_one

PASSWORD_RESET_EXPIRY = 3600


def _smtp_configured():
    user = os.getenv('SMTP_USER', '').strip()
    password = os.getenv('SMTP_PASS', '').strip()
    return bool(user and password)


def _send_reset_email(to_email, reset_link):
    """Envia e-mail de recuperação de senha via SMTP configurado no ambiente."""
    if not _smtp_configured():
        current_app.logger.warning('password_reset: SMTP_USER/SMTP_PASS não configurados')
        return False
    try:
        smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com').strip()
        smtp_port = int(os.getenv('SMTP_PORT', '587') or 587)
        smtp_user = os.getenv('SMTP_USER', '').strip()
        smtp_pass = os.getenv('SMTP_PASS', '').strip()

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
        current_app.logger.exception('password_reset: falha ao enviar e-mail')
        return False


def esqueci_senha():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            flash('Informe seu e-mail.', 'danger')
            return render_template('esqueci_senha.html')

        if not _smtp_configured():
            flash(
                'Recuperação por e-mail ainda não está ativa neste servidor. '
                'Peça ao administrador do sistema para redefinir sua senha.',
                'warning',
            )
            return render_template('esqueci_senha.html')

        user = query_one(
            'SELECT id, email, ativo FROM users WHERE lower(trim(email))=lower(trim(?)) AND COALESCE(ativo,1)=1',
            (email,),
        )
        if user:
            token = uuid.uuid4().hex + uuid.uuid4().hex
            expires_at = time.time() + PASSWORD_RESET_EXPIRY
            save_password_reset_token(token, email, expires_at)
            base = request.url_root.rstrip('/')
            reset_link = f"{base}/redefinir-senha/{token}"
            if not _send_reset_email(email, reset_link):
                flash('Não foi possível enviar o e-mail agora. Tente novamente em alguns minutos.', 'danger')
                return render_template('esqueci_senha.html')

        flash('Se esse e-mail estiver cadastrado, você receberá as instruções em instantes.', 'success')
        return render_template('esqueci_senha.html', enviado=True)

    return render_template('esqueci_senha.html')


def redefinir_senha(token):
    now = time.time()
    entry = get_password_reset_token(token)

    if not entry or entry['expires_at'] < now:
        flash('Link inválido ou expirado. Solicite um novo.', 'danger')
        return redirect(url_for('esqueci_senha'))

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha') or ''
        confirmar = request.form.get('confirmar_senha') or ''
        if len(nova_senha) < 8:
            flash('A senha deve ter pelo menos 8 caracteres.', 'danger')
            return render_template('redefinir_senha.html', token=token)
        if nova_senha != confirmar:
            flash('As senhas não coincidem.', 'danger')
            return render_template('redefinir_senha.html', token=token)

        email = entry['email']
        execute('UPDATE users SET senha_hash=? WHERE lower(trim(email))=lower(trim(?)) AND COALESCE(ativo,1)=1',
                (generate_password_hash(nova_senha), email))
        delete_password_reset_token(token)
        flash('Senha redefinida com sucesso! Faça login com a nova senha.', 'success')
        return redirect(url_for('login'))

    return render_template('redefinir_senha.html', token=token)
