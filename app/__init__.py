"""Pacote principal do IRIS."""
from app.bootstrap import app, startup
from app.factory import create_app

__all__ = ['create_app', 'app', 'startup']

# Nota: helpers compartilhados ficam em app.shared.* (fase 2 — legacy.py removido).
