"""Rotas de login, usuários, empresas e auditoria."""
import json
from app.auth.decorators import is_mobile_request
from app.campo.services import campo_token_para_usuario, sincronizar_usuario_campo, usuario_eh_campo_operacional
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, normalize_phone, now_str
from app.shared.rows import row_to_dict
from app.storage import backup_company_data, ensure_company_storage, load_company_identity_config, save_company_identity_config, save_company_identity_file

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from app.auth.constants import ALL_PERMISSIONS, PERMISSION_LABELS, ROLE_LABELS, ROLE_PERMISSIONS, normalize_permissions
from app.auth.decorators import require_permission
from app.auth.services import (
    LOGIN_MAX_ATTEMPTS,
    _login_clear,
    _login_get_ip,
    _login_is_blocked,
    _login_record_failure,
    current_user_is_super_admin,
    default_landing_url,
    get_current_user,
    permission_denied_redirect,
    senha_confere,
    user_has,
)
from app.auth.tenancy import (
    create_company_if_needed,
    current_company_id,
    find_company_by_domain_or_name,
    list_companies,
    normalize_domain,
    unique_email_for_domain,
)
from app.db import execute, query_all, query_one, table_has_column


def owned_by_current_company(table, rid):
    from app.auth.tenancy import owned_by_current_company as fn
    return fn(table, rid)

def app_logger():
    from flask import current_app
    return current_app.logger

def campo_login():
    return login()


def login():
    if request.method == 'GET' and session.get('user_id') and get_current_user():
        return redirect(default_landing_url())

    if request.method == 'POST':
        ip = _login_get_ip()
        blocked, secs = _login_is_blocked(ip)
        if blocked:
            mins = max(1, secs // 60)
            flash(f'Muitas tentativas incorretas. Tente novamente em {mins} minuto(s).', 'danger')
            return render_template('campo_login.html' if request.path.startswith('/campo/login') else 'login.html')

        email_form = (request.form.get('email') or '').strip().lower()
        senha = request.form.get('senha') or ''
        user = row_to_dict(query_one('''SELECT id, nome, email, senha_hash, perfil, permissions, empresa_id, ativo, is_super_admin, telefone
                                        FROM users
                                        WHERE lower(trim(email))=lower(trim(?))
                                          AND COALESCE(ativo,1)=1
                                        ORDER BY id DESC
                                        LIMIT 1''', (email_form,)))
        if user and senha_confere(user.get('senha_hash') or '', senha):
            _login_clear(ip)
            # Se a senha estava em formato legado/texto ou com espaço acidental, regrava como hash correto.
            try:
                senha_hash_atual = str(user.get('senha_hash') or '')
                senha_limpa = str(senha or '').strip()
                if senha_limpa and (senha_hash_atual == senha or senha_hash_atual == senha_limpa):
                    execute('UPDATE users SET senha_hash=? WHERE id=?', (generate_password_hash(senha_limpa), user['id']))
            except Exception:
                pass

            # Login inteligente: se o usuário não estiver vinculado, detecta a sede pelo domínio do e-mail.
            if not user.get('empresa_id') and email_form and '@' in email_form:
                dominio_login = normalize_domain(email_form.split('@')[-1])
                empresa_login = find_company_by_domain_or_name(dominio_login, '')
                if empresa_login:
                    execute('UPDATE users SET empresa_id=? WHERE id=?', (empresa_login['id'], user['id']))
                    user['empresa_id'] = empresa_login['id']
            session.clear()
            session.permanent = request.form.get('lembrar') == '1'
            session['user_id'] = user['id']
            session['user_name'] = user.get('nome') or user.get('email')
            session['user_email'] = user.get('email') or email_form
            session['user_perfil'] = user.get('perfil') or ''
            session['empresa_id'] = user.get('empresa_id')
            session['_is_permanent'] = session.permanent
            session.pop('selected_empresa_id', None)
            ensure_company_storage(user.get('empresa_id'))
            session['is_super_admin'] = int(user.get('is_super_admin') or 0)
            flash('Login realizado com sucesso.', 'success')

            # Usuário/técnico de campo NÃO entra no desktop.
            if usuario_eh_campo_operacional(user):
                try:
                    token_campo = campo_token_para_usuario(user)
                    if token_campo:
                        return redirect(url_for('campo_app', token=token_campo))
                    # Token não encontrado — sincroniza e tenta de novo
                    tecnico = sincronizar_usuario_campo(
                        user.get('id'), user.get('nome'), user.get('email'),
                        user.get('telefone'), user.get('empresa_id'),
                        user.get('perfil'), user.get('ativo', 1)
                    )
                    if tecnico and tecnico.get('token'):
                        return redirect(url_for('campo_app', token=tecnico['token']))
                except Exception:
                    app_logger().exception('Falha ao redirecionar usuário de campo para app mobile')
                # Fallback: mostra app de campo vazio em vez do desktop
                return redirect(url_for('campo_app_empty'))

            # Respeita o destino original quando existir.
            nxt = request.args.get('next')
            if not nxt or nxt in ('/', '/login'):
                # Celular + perfil não-campo → app mobile do gestor
                if is_mobile_request() and not usuario_eh_campo_operacional(user):
                    return redirect(url_for('gestor_app'))
                nxt = default_landing_url()
            return redirect(nxt)
        count, blocked_until = _login_record_failure(ip)
        restantes = max(0, LOGIN_MAX_ATTEMPTS - count)
        if blocked_until:
            flash(f'Conta bloqueada por 15 minutos após muitas tentativas incorretas.', 'danger')
        elif restantes > 0:
            flash(f'E-mail ou senha inválidos. {restantes} tentativa(s) restante(s).', 'danger')
        else:
            flash('E-mail ou senha inválidos.', 'danger')
    return render_template('campo_login.html' if request.path.startswith('/campo/login') else 'login.html')

def logout():
    session.clear()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('login'))


