"""Módulo Outlook / e-mail."""
from app.outlook.routes import register_routes
from app.outlook.services import (
    list_pending_monitor_alerts,
    maybe_start_monitor_worker,
)


def register_outlook(app):
    register_routes(app)


__all__ = [
    'register_outlook',
    'maybe_start_monitor_worker',
    'list_pending_monitor_alerts',
]
