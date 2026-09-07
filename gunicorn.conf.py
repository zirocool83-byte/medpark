# Production runtime is configured in production_entry.py.
# Keep this file intentionally minimal because Gunicorn auto-loads gunicorn.conf.py
# from the project root even when -c is not specified.
# Do not place data-count assertions or request-time hard failures here.

bind = None
workers = 1
threads = 4