def historico_apagar_tudo():
    if not current_user_is_super_admin():
        flash('Sem permissão para apagar o histórico.', 'danger')
        return redirect(url_for('historico_page'))
    try:
        empresa_id = current_company_id()
        if empresa_id:
            execute('DELETE FROM audit_logs WHERE empresa_id=?', (empresa_id,))
        else:
            execute('DELETE FROM audit_logs', ())
        clear_view_cache()
        flash('Histórico apagado com sucesso.', 'success')
    except Exception as exc:
        flash(f'Erro ao apagar histórico: {exc}', 'danger')
    return redirect(url_for('historico_page'))


def historico_page():
    """Tela de histórico/auditoria do sistema."""
    usuario = (request.args.get('usuario') or '').strip()
    acao = (request.args.get('acao') or '').strip()
    entidade = (request.args.get('entidade') or '').strip()
    resultado = (request.args.get('resultado') or '').strip()

    # Audit logs ficam na tabela audit_logs. Para filtrar/ocultar perfil de campo,
    # precisamos fazer JOIN com users; antes o WHERE usava u.perfil sem declarar o alias u,
    # e o PostgreSQL derrubava a página com: missing FROM-clause entry for table "u".
    where = ["lower(COALESCE(u.perfil,'')) NOT IN ('campo','colaborador de campo')"]
    params = []

    if usuario:
        where.append('(a.usuario_nome LIKE ? OR a.usuario_email LIKE ?)')
        params.extend([f'%{usuario}%', f'%{usuario}%'])

    if acao:
        where.append('(a.acao LIKE ? OR a.endpoint LIKE ? OR a.rota LIKE ?)')
        params.extend([f'%{acao}%', f'%{acao}%', f'%{acao}%'])

    if entidade:
        where.append('a.entidade = ?')
        params.append(entidade)

    if resultado:
        where.append('a.resultado LIKE ?')
        params.append(f'{resultado}%')

    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    rows = [
        dict(r) for r in query_all(
            '''SELECT a.*
               FROM audit_logs a
               LEFT JOIN users u ON lower(COALESCE(u.email,'')) = lower(COALESCE(a.usuario_email,''))
               {where_sql}
               ORDER BY a.id DESC
               LIMIT 300'''.format(where_sql=where_sql),
            tuple(params)
        )
    ]

    users = [
        dict(r) for r in query_all(
            """SELECT nome AS usuario_nome, email AS usuario_email
               FROM users
               WHERE lower(COALESCE(perfil,'')) NOT IN ('campo','colaborador de campo')
               ORDER BY nome"""
        )
    ]

    hoje = br_now().strftime('%d/%m/%Y')
    counts = {
        'total': (query_one('SELECT COUNT(*) AS c FROM audit_logs') or {'c': 0})['c'],
        'hoje': (query_one('SELECT COUNT(*) AS c FROM audit_logs WHERE substr(criado_em,1,10)=?', (hoje,)) or {'c': 0})['c'],
        'falhas': (query_one("SELECT COUNT(*) AS c FROM audit_logs WHERE resultado LIKE 'falha%'") or {'c': 0})['c'],
    }

    return render_template(
        'auditoria.html',
        rows=rows,
        users=users,
        counts=counts,
        usuario=usuario,
        acao=acao,
        entidade=entidade,
        resultado=resultado,
    )

