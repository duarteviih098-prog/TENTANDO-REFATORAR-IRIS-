"""Fixtures compartilhadas de teste."""
import os

import pytest


@pytest.fixture(scope='session')
def flask_app():
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-with-32-chars-minimum-ok')
    from app import app as application
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
