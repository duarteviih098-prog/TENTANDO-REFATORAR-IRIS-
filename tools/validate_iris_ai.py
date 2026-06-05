"""Validação rápida do contexto Iris (sem chamar API externa)."""
import json
import os
import sys
import tempfile

from werkzeug.security import generate_password_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fd, path = tempfile.mkstemp(suffix='.db')
os.close(_fd)
os.environ['IRIS_TEST_DB'] = path
os.environ['SECRET_KEY'] = 'test-secret-key-with-32-chars-minimum-ok'
os.environ.pop('DATABASE_URL', None)

from app.db.migration_runner import apply_pending_migrations

apply_pending_migrations()

from app.auth.constants import ALL_PERMISSIONS
from app.db import execute
from app.exports.iris_data import _iris_collect_context
from app.integrations.iris import _iris_context_summary
from flask import session
from app import app

eid = execute(
    "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES ('Val','C','v.local',1,'01/01/2026')"
)
uid = execute(
    """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
       VALUES (?,?,?,?,?,1,'01/01/2026',?,0)""",
    ('Admin', 'a@v.local', generate_password_hash('x'), 'admin', json.dumps(ALL_PERMISSIONS), eid),
)
for args in (
    ('05/04/2026', 'Bombeamento', 'Bomba 1', 'Em andamento', 'Nao', 'Sim', 'Selo mecanico', 'Joao'),
    ('10/04/2026', 'Bombeamento', 'Bomba 1', 'Finalizada', 'Sim', 'Sim', 'Selo mecanico', 'Joao'),
    ('12/04/2026', 'ETA', 'Motor 2', 'Atrasada', 'Nao', 'Nao', '', 'Maria'),
):
    execute(
        """INSERT INTO os_ordens(data,sistema,equipamento,status,finalizada,troca_componentes,componentes_descricao,responsavel,empresa_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (*args, eid),
    )
execute(
    """INSERT INTO pagamentos(fornecedor,valor,status,pagamento_mes,empresa_id,descricao_servico)
       VALUES ('Fornecedor A','1000','Pago','04/2026',?,'Servico')""",
    (eid,),
)

with app.test_request_context():
    session['empresa_id'] = eid
    session['user_id'] = uid
    session['selected_empresa_id'] = eid
    ctx = _iris_collect_context('04/2026')
    assert ctx['os_total'] == 3, ctx
    assert ctx['trocas_total'] == 2, ctx
    assert ctx['by_component'][0][0] == 'Selo mecanico', ctx['by_component']
    assert ctx['by_system_os'][0][0] == 'Bombeamento', ctx['by_system_os']
    assert ctx['equip_reincidentes'][0][0] == 'Bomba 1', ctx['equip_reincidentes']
    summary = _iris_context_summary('04/2026')
    assert 'Bombeamento' in summary
    assert 'Selo mecanico' in summary
    print('OK contexto Iris validado')
    print(summary)
