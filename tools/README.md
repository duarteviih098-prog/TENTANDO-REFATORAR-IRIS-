# Tools IRIS

Scripts utilitários para operação e manutenção.

## Ativos (use estes)

| Script | Uso |
|---|---|
| `bootstrap_db.py` | Bootstrap banco vazio com migrations (`--db-path app.db`) |
| `seed_getec_admin.py` | Cria empresa + admin inicial para primeiro deploy |
| `export_company_backup.py` | Backup JSON manual por empresa (`--empresa-id N`) |
| `package_for_github.py` | Gera pacote limpo para publicar no GitHub |

## Arquivo (`archive/`)

Scripts one-shot da refatoração modular (`apply_module*.py`, extratores, etc.).  
Mantidos só como histórico — **não** fazem parte do deploy.
