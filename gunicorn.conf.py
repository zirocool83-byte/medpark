# Stable Gunicorn runtime for Cafe24 AI Space.
# Keep this config minimal and valid. Bind address is supplied by Procfile.

workers = 1
threads = 2
timeout = 60
graceful_timeout = 20
keepalive = 2

# 워커를 주기적으로 재시작해 메모리를 반납한다.
# 리포트 생성 시 저장소 전체를 읽어 들이는 구조라 상주 메모리가 계속 늘어난다.
max_requests = 200
max_requests_jitter = 30

accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = "info"
