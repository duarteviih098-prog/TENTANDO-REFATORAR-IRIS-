# Migrations IRIS (P0)

Schema base versionado em `migrations/versions/`. O app aplica migrations pendentes no boot via `ensure_db()`.

## Arquivos

| Arquivo | Banco |
|---|---|
| `001_initial.sqlite.sql` | SQLite local / testes |
| `001_initial.postgres.sql` | Postgres (Supabase) |

Novas versões: prefixo numérico (`002_...`, `003_...`) + sufixo `.sqlite.sql` ou `.postgres.sql`.

## Como funciona

1. `ensure_db()` chama `apply_pending_migrations()` primeiro.
2. A tabela `schema_migrations` registra versões já aplicadas.
3. Depois, `ensure_db()` adiciona colunas/índices incrementais (compatibilidade).

### Banco que já existia (staging/produção)

Se `empresas`/`users`/`os_ordens` já existem mas `schema_migrations` está vazio, a `001` é **registrada sem recriar tabelas** (evita `DuplicateTable` no Postgres).

## Bootstrap banco vazio (local)

```bash
python tools/bootstrap_db.py --db-path app.db
```

Ou com variável:

```bash
set IRIS_TEST_DB=C:\caminho\iris-test.db
python tools/bootstrap_db.py
```

## Postgres (Supabase)

Defina `DATABASE_URL` e rode:

```bash
python tools/bootstrap_db.py
```

## Ver status

```python
from app.db import migration_status
print(migration_status())
# {'applied': ['001'], 'pending': []}
```

## Testes

Os testes usam `IRIS_TEST_DB` (banco temporário isolado). `tests/test_p0_critical.py` valida que `001` foi aplicada em banco vazio.

## Regras

- Não editar `001_*` após deploy em produção — criar `002_*` com ALTER/CREATE incremental.
- Manter par sqlite + postgres para cada versão.
- `ensure_db()` continua responsável por colunas novas até existir migration dedicada.
