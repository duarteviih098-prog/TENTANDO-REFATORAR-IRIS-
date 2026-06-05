"""Observabilidade P1: Sentry, request ID e logs estruturados."""
from app.observability.logging_setup import register_request_logging
from app.observability.sentry_setup import init_sentry


def register_observability(app):
    init_sentry(app)
    register_request_logging(app)
