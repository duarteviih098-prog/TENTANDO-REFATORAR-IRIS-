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
# desenvolvimento
export FLASK_APP=app.py   # set FLASK_APP=app.py no Windows
flask run

# ou
python app.py

# produção (Render)
gunicorn app:app --bind 0.0.0.0:$PORT
```

Teste rápido: `GET /health` → `ok`, `GET /login` → tela de login.

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
├── app.py                   # entry point local (dev)
├── tests/test_smoke.py      # smoke tests (import, /health, rotas)
├── templates/
├── static/
├── seed/
├── tools/                   # scripts apply_module*.py (histórico da refatoração)
├── requirements.txt
├── Procfile
├── runtime.txt
├── .env.example
└── README.md
```

Cada domínio expõe `register_<modulo>(app)` chamado em `app/bootstrap.py`. Helpers transversais ficam em `app/shared/*` (fase 2 — `legacy.py` removido). URLs e regras de negócio foram preservadas durante a modularização.

Produção: `gunicorn app:app` (pacote `app/`, não o `app.py` da raiz).

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
