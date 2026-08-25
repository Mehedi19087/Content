release: python core/manage.py migrate && python core/manage.py collectstatic --noinput
web: gunicorn --chdir core core.wsgi --bind 0.0.0.0:$PORT --threads 4 --timeout 300 --graceful-timeout 30
worker: celery --workdir core -A core worker --loglevel=info --concurrency=2
