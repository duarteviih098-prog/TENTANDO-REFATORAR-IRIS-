"""APIs Campo / gestor mobile."""
import os

from flask import jsonify, request

from app.auth.decorators import require_permission
from app.campo.routes_common import (
    _flask_app,
    current_company_id,
    execute,
    query_all,
    query_one,
)
from app.campo.services import (
    _api_campo_guard,
    campo_evento_registrar,
    campo_numero_visivel,
    campo_tecnico_por_token,
    ensure_campo_eventos_table,
    get_tecnico_from_token,
    table_columns,
)
from app.combustivel.services import save_combustivel
from app.controle.services import save_bomba
from app.pagamentos.services import save_pagamento
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now
from app.shared.queries import safe_int_id as _safe_int_id
from app.shared.rows import row_to_dict


def api_campo_feed_state():
    """Estado leve da fila de campo para polling inteligente."""
    try:
        empresa_id = current_company_id()
        # Versão baseada em os_ordens + campo_eventos pendentes
        sql_os = "SELECT COUNT(*) AS total, MAX(id) AS max_id FROM os_ordens"
        params_os = []
        if empresa_id:
            sql_os += " WHERE empresa_id=?"
            params_os.append(empresa_id)
        row_os = row_to_dict(query_one(sql_os, tuple(params_os))) or {}
        total = int(row_os.get('total') or 0)
        max_id = int(row_os.get('max_id') or 0)

        # Inclui max id de eventos pendentes para detectar novos popups
        try:
            ensure_campo_eventos_table()
            sql_ev = "SELECT COUNT(*) AS ev_total, MAX(id) AS ev_max FROM campo_eventos WHERE COALESCE(status,'novo')='novo'"
            params_ev = []
            if empresa_id:
                sql_ev += " AND (empresa_id=? OR empresa_id IS NULL OR empresa_id=0)"
                params_ev.append(empresa_id)
            row_ev = row_to_dict(query_one(sql_ev, tuple(params_ev))) or {}
            ev_total = int(row_ev.get('ev_total') or 0)
            ev_max = int(row_ev.get('ev_max') or 0)
        except Exception:
            ev_total = 0
            ev_max = 0

        version = f'{total}-{max_id}-{ev_total}-{ev_max}'
        return jsonify({'ok': True, 'total': total, 'max_id': max_id, 'ev_pending': ev_total, 'version': version})
    except Exception as exc:
        return jsonify({'ok': False, 'total': 0, 'max_id': 0, 'version': '0-0', 'erro': str(exc)}), 200



def api_campo_eventos():
    """Eventos de campo para popup do operador.

    Retorna JSON mesmo quando a sessão expirou. Assim o JavaScript não morre
    tentando interpretar uma página de login como JSON.
    """
    guard = _api_campo_guard('eventos')
    if guard:
        return guard
    empresa_id = current_company_id()
    try:
        ensure_campo_eventos_table()
        sql = """SELECT ce.id, ce.os_id, ce.empresa_id, ce.tipo, ce.titulo, ce.mensagem,
                        ce.status, ce.criado_em,
                        os.status AS os_status,
                        os.finalizada AS os_finalizada,
                        os.numero_os AS os_numero,
                        COALESCE(NULLIF(TRIM(os.numero_os), ''), CAST(os.id AS TEXT), CAST(ce.os_id AS TEXT)) AS numero_visivel
                 FROM campo_eventos ce
                 LEFT JOIN os_ordens os ON os.id=ce.os_id
                 WHERE COALESCE(ce.status,'novo')='novo'"""
        params = []
        if empresa_id:
            sql += " AND (ce.empresa_id=? OR os.empresa_id=? OR ce.empresa_id IS NULL OR ce.empresa_id=0)"
            params.extend([empresa_id, empresa_id])
        sql += " ORDER BY ce.id ASC LIMIT 30"
        rows = [dict(r) for r in query_all(sql, tuple(params))]
        # Recalcula numero_visivel via Python para garantir consistência
        for row in rows:
            os_row = {'id': row.get('os_id'), 'numero_os': row.get('os_numero')}
            row['numero_visivel'] = campo_numero_visivel(os_row, row.get('os_id'))
        return jsonify({'ok': True, 'eventos': rows})
    except Exception as exc:
        _flask_app().logger.exception('Falha ao buscar eventos de campo')
        return jsonify({'ok': False, 'eventos': [], 'erro': str(exc)}), 200




def api_campo_evento_teste():
    """Disparo manual para validar o popup sem depender do celular."""
    guard = _api_campo_guard('eventos')
    if guard:
        return guard
    empresa_id = current_company_id()
    row = row_to_dict(query_one('SELECT id, numero_os, empresa_id FROM os_ordens WHERE (? IS NULL OR empresa_id=?) ORDER BY id DESC LIMIT 1', (empresa_id, empresa_id)))
    if not row:
        return jsonify({'ok': False, 'erro': 'Nenhuma O.S. encontrada para testar.'}), 200
    eid = campo_evento_registrar(row['id'], row.get('empresa_id') or empresa_id, 'iniciar', '')
    return jsonify({'ok': True, 'event_id': eid})




