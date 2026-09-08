# Stable Gunicorn runtime for Cafe24 AI Space.
# Keep this config minimal and valid. Bind address is supplied by Procfile.

workers = 1
threads = 2
timeout = 60
graceful_timeout = 20
keepalive = 2
accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = "info"
