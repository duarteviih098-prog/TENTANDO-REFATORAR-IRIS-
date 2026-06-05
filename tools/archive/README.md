# Tools IRIS — arquivo histórico

Scripts one-shot da refatoração modular (`apply_module*.py`, extratores, etc.).  
Mantidos só como histórico — **não** fazem parte do deploy nem do CI.

## Scripts ativos (pasta `tools/` na raiz)

| Script | Uso |
|---|---|
| `bootstrap_db.py` | Bootstrap banco vazio com migrations (`--db-path app.db`) |
| `export_company_backup.py` | Backup JSON manual por empresa (`--empresa-id N`) |
| `package_for_github.py` | Gera pacote limpo para publicar no GitHub |