@require_permission('edit_pagamentos')
def api_mobile_pag_save():
    try:
        rid = _safe_int_id(request.form.get('id'))
        saved_id = save_pagamento(request.form, request.files, rid)
        clear_view_cache()
        return jsonify({'ok': True, 'id': saved_id})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('edit_combustivel')
def api_mobile_comb_save():
    try:
        rid = request.form.get('id') or None
        save_combustivel(request.form, rid)
        clear_view_cache()
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('edit_controle')
def api_mobile_bomba_save():
    try:
        rid = request.form.get('id') or None
        save_bomba(request.form, rid)
        clear_view_cache()
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


def api_campo_localizacao():
    """Recebe lat/lng do técnico em campo e atualiza na tabela campo_tecnicos."""
    try:
        data = request.get_json(silent=True) or {}
        lat = data.get('lat') or request.form.get('lat')
        lng = data.get('lng') or request.form.get('lng')
        os_id = data.get('os_id') or request.form.get('os_id')
        tecnico_token_qs = request.args.get('tecnico_token') or data.get('tecnico_token') or ''

        if not lat or not lng:
            return jsonify({'ok': False, 'error': 'lat/lng obrigatórios'}), 400

        tecnico_id = None

        # 1. Pelo tecnico_token (token do técnico em campo_tecnicos.token)
        if tecnico_token_qs:
            tc = campo_tecnico_por_token(tecnico_token_qs)
            if tc:
                tecnico_id = tc.get('id')

        # 2. Pelo responsavel da OS
        if not tecnico_id and os_id:
            try:
                os_row = row_to_dict(query_one(
                    'SELECT responsavel, empresa_id FROM os_ordens WHERE id=? LIMIT 1', (int(os_id),)
                ) or {})
                resp = os_row.get('responsavel') or ''
                if resp:
                    ct = row_to_dict(query_one(
                        'SELECT id FROM campo_tecnicos WHERE (nome=? OR email=?) AND ativo=1 LIMIT 1',
                        (resp, resp)
                    ) or {})
                    if ct:
                        tecnico_id = ct.get('id')
            except Exception:
                pass

        if not tecnico_id:
            _flask_app().logger.error('GPS ignorado: tecnico_token=%s os_id=%s responsavel_tentado=%s',
                           tecnico_token_qs, os_id,
                           (query_one('SELECT responsavel FROM os_ordens WHERE id=? LIMIT 1', (int(os_id),)) or {}).get('responsavel','?') if os_id else '?')
            return jsonify({'ok': True, 'warn': 'Tecnico nao identificado', 'token_recebido': tecnico_token_qs[:8] if tecnico_token_qs else 'vazio'})

        agora_iso = br_now().strftime('%Y-%m-%d %H:%M:%S')
        execute(
            'UPDATE campo_tecnicos SET campo_lat=?, campo_lng=?, campo_loc_updated_at=?, campo_os_id=? WHERE id=?',
            (float(lat), float(lng), agora_iso, int(os_id) if os_id else None, tecnico_id)
        )
        _flask_app().logger.warning('GPS salvo OK: tecnico_id=%s lat=%s lng=%s token=%s', tecnico_id, lat, lng, tecnico_token_qs[:8] if tecnico_token_qs else 'vazio')
        return jsonify({'ok': True})
    except Exception as exc:
        _flask_app().logger.error('api_campo_localizacao erro: %s', exc)
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('view_os')
def api_campo_gps_debug():
    """Diagnóstico do GPS — ver o que está na tabela campo_tecnicos."""
    try:
        empresa_id = current_company_id()
        # Ver colunas da tabela
        cols = list(table_columns('campo_tecnicos'))
        # Ver todos os técnicos ativos
        rows = [row_to_dict(r) for r in (query_all(
            'SELECT id, nome, email, ativo, token, campo_lat, campo_lng, campo_loc_updated_at, campo_os_id FROM campo_tecnicos WHERE empresa_id=? LIMIT 10',
            (empresa_id,)
        ) or [])]
        return jsonify({
            'ok': True,
            'empresa_id': empresa_id,
            'colunas_disponiveis': cols,
            'tem_campo_lat': 'campo_lat' in cols,
            'tem_campo_lng': 'campo_lng' in cols,
            'tem_campo_loc_updated_at': 'campo_loc_updated_at' in cols,
            'tecnicos': rows,
            'total': len(rows)
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)})