def empresa_contexto(empresa_id):
    if not current_user_is_super_admin():
        return permission_denied_redirect('Somente Administradores Supremos podem trocar a unidade de trabalho.')
    empresa = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=? AND ativo=1', (empresa_id,)))
    if not empresa:
        flash('Unidade não encontrada ou inativa.', 'danger')
        return redirect(url_for('dashboard'))
    session['selected_empresa_id'] = empresa_id
    session['empresa_id'] = empresa_id
    ensure_company_storage(empresa_id)
    clear_view_cache()
    session.pop('iris_history', None)
    from app.auth.audit import audit_security_event
    audit_security_event(
        'super_admin_troca_unidade',
        entidade='empresas',
        entidade_id=empresa_id,
        detalhes={'empresa_nome': empresa.get('nome'), 'empresa_cidade': empresa.get('cidade')},
    )
    flash(f'Unidade selecionada: {empresa.get("nome")}. Agora os módulos mostram somente os dados dela.', 'success')
    return redirect(url_for('dashboard'))


def visao_global():
    if not current_user_is_super_admin():
        flash('Somente os Administradores Supremos acessam a visão global.', 'danger')
        return redirect(url_for('dashboard'))
    from app.auth.audit import audit_security_event
    audit_security_event('super_admin_visao_global', entidade='empresas', detalhes={'scope': 'all'})
    resumo=[]
    for e in list_companies(active_only=False):
        eid=e['id']
        item=dict(e)
        for table in ('bombas','combustivel','pagamentos','custos','os_ativos','os_ordens','users'):
            if table_has_column(table,'empresa_id'):
                r=query_one(f'SELECT COUNT(*) AS total FROM {table} WHERE empresa_id=?',(eid,))
                item[table+'_total']=r['total'] if r else 0
        resumo.append(item)
    return render_template('visao_global.html', resumo=resumo)


