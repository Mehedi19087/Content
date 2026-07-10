release: python core/manage.py migrate && python core/manage.py collectstatic --noinput
web: gunicorn --chdir core core.wsgi --bind 0.0.0.0:$PORT
