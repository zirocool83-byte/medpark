web: python bootstrap.py && python verify_deploy.py && gunicorn -c gunicorn_safe.conf.py -w 1 --threads 4 -b 0.0.0.0:$PORT fcst_entry:app
