"""Ponto de entrada WSGI para Gunicorn/Render.

Use: gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 120
"""
from app.bootstrap import app  # noqa: F401
