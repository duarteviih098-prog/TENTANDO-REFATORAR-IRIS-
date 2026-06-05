"""Rota do técnico em campo (/os/<id>/campo/<token>)."""
import hmac
import json

from flask import render_template, request

from app.campo.routes_common import execute, get_conn, query_one
from app.campo.services import (
    _campo_save_images,
    _campo_valid_files,
    campo_evento_registrar,
    campo_mesmo_tecnico,
    campo_tecnico_por_token,
    campo_token_for,
)
from app.os.services import prepare_os_row_for_template
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, elapsed_label, only_time_str, time_diff_minutes
from app.shared.rows import row_to_dict


def campo_tecnico(rid, token):
    row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
    if not row:
        return render_template('campo_tecnico.html', erro='O.S. não encontrada.', row=None), 404
    empresa_id = row.get('empresa_id') or 0
    expected = campo_token_for(rid, empresa_id)
    if not hmac.compare_digest(str(token or ''), expected):
        return render_template('campo_tecnico.html', erro='Link inválido ou expirado.', row=None), 403

    tecnico_token = request.values.get('tecnico_token') or request.args.get('tecnico_token') or ''
    tecnico_app = campo_tecnico_por_token(tecnico_token, empresa_id) if tecnico_token else {}

    def _img_count(row_dict):
        try:
            return len(json.loads(row_dict.get('imagens') or '[]'))
        except Exception:
            return 0

    if request.method == 'POST':
        acao = request.form.get('acao')
        if not acao:
            if request.form.get('campo_problema') and request.form.get('servico_executado'):
                acao = 'finalizar'
            else:
                acao = 'salvar'
        agora = br_now()
        now_hora = agora.strftime('%H:%M')
        now_full = agora.strftime('%d/%m/%Y %H:%M')

        status = row.get('status') or 'Aberta'
        finalizada = row.get('finalizada') or 'Não'
        data_inicio = only_time_str(row.get('data_inicio'))
        data_fim = only_time_str(row.get('data_fim'))
        acumulado = int(row.get('acumulado_minutos') or 0)

        # Helper: adiciona evento ao historico_pausas (JSON)
        # Sempre lê direto do banco para evitar duplicação com dados stale
        def _hist_add(acao_hist, motivo=''):
            try:
                r_atual = row_to_dict(query_one('SELECT historico_pausas FROM os_ordens WHERE id=?', (rid,))) or {}
                hist = json.loads(r_atual.get('historico_pausas') or '[]')
            except Exception:
                hist = []
            evento = {'acao': acao_hist, 'quando': now_full}
            if motivo:
                evento['motivo'] = motivo
            if acao_hist == 'iniciado' and any(e.get('acao') == 'iniciado' for e in hist):
                return
            if acao_hist == 'finalizado' and any(e.get('acao') == 'finalizado' for e in hist):
                return
            hist.append(evento)
            execute('UPDATE os_ordens SET historico_pausas=? WHERE id=?',
                    (json.dumps(hist, ensure_ascii=False), rid))

        try:
            imagens = json.loads(row.get('imagens') or '[]')
        except Exception:
            imagens = []

        if acao == 'iniciar':
            if finalizada == 'Sim':
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')

            responsavel_atual = str(row.get('responsavel') or '').strip()
            if responsavel_atual and tecnico_app and not campo_mesmo_tecnico(responsavel_atual, tecnico_app):
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro=f'Esta O.S. já foi assumida por {responsavel_atual}.')

            # data_inicio guarda data+hora completa para rastreio
            if not data_inicio or str(status).strip().lower() == 'pausada':
                data_inicio = now_full
            status = 'Em andamento'
            finalizada = 'Não'
            data_fim = ''
            responsavel_novo = responsavel_atual
            if tecnico_app:
                responsavel_novo = (tecnico_app.get('nome') or tecnico_app.get('email') or responsavel_atual or '').strip()

            if tecnico_app:
                conn = get_conn()
                try:
                    cur = conn.execute("""UPDATE os_ordens
                                          SET responsavel=?, status=?, finalizada=?, data_inicio=?, data_fim=?
                                          WHERE id=? AND COALESCE(empresa_id, ?) = ?
                                            AND (TRIM(COALESCE(responsavel,'')) = ''
                                                 OR lower(trim(COALESCE(responsavel,''))) = lower(trim(?))
                                                 OR lower(trim(COALESCE(responsavel,''))) = lower(trim(?)))""",
                                       (responsavel_novo, status, finalizada, data_inicio, data_fim, rid, empresa_id, empresa_id, tecnico_app.get('nome') or '', tecnico_app.get('email') or ''))
                    changed = getattr(cur, 'rowcount', None)
                    conn.commit()
                finally:
                    try: conn.close()
                    except Exception: pass
                if changed == 0:
                    row_bloqueada = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or row
                    dono = row_bloqueada.get('responsavel') or 'outro técnico'
                    return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row_bloqueada), token=token, tecnico_token=tecnico_token, erro=f'Essa O.S. já foi assumida por {dono}.')
            else:
                execute("""UPDATE os_ordens SET status=?, finalizada=?, data_inicio=?, data_fim=? WHERE id=?""", (status, finalizada, data_inicio, data_fim, rid))

            # Registra no histórico: só "iniciado" na primeira vez
            # "retomado" é gravado exclusivamente pela ação retomar
            row_atual = row_to_dict(query_one('SELECT historico_pausas FROM os_ordens WHERE id=?', (rid,))) or {}
            hist_atual = json.loads(row_atual.get('historico_pausas') or '[]')
            if not any(e.get('acao') == 'iniciado' for e in hist_atual):
                _hist_add('iniciado', f'Responsável: {responsavel_novo or "não informado"}')
            campo_evento_registrar(rid, empresa_id, 'iniciar', f"Responsável: {responsavel_novo or 'não informado'}.")
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, sucesso='Atendimento iniciado. O tempo começou a contar.', erro=None)

        if acao == 'pausar':
            if finalizada == 'Sim':
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')
            if data_inicio and str(status).strip().lower() == 'em andamento':
                acumulado += time_diff_minutes(only_time_str(data_inicio), now_hora) or 0
            status = 'Pausada'
            finalizada = 'Não'
            data_fim = now_full  # data+hora completa
            motivo_pausa = str(request.form.get('motivo_pausa') or '').strip()
            execute("""UPDATE os_ordens
                       SET status=?, finalizada=?, data_fim=?, acumulado_minutos=?, motivo_pausa=?
                       WHERE id=?""",
                    (status, finalizada, data_fim, acumulado, motivo_pausa, rid))
            _hist_add('pausado', motivo_pausa)
            campo_evento_registrar(rid, empresa_id, 'pausar', motivo_pausa or '')
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, sucesso='Atendimento pausado. O contador foi interrompido.', erro=None)

        if acao == 'justificar_atraso':
            motivo_atraso = str(request.form.get('motivo_atraso') or '').strip()
            execute('UPDATE os_ordens SET motivo_atraso=? WHERE id=?', (motivo_atraso, rid))
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, sucesso='Justificativa registrada com sucesso.', erro=None)

        if acao == 'retomar':
            if finalizada == 'Sim':
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')
            status = 'Em andamento'
            finalizada = 'Não'
            data_inicio = now_full  # data+hora completa
            data_fim = ''
            execute("""UPDATE os_ordens
                       SET status=?, finalizada=?, data_inicio=?, data_fim=?
                       WHERE id=?""",
                    (status, finalizada, data_inicio, data_fim, rid))
            _hist_add('retomado')
            campo_evento_registrar(rid, empresa_id, 'retomar', '')
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, sucesso='Atendimento retomado. O tempo voltou a contar.', erro=None)

        if acao == 'finalizar' or (acao == 'salvar' and request.form.get('campo_problema') and request.form.get('servico_executado')):
            if finalizada == 'Sim' or str(status).strip().lower() in ('finalizada', 'finalizado'):
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')
            acao = 'finalizar'

        if acao == 'finalizar':
            problema = (request.form.get('campo_problema') or '').strip()
            servico = (request.form.get('servico_executado') or '').strip()
            funcionando = (request.form.get('campo_funcionando') or '').strip()
            troca = 'Sim' if str(request.form.get('troca_componentes') or '').lower() in ('sim','s','1','true','on') else 'Não'
            componentes = (request.form.get('componentes_descricao') or '').strip() if troca == 'Sim' else ''
            teve_terceiro = 'Sim' if str(request.form.get('teve_terceiro') or '').lower() in ('sim','s','1','true','on') else 'Não'
            quem_foi_terceiro = (request.form.get('quem_foi_terceiro') or '').strip() if teve_terceiro == 'Sim' else ''
            fotos_enviadas = _campo_valid_files('imagens') + _campo_valid_files('foto1') + _campo_valid_files('foto2') + _campo_valid_files('foto3')

            if not problema:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Informe qual foi o problema.')
            if not servico:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Informe o que foi feito.')
            if funcionando not in ('Sim', 'Não'):
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Informe se já está funcionando.')

            imagens_existentes = [img for img in (imagens or []) if str(img or '').strip()]
            total_fotos_previsto = len(imagens_existentes) + len(fotos_enviadas)
            if total_fotos_previsto < 2:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro=f'Envie pelo menos 2 fotos para finalizar. Recebidas agora: {len(fotos_enviadas)}.')
            if len(fotos_enviadas) > 3 or total_fotos_previsto > 3:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Envie no máximo 3 fotos no total.')

            novas_fotos = _campo_save_images(fotos_enviadas, empresa_id)
            imagens = imagens_existentes + novas_fotos
            if len(imagens) < 2:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro=f'Não consegui salvar as fotos no servidor. Verifique sua conexão e tente novamente. Salvas: {len(imagens)}.')

            if str(status).strip().lower() != 'pausada' and data_inicio:
                acumulado += time_diff_minutes(only_time_str(data_inicio), now_hora) or 0
            if not data_inicio:
                data_inicio = now_full

            status = 'Finalizada'
            finalizada = 'Sim'
            data_fim = now_full  # data+hora completa
            execute("""UPDATE os_ordens
                       SET status=?, finalizada=?, data_inicio=?, data_fim=?, acumulado_minutos=?,
                           servico_executado=?, troca_componentes=?, componentes_descricao=?, imagens=?,
                           campo_problema=?, campo_funcionando=?, campo_finalizado_em=?,
                           teve_terceiro=?, quem_foi_terceiro=?
                       WHERE id=?""",
                    (status, finalizada, data_inicio, data_fim, acumulado, servico, troca, componentes,
                     json.dumps(imagens, ensure_ascii=False), problema, funcionando, now_full,
                     teve_terceiro, quem_foi_terceiro, rid))
            _hist_add('finalizado', f'Tempo total: {elapsed_label("", "", acumulado, running=False)}')
            campo_evento_registrar(rid, empresa_id, 'finalizar', f"Tempo total: {elapsed_label('', '', acumulado, running=False)}.")
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, sucesso='Atendimento finalizado com sucesso.', erro=None)

    return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro=None)