def ops_jobs():
    """Painel super-admin: fila de jobs PDF e status recentes."""
    if not current_user_is_super_admin():
        flash('Somente Administradores Supremos acessam operações.', 'danger')
        return redirect(url_for('dashboard'))
    from app.auth.audit import audit_security_event
    audit_security_event('super_admin_ops_jobs', entidade='pdf_jobs', detalhes={'scope': 'recent'})

    if not table_has_column('pdf_jobs', 'id'):
        jobs = []
        stats = {'total': 0, 'gerando': 0, 'erro': 0, 'pronto': 0}
    else:
        jobs = [
            row_to_dict(r)
            for r in query_all(
                '''SELECT j.*, e.nome AS empresa_nome, u.nome AS usuario_nome
                   FROM pdf_jobs j
                   LEFT JOIN empresas e ON e.id = j.empresa_id
                   LEFT JOIN users u ON u.id = j.usuario_id
                   ORDER BY j.id DESC LIMIT 80''',
                (),
            )
        ]
        stats = {
            'total': (query_one('SELECT COUNT(*) AS c FROM pdf_jobs') or {'c': 0})['c'],
            'gerando': (query_one("SELECT COUNT(*) AS c FROM pdf_jobs WHERE status IN ('pendente','gerando')") or {'c': 0})['c'],
            'erro': (query_one("SELECT COUNT(*) AS c FROM pdf_jobs WHERE status='erro'") or {'c': 0})['c'],
            'pronto': (query_one("SELECT COUNT(*) AS c FROM pdf_jobs WHERE status='pronto'") or {'c': 0})['c'],
        }
    return render_template('ops_jobs.html', jobs=jobs, stats=stats)


def usuarios_page():
    if not current_user_is_super_admin():
        return permission_denied_redirect('Somente a Administradora Suprema pode criar empresas, usuários e permissões.')

    filtro_empresa = (request.args.get('empresa_id') or '').strip()
    filtro_perfil = (request.args.get('perfil') or '').strip()

    where = ["COALESCE(u.ativo,1)=1"]
    params = []
    if filtro_empresa:
        where.append('u.empresa_id = ?')
        params.append(filtro_empresa)
    if filtro_perfil:
        where.append('u.perfil = ?')
        params.append(filtro_perfil)

    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    rows = [dict(r) for r in query_all("""SELECT u.*, e.nome AS empresa_nome, e.cidade AS empresa_cidade
                                      FROM users u
                                      LEFT JOIN empresas e ON e.id=u.empresa_id
                                      {where_sql}
                                      ORDER BY COALESCE(e.nome,''), u.nome""".format(where_sql=where_sql), tuple(params))]
    empresas = list_companies(active_only=True)
    for r in rows:
        r['permissions'] = normalize_permissions(r.get('permissions'))
        r['perfil_label'] = ROLE_LABELS.get(r.get('perfil') or 'campo', r.get('perfil') or 'Usuário')
        # Indica se o usuário tem senha cadastrada (sem expor o hash)
        r['tem_senha'] = bool(str(r.get('senha_hash') or '').strip())
        # Remove o hash da resposta para não expor no template
        r.pop('senha_hash', None)
    return render_template('usuarios.html', rows=rows, empresas=empresas, all_permissions=ALL_PERMISSIONS,
                           permission_labels=PERMISSION_LABELS, role_permissions=ROLE_PERMISSIONS, role_labels=ROLE_LABELS,
                           filtro_empresa=filtro_empresa, filtro_perfil=filtro_perfil)

def empresas_save():
    if not current_user_is_super_admin():
        flash('Só a Administradora Suprema pode criar empresas.', 'danger')
        return redirect(url_for('usuarios_page'))
    nome = (request.form.get('empresa_nome') or '').strip()
    cidade = (request.form.get('empresa_cidade') or '').strip()
    dominio = normalize_domain(request.form.get('empresa_dominio') or '')
    if not nome and not dominio:
        flash('Informe pelo menos o nome da empresa ou o domínio.', 'danger')
        return redirect(url_for('usuarios_page'))
    try:
        empresa, created = create_company_if_needed(nome, cidade, dominio)
        if created:
            flash('Empresa criada com base vazia e pasta própria.', 'success')
        else:
            flash('Essa empresa/domínio já existia. Mantive o cadastro e evitei duplicar.', 'warning')
    except Exception as exc:
        flash(f'Não foi possível criar empresa: {exc}', 'danger')
    return redirect(url_for('usuarios_page'))

