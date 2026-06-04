"""Entry point local — gunicorn usa o pacote `app` (app:app)."""
import os

from app import app
from app.bootstrap import startup

if __name__ == '__main__':
    startup()
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', '5000')),
        debug=os.getenv('FLASK_DEBUG', '1').strip().lower() in ('1', 'true', 'yes', 'on'),
    )
