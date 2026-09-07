web: python bootstrap.py && python verify_deploy.py && gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT patched_app:app