def empresas_update(empresa_id):
    if not current_user_is_super_admin():
        flash('Só a Administradora Suprema pode editar empresas.', 'danger')
        return redirect(url_for('usuarios_page'))
    nome = (request.form.get('nome') or '').strip()
    cidade = (request.form.get('cidade') or '').strip()
    dominio = normalize_domain(request.form.get('dominio_email') or '')
    ativo = 1 if request.form.get('ativo') == '1' else 0
    if not nome:
        flash('Informe o nome da empresa.', 'danger')
        return redirect(url_for('usuarios_page'))
    same_name = query_one('SELECT id FROM empresas WHERE lower(nome)=lower(?) AND id<>?', (nome, empresa_id))
    if same_name:
        flash('Já existe outra empresa com esse nome. Edite o cadastro existente ou escolha outro nome.', 'danger')
        return redirect(url_for('usuarios_page'))
    if dominio:
        same_domain = query_one('SELECT id FROM empresas WHERE lower(dominio_email)=lower(?) AND id<>?', (dominio, empresa_id))
        if same_domain:
            flash('Já existe outra empresa usando esse domínio. Um domínio só pode apontar para uma sede.', 'danger')
            return redirect(url_for('usuarios_page'))
    execute('UPDATE empresas SET nome=?, cidade=?, dominio_email=?, ativo=? WHERE id=?', (nome, cidade, dominio, ativo, empresa_id))
    ensure_company_storage(empresa_id)
    save_company_identity_config({
        'cliente': request.form.get('cliente_pdf') or '',
        'contratada': request.form.get('contratada_pdf') or nome,
        'cnpj': request.form.get('cnpj_pdf') or '',
        'cidade': request.form.get('cidade_pdf') or cidade,
        'responsavel': request.form.get('responsavel_pdf') or '',
        'assinatura_esquerda_label': request.form.get('assinatura_esquerda_label') or nome,
        'assinatura_direita_label': request.form.get('assinatura_direita_label') or ''
    }, empresa_id=empresa_id)
    save_company_identity_file(request.files.get('logo_esquerda'), 'logo_esquerda.png', empresa_id)
    save_company_identity_file(request.files.get('logo_direita'), 'logo_direita.png', empresa_id)
    save_company_identity_file(request.files.get('logo'), 'logo.png', empresa_id)
    arq_ass = request.files.get('assinatura')
    save_company_identity_file(arq_ass, 'assinatura.png', empresa_id)
    # Salva também em base64 no config para sobreviver restarts do Render
    if arq_ass and getattr(arq_ass, 'filename', ''):
        try:
            arq_ass.seek(0)
            import base64 as _b64
            ass_b64 = _b64.b64encode(arq_ass.read()).decode('utf-8')
            ext = (arq_ass.filename or 'assinatura.png').rsplit('.', 1)[-1].lower()
            mime = 'image/png' if ext == 'png' else ('image/jpeg' if ext in ('jpg','jpeg') else 'image/png')
            cfg_atual = load_company_identity_config(empresa_id) or {}
            cfg_atual['assinatura_b64'] = f'data:{mime};base64,{ass_b64}'
            save_company_identity_config(cfg_atual, empresa_id=empresa_id)
        except Exception as exc:
            print('Falha ao salvar assinatura em base64:', exc)

    # Mudou marca/dados cadastrais: PDFs prontos antigos não devem ser reutilizados.
    # Assim, o próximo PDF diário/mensal já sai com os novos dados.
    try:
        if table_has_column('pdf_jobs', 'empresa_id') and table_has_column('pdf_jobs', 'status'):
            execute("UPDATE pdf_jobs SET status='obsoleto' WHERE empresa_id=? AND status='pronto'", (empresa_id,))
    except Exception as exc:
        print('Não foi possível invalidar PDFs antigos após mudança da empresa:', exc)

    clear_view_cache()
    backup_company_data(empresa_id)
    flash('Empresa atualizada. Logo, assinatura e dados do PDF ficaram vinculados somente a esta unidade.', 'success')
    return redirect(url_for('usuarios_page'))

