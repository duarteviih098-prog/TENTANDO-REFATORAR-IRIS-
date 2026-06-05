"""Request ID e logs JSON em produção."""
import json
import logging
import os
import uuid

from flask import g, has_request_context, request


class JsonRequestFormatter(logging.Formatter):
    """Uma linha JSON por log — fácil de filtrar no Render/Supabase."""

    def format(self, record):
        payload = {
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if has_request_context():
            payload['request_id'] = getattr(g, 'request_id', None)
            payload['path'] = request.path
            payload['method'] = request.method
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _json_logs_enabled():
    if os.getenv('IRIS_JSON_LOGS', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    from app.config import is_production_env
    return is_production_env()


def configure_app_logging(app):
    if not _json_logs_enabled():
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonRequestFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)


def register_request_logging(app):
    configure_app_logging(app)

    @app.before_request
    def _assign_request_id():
        incoming = (request.headers.get('X-Request-ID') or '').strip()
        g.request_id = incoming or uuid.uuid4().hex[:16]

    @app.after_request
    def _attach_request_id(response):
        if hasattr(g, 'request_id'):
            response.headers['X-Request-ID'] = g.request_id
        return response
