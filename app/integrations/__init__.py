"""Integrações externas — Iris IA, WhatsApp."""
from app.integrations.iris import register_iris_routes


def register_integrations(app):
    register_iris_routes(app)


__all__ = ['register_integrations']