def usuarios_save():
    if not current_user_is_super_admin():
        return permission_denied_redirect('Somente a Administradora Suprema pode criar ou editar usuários.')
    rid = request.form.get('id') or None
    nome = (request.form.get('nome') or '').strip()
    email_user = (request.form.get('email') or '').strip().lower()
    senha = (request.form.get('senha') or '').strip()
    perfil = (request.form.get('perfil') or 'campo').strip()
    # Novo usuário nasce ativo por padrão. Em edição, desmarcar o checkbox inativa.
    ativo = 1 if (request.form.get('ativo') == '1' or not rid) else 0
    telefone = normalize_phone(request.form.get('telefone') or '')

    # Empresa inteligente: pode vir por id, por nome digitado, por domínio do e-mail ou por domínio digitado.
    empresa_id = request.form.get('empresa_id') or ''
    empresa_nome = (request.form.get('empresa_nome') or '').strip()
    empresa_cidade = (request.form.get('empresa_cidade') or '').strip()
    empresa_dominio = normalize_domain(request.form.get('empresa_dominio') or '')
    if email_user and '@' in email_user and not empresa_dominio:
        empresa_dominio = normalize_domain(email_user.split('@')[-1])

    empresa = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=?', (empresa_id,))) if empresa_id else None
    if not empresa:
        empresa = find_company_by_domain_or_name(empresa_dominio, empresa_nome)
    try:
        if not empresa and (empresa_nome or empresa_dominio):
            empresa, created = create_company_if_needed(empresa_nome, empresa_cidade, empresa_dominio)
            if created:
                flash('Empresa criada automaticamente pelo domínio informado.', 'success')
        elif empresa and (empresa_nome or empresa_dominio):
            # Se a empresa já existe, mantém domínio/cidade atualizados quando vierem preenchidos.
            if empresa_dominio and empresa_dominio != normalize_domain(empresa.get('dominio_email')):
                exists = query_one('SELECT id FROM empresas WHERE lower(dominio_email)=lower(?) AND id<>?', (empresa_dominio, empresa['id']))
                if exists:
                    flash('Esse domínio já pertence a outra empresa. Mantive o domínio anterior para evitar vazamento entre sedes.', 'danger')
                else:
                    execute('UPDATE empresas SET dominio_email=? WHERE id=?', (empresa_dominio, empresa['id']))
                    empresa['dominio_email'] = empresa_dominio
    except Exception as exc:
        flash(f'Não foi possível preparar a empresa: {exc}', 'danger')
        return redirect(url_for('usuarios_page'))

    empresa_id = empresa.get('id') if empresa else None
    dominio = normalize_domain((empresa or {}).get('dominio_email') or empresa_dominio)

    # Regra da Vi: só podem existir 2 Administradores Supremos no sistema.
    # Uma suprema pode transformar outro usuário em supremo, desde que o limite continue sendo 2.
    requested_super = (perfil == 'super_admin')
    existing_super_ids = [int(r['id']) for r in query_all("SELECT id FROM users WHERE is_super_admin=1 OR lower(perfil)='super_admin'")]
    current_edit_id = int(rid) if rid and str(rid).isdigit() else None
    if requested_super:
        projected = set(existing_super_ids)
        if current_edit_id:
            projected.add(current_edit_id)
        else:
            projected.add(-999999)
        if len(projected) > 2:
            perfil = 'gestor'
            requested_super = False
            flash('Já existem 2 Administradores Supremos. O usuário foi salvo como Gestor para manter a regra das duas cadeiras.', 'warning')
    is_super = 1 if requested_super and current_user_is_super_admin() else 0
    permissions = request.form.getlist('permissions')
    if perfil == 'super_admin':
        permissions = ALL_PERMISSIONS
    # Para outros perfis, usa o que foi marcado nos checkboxes da tela.
    # Se nenhum checkbox foi enviado (form antigo sem checkboxes), usa o padrão do perfil.
    if not permissions and perfil in ROLE_PERMISSIONS:
        permissions = ROLE_PERMISSIONS.get(perfil, [])
    permissions = normalize_permissions(permissions)
    if not nome:
        flash('Preencha o nome do usuário.', 'danger')
        return redirect(url_for('usuarios_page'))
    if not email_user:
        email_user = unique_email_for_domain(nome, dominio, ignore_user_id=rid)
        flash(f'Login sugerido automaticamente: {email_user}', 'info')
    elif dominio and not email_user.endswith('@' + dominio):
        # Corrige automaticamente para o domínio da sede, evitando usuário cair na empresa errada.
        old_email = email_user
        email_user = unique_email_for_domain(nome, dominio, ignore_user_id=rid)
        flash(f'O e-mail informado não batia com o domínio da empresa. Ajustei de {old_email} para {email_user}.', 'warning')
    else:
        conflict = query_one('SELECT id FROM users WHERE lower(email)=lower(?)' + (' AND id<>?' if rid else ''), (email_user, rid) if rid else (email_user,))
        if conflict:
            email_user = unique_email_for_domain(nome, dominio, ignore_user_id=rid)
            flash(f'Esse login já existia. Sugeri e salvei como {email_user}.', 'warning')
    if not empresa_id:
        flash('Não encontrei empresa/domínio para vincular o usuário. Cadastre ou informe um domínio.', 'danger')
        return redirect(url_for('usuarios_page'))
    ensure_company_storage(empresa_id)
    if rid:
        if not current_user_is_super_admin() and not owned_by_current_company('users', rid):
            flash('Você não pode editar usuário de outra empresa.', 'danger')
            return redirect(url_for('usuarios_page'))
        if senha:
            execute('UPDATE users SET nome=?, email=?, senha_hash=?, perfil=?, empresa_id=?, is_super_admin=?, permissions=?, ativo=?, telefone=? WHERE id=?',
                    (nome, email_user, generate_password_hash(senha), perfil, empresa_id, is_super, json.dumps(permissions, ensure_ascii=False), ativo, telefone, rid))
        else:
            execute('UPDATE users SET nome=?, email=?, perfil=?, empresa_id=?, is_super_admin=?, permissions=?, ativo=?, telefone=? WHERE id=?',
                    (nome, email_user, perfil, empresa_id, is_super, json.dumps(permissions, ensure_ascii=False), ativo, telefone, rid))
        sincronizar_usuario_campo(rid, nome, email_user, telefone, empresa_id, perfil, ativo)
        # Salva assinatura se enviada
        arq_ass = request.files.get('assinatura')
        if arq_ass and arq_ass.filename:
            save_company_identity_file(arq_ass, 'assinatura.png', empresa_id)
        backup_company_data(empresa_id)
        flash('Usuário atualizado. Permissões e empresa ficaram salvas.', 'success')
    else:
        if not senha:
            senha = '123456'
        try:
            novo_user_id = execute('INSERT INTO users(nome,email,senha_hash,perfil,empresa_id,is_super_admin,permissions,ativo,criado_em,telefone) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (nome, email_user, generate_password_hash(senha), perfil, empresa_id, is_super, json.dumps(permissions, ensure_ascii=False), ativo, now_str(), telefone))
            sincronizar_usuario_campo(novo_user_id, nome, email_user, telefone, empresa_id, perfil, ativo)
            # Salva assinatura se enviada
            arq_ass = request.files.get('assinatura')
            if arq_ass and arq_ass.filename:
                save_company_identity_file(arq_ass, 'assinatura.png', empresa_id)
            backup_company_data(empresa_id)
            flash(f'Usuário criado. Login: {email_user}', 'success')
        except Exception as exc:
            flash(f'Não foi possível criar usuário: {exc}', 'danger')
    return redirect(url_for('usuarios_page'))

def usuarios_delete(rid):
    # Soft delete seguro: preserva auditoria/histórico e evita 500 no PostgreSQL.
    if not current_user_is_super_admin():
        return permission_denied_redirect('Somente a Administradora Suprema pode excluir usuários.')

    try:
        rid = int(rid or 0)
    except Exception:
        rid = 0

    if not rid:
        flash('Usuário inválido.', 'warning')
        return redirect(url_for('usuarios_page'))

    if int(session.get('user_id') or 0) == rid:
        flash('Você não pode excluir/desativar seu próprio usuário logado.', 'danger')
        return redirect(url_for('usuarios_page'))

    row_del = row_to_dict(query_one('SELECT id, empresa_id, email, ativo FROM users WHERE id=?', (rid,)))
    if not row_del:
        flash('Usuário não encontrado.', 'warning')
        return redirect(url_for('usuarios_page'))

    try:
        if table_has_column('users', 'ativo'):
            execute('UPDATE users SET ativo=0 WHERE id=?', (rid,))
        else:
            execute('DELETE FROM users WHERE id=?', (rid,))

        if row_del.get('empresa_id'):
            try:
                if table_has_column('campo_tecnicos', 'user_id'):
                    execute('UPDATE campo_tecnicos SET ativo=0 WHERE user_id=? AND COALESCE(empresa_id, ?) = ?', (rid, row_del.get('empresa_id'), row_del.get('empresa_id')))
                if row_del.get('email'):
                    execute("UPDATE campo_tecnicos SET ativo=0 WHERE lower(trim(COALESCE(email,'')))=lower(trim(?)) AND COALESCE(empresa_id, ?) = ?", (row_del.get('email'), row_del.get('empresa_id'), row_del.get('empresa_id')))
            except Exception as exc:
                print('Não foi possível desativar técnico vinculado ao usuário:', exc)
            backup_company_data(row_del.get('empresa_id'))
        clear_view_cache()
        flash('Usuário desativado com segurança.', 'success')
    except Exception as exc:
        app_logger().exception('Falha ao desativar usuário %s', rid)
        flash(f'Não foi possível desativar o usuário: {exc}', 'danger')

    return redirect(url_for('usuarios_page'))


def register_routes(app):
    from app.auth import password_reset

    for path, endpoint, view, methods in [
        ('/campo/login', 'campo_login', campo_login, ['GET', 'POST']),
        ('/login', 'login', login, ['GET', 'POST']),
        ('/logout', 'logout', logout, ['GET']),
        ('/historico/apagar-tudo', 'historico_apagar_tudo', historico_apagar_tudo, ['POST']),
        ('/historico', 'historico_page', historico_page, ['GET']),
        ('/empresa/contexto/<int:empresa_id>', 'empresa_contexto', empresa_contexto, ['GET']),
        ('/visao-global', 'visao_global', visao_global, ['GET']),
        ('/ops/jobs', 'ops_jobs', ops_jobs, ['GET']),
        ('/usuarios', 'usuarios_page', usuarios_page, ['GET']),
        ('/empresas/save', 'empresas_save', empresas_save, ['POST']),
        ('/empresas/update/<int:empresa_id>', 'empresas_update', empresas_update, ['POST']),
        ('/usuarios/save', 'usuarios_save', usuarios_save, ['POST']),
        ('/usuarios/delete/<int:rid>', 'usuarios_delete', usuarios_delete, ['POST']),
        ('/esqueci-senha', 'esqueci_senha', password_reset.esqueci_senha, ['GET', 'POST']),
        ('/redefinir-senha/<token>', 'redefinir_senha', password_reset.redefinir_senha, ['GET', 'POST']),
    ]:
        app.add_url_rule(path, endpoint, view, methods=methods)
