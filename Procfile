web: python bootstrap.py && python verify_ui.py && gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT production_entry:app
