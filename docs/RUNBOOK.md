# Runbook IRIS — o que fazer quando...

## App não sobe no Render

1. Ver **Logs** no Render.
2. Erro `SECRET_KEY insegura` → definir chave 32+ chars.
3. Erro de banco → conferir `DATABASE_URL` (senha, pooler Direct/Transaction).
4. `ImportError` → arquivo faltando no GitHub; conferir deploy completo.

## `/health` retorna 503

- `db: fail` → Postgres inacessível ou credencial errada.
- Testar connection string no Supabase → **Connect**.

## Login não funciona

- Banco vazio? Precisa usuário em `users` + empresa em `empresas`.
- `SMTP` só afeta reset de senha, não login normal.

## PDF não gera / timeout

1. Super-admin → `/ops/jobs` — ver status e coluna **Erro**.
2. Conferir `SUPABASE_*` e bucket storage.
3. Render free pode matar job longo — considerar plano ou worker separado (P2).

## Erros 500 em produção

1. Logs Render (filtrar por `request_id` no header `X-Request-ID`).
2. Se `SENTRY_DSN` configurado → abrir issue no Sentry.
3. Reproduzir em staging antes de patch.

## Outlook / monitor parou

- Conferir `MONITOR_IMAP_*` e `ENABLE_MONITOR_WORKER`.
- Ver logs de startup: worker só inicia se env configurada.

## Backup e restore

- **Automático Supabase:** ativar PITR no plano pago.
- **Manual:** `python tools/export_company_backup.py --empresa-id N`
- Restore manual = importar JSON tabela a tabela (procedimento sob demanda).

## Contatos úteis

- Render: dashboard.render.com
- Supabase: supabase.com/dashboard
- Sentry: sentry.io (se configurado)
