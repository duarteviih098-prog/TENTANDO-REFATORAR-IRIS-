"""Application factory do IRIS."""
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config, PROJECT_ROOT


def create_app(config_class=Config):
    """Cria e configura a instância Flask (factory pattern)."""
    application = Flask(
        __name__,
        root_path=str(PROJECT_ROOT),
        template_folder='templates',
        static_folder='static',
    )
    application.config.from_object(config_class)
    application.secret_key = application.config['SECRET_KEY']

    from app.config import validate_production_config
    validate_production_config(application.config['SECRET_KEY'])

    application.wsgi_app = ProxyFix(
        application.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
    )
    return application
