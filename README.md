# IRIS (iris-cost)

Sistema web de gestão operacional **Getec/IRIS** — controle de O.S., pagamentos, combustível, custos, inventário, campo (PWA) e integrações (Outlook, Supabase, IA).

Stack: **Flask 3**, SQLite local ou **Postgres/Supabase** em produção, deploy em **Render** com storage em **Supabase**.

## Instalação local

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # ou copy no Windows
```

Edite `.env` com `SECRET_KEY` e, se quiser Postgres, `DATABASE_URL`. Sem `DATABASE_URL`, o app usa SQLite (`app.db` na raiz — **não versionar**).

## Executar

```bash
# desenvolvimento local
python run_local.py

# produção (Render)
gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 120
```

Teste rápido: `GET /health` → `{"status":"ok","db":"ok"}`, `GET /login` → tela de login.

```bash
# testes
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -q
```

Páginas de erro amigáveis (404/403/500) em `templates/errors/page.html`.

## Documentação operacional

| Doc | Conteúdo |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Render + Supabase + checklist pós-deploy |
| [docs/MIGRATIONS.md](docs/MIGRATIONS.md) | Migrations versionadas e bootstrap |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | O que fazer quando algo quebra |
| [tools/README.md](tools/README.md) | Scripts utilitários |

CI: `.github/workflows/ci.yml` (lint + pytest com coverage + job Postgres + Dependabot).

Segurança: `SECRET_KEY`/Supabase obrigatórios em produção, CSRF em APIs JSON, tenant isolation, login rate-limit no banco — testes em `tests/test_security_complete.py`.

## Estrutura modular (refatoração concluída)

```
iris-cost/
├── app/
│   ├── __init__.py          # exporta app (via bootstrap)
│   ├── bootstrap.py         # create_app + register_* de todos os módulos
│   ├── runtime.py           # flask_app() + contexto de background workers
│   ├── factory.py           # Flask factory
│   ├── config.py
│   ├── shared/              # helpers (formatters, rows, cache, queries, …)
│   ├── auth/                # login, permissões, multi-empresa
│   ├── db/                  # SQLite/Postgres, migrations
│   ├── storage/             # Supabase, anexos, identidade PDF
│   ├── controle/            # bombas / controle
│   ├── combustivel/
│   ├── pagamentos/
│   ├── custos/
│   ├── os/
│   ├── campo/               # PWA técnicos, push
│   ├── inventario/
│   ├── outlook/
│   ├── exports/             # PDF/Excel Iris
│   └── integrations/        # Iris chat, WhatsApp
├── run_local.py             # entry point local (dev)
├── wsgi.py                  # entry point Gunicorn/Render
├── tests/                   # pytest (smoke, auth, P0, erros)
├── templates/
├── static/
├── seed/
├── tools/                   # bootstrap, backup, package (archive/ = histórico)
├── migrations/versions/     # schema SQL versionado
├── docs/                    # DEPLOY, MIGRATIONS, RUNBOOK
├── requirements.txt         # produção
├── requirements-dev.txt     # pytest + ruff
├── Procfile
├── runtime.txt
├── render.yaml              # blueprint Render (opcional)
├── .gitignore
├── .env.example
└── README.md
```

Cada domínio expõe `register_<modulo>(app)` chamado em `app/bootstrap.py`. Helpers transversais ficam em `app/shared/*` (fase 2 — `legacy.py` removido). URLs e regras de negócio foram preservadas durante a modularização.

Produção: `gunicorn wsgi:app` (ver `Procfile`).

## Dados sensíveis — não commitar

- `app.db`, `*.db-journal`
- `.env`
- `seed/app_state.json` (dados reais — use `seed/app_state.example.json`)
- `static/uploads/**`

## Seed

```bash
cp seed/app_state.example.json seed/app_state.json
```

Ajuste conforme necessário; o arquivo real permanece fora do Git.

## ZIP para GitHub

Gera pacote limpo (sem dados locais):

```bash
python tools/package_for_github.py
```

Saída: `dist/iris-cost-para-github.zip`
