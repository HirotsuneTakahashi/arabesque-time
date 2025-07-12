web: gunicorn --config gunicorn.conf.py app:app
release: python -c "from app import create_app; create_app()" 