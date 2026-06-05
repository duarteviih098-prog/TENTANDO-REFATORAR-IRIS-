"""Registro das rotas Campo."""
from app.campo.routes_api import (
    api_campo_evento_teste,
    api_campo_evento_visto,
    api_campo_eventos,
    api_campo_feed_state,
    api_campo_gps_debug,
    api_campo_localizacao,
    api_campo_tecnico_foto,
    api_campo_tecnico_foto_delete,
    api_campo_tecnicos_mapa,
    api_mobile_bomba_save,
    api_mobile_comb_save,
    api_mobile_pag_save,
)
from app.campo.routes_pages import (
    campo_app,
    campo_app_empty,
    campo_page,
    campo_short_app,
    campo_template_save,
    campo_tecnico_delete,
    campo_tecnico_revogar_token,
    campo_tecnico_save,
    campo_whatsapp,
    campo_whatsapp_equipe,
    gestor_app,
)
from app.campo.routes_tecnico import campo_tecnico


def register_routes(app):
    rules = [
        ('/api/campo/feed-state', 'api_campo_feed_state', api_campo_feed_state, ['GET']),
        ('/api/campo/eventos', 'api_campo_eventos', api_campo_eventos, ['GET']),
        ('/api/campo/eventos/<int:eid>/visto', 'api_campo_evento_visto', api_campo_evento_visto, ['POST']),
        ('/api/campo/eventos/teste', 'api_campo_evento_teste', api_campo_evento_teste, ['POST']),
        ('/gestor/app', 'gestor_app', gestor_app, ['GET']),
        ('/api/mobile/pagamentos/save', 'api_mobile_pag_save', api_mobile_pag_save, ['POST']),
        ('/api/mobile/combustivel/save', 'api_mobile_comb_save', api_mobile_comb_save, ['POST']),
        ('/api/mobile/bomba/save', 'api_mobile_bomba_save', api_mobile_bomba_save, ['POST']),
        ('/campo', 'campo_page', campo_page, ['GET']),
        ('/campo/tecnico/save', 'campo_tecnico_save', campo_tecnico_save, ['POST']),
        ('/campo/tecnico/revogar/<int:rid>', 'campo_tecnico_revogar_token', campo_tecnico_revogar_token, ['POST']),
        ('/campo/tecnico/delete/<int:rid>', 'campo_tecnico_delete', campo_tecnico_delete, ['POST']),
        ('/campo/templates/save', 'campo_template_save', campo_template_save, ['POST']),
        ('/c/<token>', 'campo_short_app', campo_short_app, ['GET', 'POST']),
        ('/campo/app/', 'campo_app_empty', campo_app_empty, ['GET', 'POST']),
        ('/campo/app/<path:token>', 'campo_app', campo_app, ['GET', 'POST']),
        ('/campo/whatsapp/<int:rid>', 'campo_whatsapp', campo_whatsapp, ['GET']),
        ('/campo/whatsapp/equipe/<int:rid>', 'campo_whatsapp_equipe', campo_whatsapp_equipe, ['GET']),
        ('/os/<int:rid>/campo/<token>', 'campo_tecnico', campo_tecnico, ['GET', 'POST']),
        ('/api/campo/localizacao', 'api_campo_localizacao', api_campo_localizacao, ['POST']),
        ('/api/campo/gps-debug', 'api_campo_gps_debug', api_campo_gps_debug, ['GET']),
        ('/api/campo/tecnicos-mapa', 'api_campo_tecnicos_mapa', api_campo_tecnicos_mapa, ['GET']),
        ('/api/campo/tecnico/foto', 'api_campo_tecnico_foto', api_campo_tecnico_foto, ['POST']),
        ('/api/campo/tecnico/foto', 'api_campo_tecnico_foto_delete', api_campo_tecnico_foto_delete, ['DELETE']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
