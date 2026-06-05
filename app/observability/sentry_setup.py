"""Integração opcional com Sentry (SENTRY_DSN no ambiente)."""
import os


def init_sentry(app):
    dsn = os.getenv('SENTRY_DSN', '').strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        app.logger.warning('sentry-sdk não instalado; SENTRY_DSN ignorado')
        return

    environment = os.getenv('SENTRY_ENVIRONMENT', '').strip() or (
        'production' if os.getenv('IRIS_PRODUCTION', '').strip() in ('1', 'true', 'yes') else 'development'
    )
    traces_sample_rate = float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.1') or 0.1)

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=environment,
        release=os.getenv('SENTRY_RELEASE', '').strip() or None,
        traces_sample_rate=max(0.0, min(traces_sample_rate, 1.0)),
        send_default_pii=False,
    )
    app.logger.info('Sentry ativo (env=%s)', environment)
