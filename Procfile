web: python bootstrap.py && gunicorn -c gunicorn_safe.conf.py -w 1 --threads 4 -b 0.0.0.0:$PORT fcst_entry:app
