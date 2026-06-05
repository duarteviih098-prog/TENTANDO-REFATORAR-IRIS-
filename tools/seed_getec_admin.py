#!/usr/bin/env python3
"""Cria empresa e administrador inicial para primeiro deploy (Getec).

Uso SQLite:
  python tools/bootstrap_db.py --db-path app.db
  python tools/seed_getec_admin.py --db-path app.db --email admin@getec.local --senha "SenhaSegura123"

Uso Postgres (Render / Supabase):
  set DATABASE_URL=postgresql://...
  python tools/bootstrap_db.py
  python tools/seed_getec_admin.py --nome Getec --email admin@getec.com.br --senha "SenhaSegura123"
"""
import argparse
import json
import os
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def seed_getec_admin(
    *,
    nome='Getec',
    cidade='',
    dominio='getec.local',
    admin_nome='Administrador Getec',
    email='admin@getec.local',
    senha='',
    super_admin=True,
):
    if not senha or len(senha) < 8:
        raise SystemExit('Informe --senha com pelo menos 8 caracteres.')

    from app.auth.constants import ALL_PERMISSIONS
    from app.db import ensure_db, execute, query_one
    from app.shared.formatters import now_str

    ensure_db()
    email = email.strip().lower()
    dominio = dominio.strip().lower().lstrip('@')
    existente_user = query_one('SELECT id FROM users WHERE lower(email)=lower(?)', (email,))
    if existente_user:
        raise SystemExit(f'Usuário já existe: {email}')

    empresa = query_one('SELECT id FROM empresas WHERE lower(nome)=lower(?)', (nome,))
    if empresa:
        empresa_id = empresa['id']
        print(f'Empresa existente reutilizada: {nome} (id={empresa_id})')
    else:
        empresa_id = execute(
            "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,?)",
            (nome, cidade, dominio, now_str()),
        )
        print(f'Empresa criada: {nome} (id={empresa_id})')

    permissions = json.dumps(ALL_PERMISSIONS)
    user_id = execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES (?,?,?,?,?,1,?,?,?)""",
        (
            admin_nome,
            email,
            generate_password_hash(senha),
            'admin',
            permissions,
            now_str(),
            empresa_id,
            1 if super_admin else 0,
        ),
    )
    print(f'Admin criado: {email} (id={user_id})')
    print('Próximo passo: faça login e altere a senha no primeiro acesso.')


def main():
    parser = argparse.ArgumentParser(description='Seed empresa Getec + admin inicial')
    parser.add_argument('--db-path', help='SQLite local (ignorado se DATABASE_URL estiver definida)')
    parser.add_argument('--nome', default='Getec', help='Nome da empresa')
    parser.add_argument('--cidade', default='', help='Cidade da empresa')
    parser.add_argument('--dominio', default='getec.local', help='Domínio de e-mail da empresa')
    parser.add_argument('--admin-nome', default='Administrador Getec', help='Nome do usuário admin')
    parser.add_argument('--email', required=True, help='E-mail do admin')
    parser.add_argument('--senha', required=True, help='Senha inicial (mín. 8 caracteres)')
    parser.add_argument('--no-super-admin', action='store_true', help='Não marcar como super admin')
    args = parser.parse_args()

    if args.db_path:
        os.environ['IRIS_TEST_DB'] = str(Path(args.db_path).resolve())
        os.environ.pop('DATABASE_URL', None)

    seed_getec_admin(
        nome=args.nome,
        cidade=args.cidade,
        dominio=args.dominio,
        admin_nome=args.admin_nome,
        email=args.email,
        senha=args.senha,
        super_admin=not args.no_super_admin,
    )


if __name__ == '__main__':
    main()
