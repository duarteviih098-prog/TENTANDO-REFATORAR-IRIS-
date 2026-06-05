# Deploy IRIS — produção (Render + Supabase)

Guia enxuto para subir o refatorado. **Não migra dados automaticamente.**

## 1. Supabase

1. Criar projeto (ou usar staging).
2. **Connect → Direct → Transaction** → copiar `DATABASE_URL`.
3. **Settings → API** → `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (secret, não anon).
4. **Storage** → bucket `uploads` (ou o nome em `SUPABASE_STORAGE_BUCKET`).

## 2. Render (Web Service)

- **Runtime:** `python-3.11.9` (`runtime.txt`)
- **Build:** `pip install -r requirements.txt`
- **Start:** `gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 120` (igual ao `Procfile`)
- **Health check:** `/health`
- **Blueprint opcional:** `render.yaml`

### Variáveis obrigatórias

| Variável | Exemplo |
|---|---|
| `SECRET_KEY` | 40+ chars aleatórios |
| `IRIS_PRODUCTION` | `1` |
| `DATABASE_URL` | URI Postgres Supabase |
| `SUPABASE_URL` | `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | `sb_secret_...` |
| `SUPABASE_STORAGE_BUCKET` | `uploads` |
| `APP_TIMEZONE` | `America/Sao_Paulo` |

### Variáveis recomendadas (P1)

| Variável | Para quê |
|---|---|
| `SENTRY_DSN` | Alertas de erro 500 |
| `IRIS_JSON_LOGS` | `1` — logs JSON no Render |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` | Reset de senha |

Copie Outlook, IA, VAPID etc. do ambiente antigo se usar esses módulos.

## 3. Código no GitHub

Subir o repo refatorado. Deploy manual ou auto-deploy do Render.

## 4. Primeiro boot

- App roda `ensure_db()` → aplica migrations em `migrations/versions/` e depois colunas/índices incrementais.
- Banco **vazio** = sem usuários até cadastrar ou importar dados.
- Login só funciona se existir registro em `users` + `empresas`.

### Bootstrap manual (opcional)

```bash
python tools/bootstrap_db.py --db-path app.db
```

Postgres: defina `DATABASE_URL` e rode `python tools/bootstrap_db.py`.

Detalhes: `docs/MIGRATIONS.md`.

## 5. Backup manual por empresa (P1)

```bash
python tools/export_company_backup.py --empresa-id 1
```

## 6. Painéis ops (super-admin)

- `/visao-global` — resumo por empresa
- `/ops/jobs` — fila PDF
- `/historico` — auditoria

## 7. CI (GitHub Actions)

- `.github/workflows/ci.yml` — `ruff check` + `pytest` em push/PR na `main`.

## 8. Checklist pós-deploy

- [ ] `/health` retorna `{"status":"ok","db":"ok"}`
- [ ] Login funciona
- [ ] Upload/storage ok (teste anexo O.S.)
- [ ] PDF mensal gera (ver `/ops/jobs`)
