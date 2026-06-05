# Checklist Getec — app profissional

Guia de entrega para o cliente. Itens marcados com **código** já estão no repositório; itens **config** exigem ação no Render/Supabase.

## P0 — Bloqueadores de go-live

| # | Item | Status | Ação |
|---|------|--------|------|
| 1 | Schema no Postgres | **código** | `python tools/bootstrap_db.py` no deploy ou boot automático |
| 2 | Primeiro admin | **código** | `python tools/seed_getec_admin.py --email SEU@EMAIL --senha "SenhaSegura123"` |
| 3 | Variáveis Render | **config** | `SECRET_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `IRIS_PRODUCTION=1` |
| 4 | SMTP esqueci senha | **config** | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` (Office365) |
| 5 | Ícones / favicon | **código** | `static/favicon_iris.ico`, `icon-192.png`, `icon-512.png`, `iris_icon.png` |
| 6 | Deploy correto | **código** | Usar `Procfile` / `render.yaml` (`gunicorn wsgi:app`) — **não** `gunicorn app:app` |
| 7 | Migração de dados legado | **manual** | Exportar com `tools/export_company_backup.py`; importação sob demanda |

## P1 — Profissional / segurança

| # | Item | Status |
|---|------|--------|
| 8 | CSRF em APIs JSON | **código** — inclui `/controle/*` |
| 9 | Headers de segurança | **código** — HSTS (HTTPS), Permissions-Policy |
| 10 | Senha mínima 8 chars | **código** — reset de senha |
| 11 | Sentry + logs JSON | **config** — `SENTRY_DSN`, `IRIS_JSON_LOGS=1` |
| 12 | CI verde | **código** — GitHub Actions lint + test + postgres |
| 13 | Isolamento multi-empresa | **código** — `assert_owned_by_current_company` + `tenant_scope_sql` em todos os `save_*` |

## Pós-deploy (5 min)

1. `GET /health` → `{"status":"ok","db":"ok"}`
2. Login com admin criado no seed
3. Upload de anexo em uma O.S.
4. Gerar PDF de O.S.
5. Testar `/esqueci-senha` (com SMTP configurado)

## Módulos opcionais (decidir com Getec)

| Módulo | Variáveis |
|--------|-----------|
| Web Push (campo) | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` |
| Outlook monitor | `OUTLOOK_*`, `MONITOR_IMAP_*`, `ENABLE_MONITOR_WORKER=1` |
| Relatório IA | `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY` |

Ver também: [DEPLOY.md](DEPLOY.md), [RUNBOOK.md](RUNBOOK.md).
