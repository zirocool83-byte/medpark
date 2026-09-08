import os
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import l4_net_probe as prev
from flask import Response

app = prev.app

EDGE_IP = "222.122.39.91"
SELF_MARKER = "공간4 네트워크 계층 진단"
PORT_START = 8000
PORT_END = 8100


def esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def raw_get(ip, port, path, timeout=2.5):
    url = "http://%s:%s%s" % (ip, port, path)
    req = urllib.request.Request(url, headers={"User-Agent": "MedPark-Probe2/1.0", "Accept": "*/*"}, method="GET")
    opener = urllib.request.build_opener(prev._NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as res:
            body = res.read(200).decode("utf-8", "replace").replace("\n", " ").strip()
            return {"status": getattr(res, "status", 200), "server": res.headers.get("Server"), "location": None, "body": body}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200).decode("utf-8", "replace").replace("\n", " ").strip()
        except Exception:
            body = ""
        return {"status": exc.code, "server": exc.headers.get("Server") if exc.headers else None, "location": exc.headers.get("Location") if exc.headers else None, "body": body}
    except Exception as exc:
        return {"status": 0, "server": None, "location": None, "body": type(exc).__name__ + ": " + str(exc)[:80]}


def port_open(port):
    try:
        s = socket.create_connection((EDGE_IP, port), timeout=0.6)
        s.close()
        return port
    except Exception:
        return None


def container_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as exc:
        return type(exc).__name__


@app.get("/l4-probe2")
def l4_probe2():
    out = []
    out.append("<!doctype html><html lang='ko'><head><meta charset='utf-8'>")
    out.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    out.append("<title>PROBE2</title></head><body style='margin:0;padding:14px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:17px;line-height:1.5;color:#111'>")
    out.append("<h1 style='font-size:22px;margin:0 0 10px'>2차 진단 · 호스트 포트 정체</h1>")

    ident = raw_get(EDGE_IP, 8000, "/l4-probe")
    is_self = SELF_MARKER in (ident.get("body") or "")
    local_ident = raw_get("127.0.0.1", int(os.environ.get("PORT", "8000")), "/l4-probe")
    local_self = SELF_MARKER in (local_ident.get("body") or "")

    verdict_color = "#b3261e"
    if is_self:
        verdict = "222.122.39.91:8000 은 공간4 자기 자신입니다. 서버간 직결 경로 없음 → 브라우저 사이드로 전환."
    else:
        verdict = "222.122.39.91:8000 은 공간4가 아닌 다른 서비스입니다. 아래 스캔 결과에서 SalesOps 포트를 확인하십시오."
        verdict_color = "#8a6d00"

    out.append("<div style='padding:14px;border-radius:9px;background:#f6f6f6;border-left:6px solid %s;font-weight:700;font-size:18px;margin-bottom:16px'>판정<br>%s</div>" % (verdict_color, esc(verdict)))

    out.append("<h2 style='font-size:19px;margin:18px 0 8px'>1. 정체 확인</h2>")
    out.append("<table style='width:100%;border-collapse:collapse;font-size:15px'>")
    for label, res, flag in (("edge 222.122.39.91:8000", ident, is_self), ("local 127.0.0.1:PORT", local_ident, local_self)):
        out.append("<tr><td style='padding:8px;border-bottom:1px solid #e5e5e5;font-weight:600'>%s</td><td style='padding:8px;border-bottom:1px solid #e5e5e5'>HTTP %s<br>자기자신=%s<br>%s</td></tr>" % (esc(label), esc(res.get("status")), "예" if flag else "아니오", esc((res.get("body") or "")[:120])))
    out.append("</table>")

    t0 = time.time()
    ports = list(range(PORT_START, PORT_END + 1))
    with ThreadPoolExecutor(max_workers=50) as ex:
        found = [p for p in ex.map(port_open, ports) if p]
    scan_ms = int((time.time() - t0) * 1000)

    out.append("<h2 style='font-size:19px;margin:22px 0 8px'>2. 포트 스캔 %s-%s (%sms)</h2>" % (PORT_START, PORT_END, scan_ms))
    if not found:
        out.append("<p style='color:#b3261e;font-weight:700'>열린 포트 없음</p>")
    out.append("<table style='width:100%;border-collapse:collapse;font-size:15px'>")
    for p in found[:20]:
        h = raw_get(EDGE_IP, p, "/health")
        r = raw_get(EDGE_IP, p, "/")
        mark = "공간4(자기)" if (SELF_MARKER in (raw_get(EDGE_IP, p, "/l4-probe").get("body") or "")) else "기타"
        out.append("<tr><td style='padding:8px;border-bottom:1px solid #e5e5e5;font-weight:700;white-space:nowrap'>:%s<br><span style='font-size:13px;color:#666'>%s</span></td><td style='padding:8px;border-bottom:1px solid #e5e5e5;word-break:break-all;font-size:14px'>/health → %s %s<br>/ → %s | %s</td></tr>" % (p, esc(mark), esc(h.get("status")), esc((h.get("body") or "")[:70]), esc(r.get("status")), esc((r.get("body") or "")[:90])))
    out.append("</table>")

    out.append("<h2 style='font-size:19px;margin:22px 0 8px'>3. DB 접근성</h2>")
    db_host = os.environ.get("DB_HOST", "")
    db_port = os.environ.get("DB_PORT", "3306")
    db_name = os.environ.get("DB_NAME", "")
    db_user = os.environ.get("DB_USER", "")
    db_pw = os.environ.get("DB_PASSWORD", "")
    db_rows = [
        ("DB_HOST", db_host or "(없음)"),
        ("DB_PORT", db_port),
        ("DB_NAME", db_name or "(없음)"),
        ("DB_USER", db_user or "(없음)"),
        ("DB_PASSWORD", "설정됨" if db_pw else "(없음)"),
        ("컨테이너 내부 IP", container_ip()),
    ]
    if db_host:
        try:
            res = prev.tcp(db_host, int(db_port))
        except Exception as exc:
            res = {"ok": False, "detail": type(exc).__name__}
        db_rows.append(("DB TCP 연결", ("성공 " if res.get("ok") else "실패 ") + str(res.get("detail"))))
    out.append("<table style='width:100%;border-collapse:collapse;font-size:15px'>")
    for k, v in db_rows:
        out.append("<tr><td style='padding:8px;border-bottom:1px solid #e5e5e5;font-weight:600;white-space:nowrap'>%s</td><td style='padding:8px;border-bottom:1px solid #e5e5e5;word-break:break-all'>%s</td></tr>" % (esc(k), esc(v)))
    out.append("</table>")

    out.append("<p style='color:#666;font-size:14px;margin-top:18px'>진단 전용. 기존 화면/데이터는 건드리지 않습니다.</p></body></html>")

    resp = Response("".join(out), mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    return resp
