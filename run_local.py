"""Entry point local — no PC use: python run_local.py

Em produção o Render usa: gunicorn wsgi:app --bind 0.0.0.0:$PORT --timeout 120
"""
import os

from app.bootstrap import app, startup

if __name__ == '__main__':
    startup()
    app.run(
        host=os.getenv('FLASK_HOST', '0.0.0.0'),
        port=int(os.getenv('FLASK_PORT', '5000')),
        debug=os.getenv('FLASK_DEBUG', '1').strip().lower() in ('1', 'true', 'yes', 'on'),
    )
