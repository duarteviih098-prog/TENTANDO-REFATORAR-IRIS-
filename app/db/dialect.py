"""Tradução SQLite → PostgreSQL."""
import re

from app.db import settings

def _replace_sqlite_placeholders(sql):
    """Troca placeholders SQLite (?) por placeholders PostgreSQL (%s), sem mexer em ? dentro de strings.
    Também escapa % literais (dentro e fora de strings) para evitar conflito com psycopg2."""
    out = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            out.append(ch)
            # aspas simples escapadas no SQL: ''
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                out.append(sql[i + 1])
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            out.append(ch)
            in_double = not in_double
        elif ch == '?' and not in_single and not in_double:
            # Placeholder SQLite → PostgreSQL
            out.append('%s')
        elif ch == '%':
            # Escapa % literais em qualquer posição — psycopg2 interpreta % como início de placeholder
            out.append('%%')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


def _normalize_pg_sql(sql, params=()):
    """Compatibilidade mínima SQLite -> PostgreSQL para o app existente."""
    original = str(sql or '').strip()
    params = tuple(params or ())
    compact = re.sub(r'\s+', ' ', original).strip()

    # PRAGMA table_info(tabela) -> information_schema
    m = re.match(r'^PRAGMA\s+table_info\((?:"|\'|`)?([A-Za-z0-9_]+)(?:"|\'|`)?\)\s*;?$', compact, flags=re.I)
    if m:
        table = m.group(1)
        return (
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (table,),
            'select'
        )

    # sqlite_sequence não existe no PostgreSQL. Reset de sequence pode ser ignorado aqui.
    if re.match(r'^DELETE\s+FROM\s+sqlite_sequence\b', compact, flags=re.I):
        return 'SELECT 1 WHERE false', (), 'noop'

    s = original

    # CREATE TABLE SQLite -> PostgreSQL básico
    s = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', s, flags=re.I)
    s = re.sub(r'INT\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', s, flags=re.I)
    s = re.sub(r'\bAUTOINCREMENT\b', '', s, flags=re.I)

    # INSERT OR IGNORE -> ON CONFLICT DO NOTHING
    insert_ignore = bool(re.match(r'^\s*INSERT\s+OR\s+IGNORE\s+INTO\b', s, flags=re.I))
    if insert_ignore:
        s = re.sub(r'^\s*INSERT\s+OR\s+IGNORE\s+INTO\b', 'INSERT INTO', s, flags=re.I)
        if ' ON CONFLICT ' not in s.upper():
            s = s.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'

    # INSERT OR REPLACE para tabelas chave/valor e deleted_users.
    replace_match = re.match(r'^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]+)\)\s*VALUES\s*\((.+)\)\s*;?\s*$', s, flags=re.I | re.S)
    if replace_match:
        table = replace_match.group(1)
        cols = [c.strip().strip('"') for c in replace_match.group(2).split(',')]
        conflict_col = None
        if table in ('email_config', 'email_templates') and 'chave' in cols:
            conflict_col = 'chave'
        elif table == 'deleted_users' and 'email' in cols:
            conflict_col = 'email'
        if conflict_col:
            update_cols = [c for c in cols if c != conflict_col]
            set_clause = ', '.join([f'{c}=EXCLUDED.{c}' for c in update_cols]) or f'{conflict_col}=EXCLUDED.{conflict_col}'
            s = re.sub(r'^\s*INSERT\s+OR\s+REPLACE\s+INTO\b', 'INSERT INTO', s, flags=re.I)
            s = s.rstrip().rstrip(';') + f' ON CONFLICT ({conflict_col}) DO UPDATE SET {set_clause}'
        else:
            s = re.sub(r'^\s*INSERT\s+OR\s+REPLACE\s+INTO\b', 'INSERT INTO', s, flags=re.I)

    s = _replace_sqlite_placeholders(s)
    kind = 'select' if re.match(r'^\s*(SELECT|WITH|SHOW)\b', s, flags=re.I) else 'write'
    return s, params, kind


def _is_insert_without_returning(sql):
    return bool(re.match(r'^\s*INSERT\s+INTO\b', sql, flags=re.I)) and not re.search(r'\bRETURNING\b', sql, flags=re.I)


def _insert_table_name(sql):
    m = re.match(r'^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\b', str(sql or ''), flags=re.I)
    return m.group(1) if m else ''


def _insert_can_return_id(sql):
    table = _insert_table_name(sql)
    if not table:
        return False
    if table in {'deleted_users', 'email_config'}:
        return False
    try:
        from app.db.schema import table_has_column
        return table_has_column(table, 'id')
    except Exception:
        return False

