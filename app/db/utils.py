"""Utilitários internos da camada de banco."""


def row_get_value(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        try:
            return getattr(row, key)
        except Exception:
            return default
