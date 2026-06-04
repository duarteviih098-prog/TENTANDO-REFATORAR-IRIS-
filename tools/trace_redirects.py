"""Trace redirect chains for debugging ERR_TOO_MANY_REDIRECTS."""
from app import app

client = app.test_client()


def trace(path, session_data=None, max_hops=15):
    chain = []
    with client.session_transaction() as sess:
        if session_data:
            sess.update(session_data)
        resp = client.get(path)
        current_path = path
        for _ in range(max_hops):
            chain.append((current_path, resp.status_code, resp.headers.get('Location')))
            if resp.status_code not in (301, 302, 303, 307, 308):
                break
            loc = resp.headers.get('Location') or ''
            if loc.startswith('http'):
                from urllib.parse import urlparse
                current_path = urlparse(loc).path or '/'
            else:
                current_path = loc.split('?')[0] or '/'
            resp = client.get(loc)
        return chain


if __name__ == '__main__':
    paths = ['/', '/login', '/home', '/controle', '/controle/hub', '/gestor/app', '/dashboard']
    print('=== sem sessao ===')
    for p in paths:
        ch = trace(p)
        print(p)
        for item in ch:
            print('  ', item)

    print('\n=== sessao user_id=1 ===')
    sess = {'user_id': 1, '_is_permanent': True, 'empresa_id': 1}
    for p in paths:
        ch = trace(p, sess)
        print(p)
        for item in ch:
            print('  ', item)
