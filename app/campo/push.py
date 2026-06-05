"""Web Push — VAPID, subscriptions e service worker."""
import json
import os

from flask import Response, jsonify, request

from app.auth.decorators import require_permission
from app.shared.formatters import (
    now_str,
)
from app.shared.rows import row_to_dict

VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '').strip()
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '').strip()
VAPID_CLAIMS_EMAIL = os.getenv('VAPID_CLAIMS_EMAIL', 'admin@iris.local').strip()


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin(user=None):
    from app.auth import current_user_is_super_admin as fn
    return fn(user)


def get_current_user():
    from app.auth import get_current_user as fn
    return fn()


def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)


def company_and(table):
    from app.auth import company_and as fn
    return fn(table)


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def get_conn():
    from app.db import get_conn as fn
    return fn()


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_db():
    from app.db import ensure_db as fn
    return fn()


def tenant_upload_dir(kind, empresa_id=None):
    from app.storage import tenant_upload_dir as fn
    return fn(kind, empresa_id=empresa_id)


def company_folder_name(empresa_id=None):
    from app.storage import company_folder_name as fn
    return fn(empresa_id)


def ensure_company_storage(empresa_id=None):
    from app.storage import ensure_company_storage as fn
    return fn(empresa_id)


def load_whatsapp_templates(empresa_id=None):
    from app.storage import load_whatsapp_templates as fn
    return fn(empresa_id)


def save_whatsapp_templates(items, empresa_id=None):
    from app.storage import save_whatsapp_templates as fn
    return fn(items, empresa_id=empresa_id)


def active_whatsapp_template(tipo, empresa_id=None):
    from app.storage import active_whatsapp_template as fn
    return fn(tipo, empresa_id)


def upload_file_to_supabase(file_storage, storage_path, content_type=None):
    from app.storage import upload_file_to_supabase as fn
    return fn(file_storage, storage_path, content_type)


def pagamentos_query_rows(*args, **kwargs):
    from app.pagamentos.services import pagamentos_query_rows as fn
    return fn(*args, **kwargs)
def _send_push(subscription_info, title, body, url='/'):
    """Envia Web Push para uma subscription. Retorna True se OK, 'gone' se expirada."""
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        print('_send_push: VAPID keys não configuradas.')
        return False
    try:
        from pywebpush import webpush
        data = json.dumps({'title': title, 'body': body, 'url': url}, ensure_ascii=False)
        webpush(
            subscription_info=subscription_info,
            data=data,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={'sub': f'mailto:{VAPID_CLAIMS_EMAIL}'}
        )
        print(f'_send_push OK: {title}')
        return True
    except Exception as exc:
        err = str(exc)
        print(f'_send_push falhou: {exc}')
        # 410 Gone = assinatura expirada/cancelada
        if '410' in err or 'unsubscribed or expired' in err or 'Gone' in err:
            return 'gone'
        return False




def _ensure_push_subscriptions_table():
    from app.db import USE_POSTGRES, ensure_column

    if USE_POSTGRES:
        execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER DEFAULT 0,
            tecnico_id INTEGER DEFAULT 0,
            tecnico_nome TEXT DEFAULT '',
            endpoint TEXT DEFAULT '',
            p256dh TEXT DEFAULT '',
            auth TEXT DEFAULT '',
            criado_em TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1
        )""")
    else:
        execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER DEFAULT 0,
            tecnico_id INTEGER DEFAULT 0,
            tecnico_nome TEXT DEFAULT '',
            endpoint TEXT DEFAULT '',
            p256dh TEXT DEFAULT '',
            auth TEXT DEFAULT '',
            criado_em TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1
        )""")
    try:
        ensure_column('push_subscriptions', 'tecnico_nome', "TEXT DEFAULT ''")
    except Exception:
        pass




def push_vapid_public_key():
    return jsonify({'key': VAPID_PUBLIC_KEY})




def push_subscribe():
    """Técnico de campo salva subscription do browser."""
    try:
        _ensure_push_subscriptions_table()
        data = request.get_json(silent=True) or {}
        endpoint = data.get('endpoint', '').strip()
        p256dh = (data.get('keys') or {}).get('p256dh', '').strip()
        auth = (data.get('keys') or {}).get('auth', '').strip()
        tecnico_id = int(data.get('tecnico_id') or 0)
        tecnico_nome = str(data.get('tecnico_nome') or '').strip()
        empresa_id = int(data.get('empresa_id') or current_company_id() or 0)
        if not endpoint or not p256dh or not auth:
            return jsonify({'ok': False, 'error': 'Dados incompletos'}), 400
        # Atualiza se já existe, insere se não
        existing = query_one('SELECT id FROM push_subscriptions WHERE endpoint=?', (endpoint,))
        if existing:
            execute('UPDATE push_subscriptions SET p256dh=?, auth=?, ativo=1, tecnico_id=?, tecnico_nome=? WHERE endpoint=?',
                    (p256dh, auth, tecnico_id, tecnico_nome, endpoint))
        else:
            execute('INSERT INTO push_subscriptions (empresa_id, tecnico_id, tecnico_nome, endpoint, p256dh, auth, criado_em, ativo) VALUES (?,?,?,?,?,?,?,1)',
                    (empresa_id, tecnico_id, tecnico_nome, endpoint, p256dh, auth, now_str()))
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint', '').strip()
    if endpoint:
        execute('UPDATE push_subscriptions SET ativo=0 WHERE endpoint=?', (endpoint,))
    return jsonify({'ok': True})




def push_test():
    """Envia push de teste para todos os técnicos da empresa."""
    try:
        _ensure_push_subscriptions_table()
        empresa_id = current_company_id()
        subs = [row_to_dict(r) for r in query_all(
            'SELECT * FROM push_subscriptions WHERE empresa_id=? AND ativo=1', (empresa_id,)
        )]
        enviados = 0
        for sub in subs:
            ok = _send_push(
                {'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}},
                'IRIS — Teste de notificação',
                'As notificações estão funcionando!',
                '/'
            )
            if ok:
                enviados += 1
        return jsonify({'ok': True, 'enviados': enviados, 'total': len(subs)})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




def service_worker():
    """Service Worker para Web Push — precisa estar na raiz."""
    sw_code = """
self.addEventListener('push', function(event) {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch(e) {}
  const title = data.title || 'IRIS Campo';
  const options = {
    body: data.body || 'Nova atualização disponível.',
    icon: '/static/iris_icon.png',
    badge: '/static/iris_icon.png',
    vibrate: [200, 100, 200],
    data: { url: data.url || '/' },
    requireInteraction: true,
    actions: [{ action: 'abrir', title: 'Abrir O.S.' }]
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(clients.matchAll({type:'window'}).then(function(clientList) {
    for (const client of clientList) {
      if (client.url === url && 'focus' in client) return client.focus();
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
"""
    return Response(sw_code, mimetype='application/javascript',
                    headers={'Service-Worker-Allowed': '/', 'Cache-Control': 'no-cache, no-store'})


def register_push_routes(app):
    rules = [
        ('/push/vapid-public-key', 'push_vapid_public_key', push_vapid_public_key, ['GET']),
        ('/push/subscribe', 'push_subscribe', push_subscribe, ['POST']),
        ('/push/unsubscribe', 'push_unsubscribe', push_unsubscribe, ['POST']),
        ('/push/test', 'push_test', require_permission('manage_users')(push_test), ['POST']),
        ('/sw.js', 'service_worker', service_worker, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
