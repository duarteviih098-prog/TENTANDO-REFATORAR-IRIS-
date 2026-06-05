"""Monta a aplicação Flask e registra todos os módulos."""
from app.auth import register_auth, user_has
from app.campo import register_campo
from app.combustivel import register_combustivel
from app.controle import register_controle
from app.custos import register_custos
from app.exports import register_exports
from app.factory import create_app
from app.integrations import register_integrations
from app.inventario import register_inventario
from app.os import register_os
from app.outlook import register_outlook
from app.pagamentos import register_pagamentos
from app.shared import register_shared
from app.shared.formatters import br_date, br_money, format_phone_br
from app.storage import register_storage


def wire_app(application):
    from app.observability import register_observability

    register_observability(application)
    register_auth(application)
    register_storage(application)
    register_shared(application)
    register_controle(application)
    register_combustivel(application)
    register_pagamentos(application)
    register_custos(application)
    register_os(application)
    register_campo(application)
    register_inventario(application)
    register_outlook(application)
    register_exports(application)
    register_integrations(application)

    application.jinja_env.filters['br_money'] = br_money
    application.jinja_env.filters['br_date'] = br_date
    application.jinja_env.filters['phone_br'] = format_phone_br
    application.jinja_env.globals['user_has'] = user_has
    return application


def create_wired_app():
    application = create_app()
    wire_app(application)
    return application


app = create_wired_app()


def startup():
    from app.db import ensure_db, ensure_indexes
    from app.outlook.services import maybe_start_monitor_worker

    ensure_db()
    ensure_indexes()
    maybe_start_monitor_worker()


startup()

__all__ = ['app', 'wire_app', 'create_wired_app', 'startup']