@require_permission('view_os')
def api_campo_tecnicos_mapa():
    """Retorna posições dos técnicos ativos em campo para o mapa do dashboard."""
    try:
        empresa_id = current_company_id()
        from datetime import timedelta as _td
        # Formato ISO para comparação correta no PostgreSQL
        limite_iso = (br_now() - _td(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')

        where = """WHERE campo_lat IS NOT NULL AND campo_lng IS NOT NULL
                   AND campo_loc_updated_at IS NOT NULL AND campo_loc_updated_at != ''
                   AND campo_loc_updated_at > ? AND ativo=1"""
        params = [limite_iso]
        if empresa_id:
            where += ' AND empresa_id=?'
            params.append(empresa_id)

        rows = query_all(
            f'SELECT id, nome, email, campo_lat, campo_lng, campo_loc_updated_at, campo_os_id FROM campo_tecnicos {where}',
            tuple(params)
        )

        tecnicos = []
        for r in rows:
            r = row_to_dict(r)
            nome = r.get('nome') or r.get('email') or 'Técnico'
            # Iniciais para avatar
            partes = nome.strip().split()
            iniciais = (partes[0][0] + (partes[-1][0] if len(partes) > 1 else '')).upper()
            # Cor do avatar baseada no ID
            cores = ['#2563eb','#7c3aed','#059669','#d97706','#dc2626','#0891b2','#be185d']
            cor = cores[int(r.get('id') or 0) % len(cores)]
            # Info da O.S. ativa
            os_info = {}
            if r.get('campo_os_id'):
                os_row = row_to_dict(query_one(
                    'SELECT numero_os, sistema, equipamento, status FROM os_ordens WHERE id=?',
                    (r['campo_os_id'],)
                ) or {})
                if os_row:
                    os_info = {
                        'numero': os_row.get('numero_os') or r['campo_os_id'],
                        'sistema': os_row.get('sistema') or '',
                        'equipamento': os_row.get('equipamento') or '',
                        'status': os_row.get('status') or '',
                    }
            tecnicos.append({
                'id': r.get('id'),
                'nome': nome,
                'iniciais': iniciais,
                'cor': cor,
                'lat': r.get('campo_lat'),
                'lng': r.get('campo_lng'),
                'updated_at': r.get('campo_loc_updated_at') or '',
                'os': os_info,
                'foto_url': r.get('foto_perfil') or '',
            })

        return jsonify({'ok': True, 'tecnicos': tecnicos})
    except Exception as exc:
        return jsonify({'ok': False, 'tecnicos': [], 'error': str(exc)})




def api_campo_tecnico_foto():
    """Upload de foto de perfil do técnico (feito pelo próprio técnico no app de campo)."""
    tecnico = get_tecnico_from_token()
    if not tecnico:
        return jsonify({'ok': False, 'error': 'Não autenticado'}), 401
    tid = tecnico.get('id')
    if not tid:
        return jsonify({'ok': False, 'error': 'Técnico inválido'}), 400
    f = request.files.get('foto')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Nenhuma foto enviada'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.jpg','.jpeg','.png','.webp'):
        return jsonify({'ok': False, 'error': 'Formato inválido. Use JPG, PNG ou WEBP.'}), 400
    # Salva em static/fotos_perfil/
    pasta = os.path.join(_flask_app().static_folder, 'fotos_perfil')
    os.makedirs(pasta, exist_ok=True)
    nome_arquivo = f'tecnico_{tid}{ext}'
    caminho = os.path.join(pasta, nome_arquivo)
    f.save(caminho)
    url = f'/static/fotos_perfil/{nome_arquivo}'
    execute('UPDATE campo_tecnicos SET foto_perfil=? WHERE id=?', (url, tid))
    return jsonify({'ok': True, 'foto_url': url})


def api_campo_tecnico_foto_delete():
    """Remove foto de perfil do técnico."""
    tecnico = get_tecnico_from_token()
    if not tecnico:
        return jsonify({'ok': False, 'error': 'Não autenticado'}), 401
    tid = tecnico.get('id')
    foto = tecnico.get('foto_perfil') or ''
    if foto and foto.startswith('/static/fotos_perfil/'):
        caminho = os.path.join(_flask_app().static_folder, foto.lstrip('/static/'))
        try:
            os.remove(caminho)
        except OSError:
            pass
    execute('UPDATE campo_tecnicos SET foto_perfil=? WHERE id=?', ('', tid))
    return jsonify({'ok': True})


def api_campo_evento_visto(eid):
    guard = _api_campo_guard('eventos')
    if guard:
        return guard
    empresa_id = current_company_id()
    try:
        ensure_campo_eventos_table()
        if empresa_id:
            execute("""UPDATE campo_eventos SET status='visto'
                       WHERE id=? AND (empresa_id=? OR empresa_id IS NULL OR empresa_id=0)""", (eid, empresa_id))
        else:
            execute("UPDATE campo_eventos SET status='visto' WHERE id=?", (eid,))
    except Exception as exc:
        _flask_app().logger.exception('Falha ao marcar evento de campo como visto')
        return jsonify({'ok': False, 'erro': str(exc)}), 200
    return jsonify({'ok': True})
