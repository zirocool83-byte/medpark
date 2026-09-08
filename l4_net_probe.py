import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import salesops_variant_probe as current
from flask import Response

app = current.app

SALESOPS_HOST = "medparkallo-medpark-salesops.mycafe24.ai"
SELF_HOST = "medparkallo-performance-report-clean.mycafe24.ai"
INTERNAL_CANDIDATES = [
    "medparkallo-medpark-salesops",
    "medparkallo-medpark-salesops.default",
    "medparkallo-medpark-salesops.default.svc.cluster.local",
    "medparkallo-medpark-salesops.local",
]


def resolve(host):
    t0 = time.time()
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        ips = sorted({i[4][0] for i in infos})
        return {"ok": True, "detail": ", ".join(ips), "ms": int((time.time() - t0) * 1000), "ips": ips}
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__ + ": " + str(exc)[:110], "ms": int((time.time() - t0) * 1000), "ips": []}


def tcp(host, port, timeout=4.0):
    t0 = time.time()
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        peer = sock.getpeername()[0]
        return {"ok": True, "detail": "connected -> " + str(peer), "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__ + ": " + str(exc)[:110], "ms": int((time.time() - t0) * 1000)}
    finally:
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url, headers=None, timeout=6.0):
    t0 = time.time()
    hdr = {"User-Agent": "MedPark-L4Probe/1.0", "Accept": "*/*"}
    hdr.update(headers or {})
    req = urllib.request.Request(url, headers=hdr, method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as res:
            body = res.read(160).decode("utf-8", "replace").replace("\n", " ")
            ctype = str(res.headers.get("Content-Type") or "-")
            return {"ok": True, "detail": "HTTP %s | %s | %s" % (getattr(res, "status", 200), ctype, body[:110]), "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as exc:
        loc = exc.headers.get("Location") if exc.headers else None
        try:
            body = exc.read(160).decode("utf-8", "replace").replace("\n", " ")
        except Exception:
            body = ""
        return {"ok": False, "detail": "HTTP %s | Location=%s | %s" % (exc.code, loc, body[:90]), "ms": int((time.time() - t0) * 1000)}
    except urllib.error.URLError as exc:
        return {"ok": False, "detail": "URLError: " + str(getattr(exc, "reason", exc))[:120], "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__ + ": " + str(exc)[:110], "ms": int((time.time() - t0) * 1000)}


def read_text(path, limit=400):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit).strip()
    except Exception as exc:
        return type(exc).__name__


def esc(v):
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def row(label, res):
    color = "#0a7a3d" if res.get("ok") else "#b3261e"
    mark = "PASS" if res.get("ok") else "FAIL"
    return (
        "<tr><td style='padding:9px 8px;border-bottom:1px solid #e5e5e5;font-weight:600'>%s</td>"
        "<td style='padding:9px 8px;border-bottom:1px solid #e5e5e5;color:%s;font-weight:700;white-space:nowrap'>%s</td>"
        "<td style='padding:9px 8px;border-bottom:1px solid #e5e5e5;word-break:break-all'>%s</td>"
        "<td style='padding:9px 8px;border-bottom:1px solid #e5e5e5;text-align:right;color:#666;white-space:nowrap'>%sms</td></tr>"
        % (esc(label), color, mark, esc(res.get("detail")), res.get("ms"))
    )


@app.get("/l4-probe")
def l4_probe():
    port = os.environ.get("PORT", "8000")
    token = os.environ.get("PERFORMANCE_READ_ONLY_TOKEN", "").strip()

    dns_salesops = resolve(SALESOPS_HOST)
    dns_self = resolve(SELF_HOST)
    dns_public = resolve("api.github.com")

    salesops_ip = dns_salesops["ips"][0] if dns_salesops["ips"] else None
    self_ip = dns_self["ips"][0] if dns_self["ips"] else None

    tests = []
    tests.append(("A1. DNS  SalesOps 공개주소", dns_salesops))
    tests.append(("A2. DNS  공간4 자기주소", dns_self))
    tests.append(("A3. DNS  외부(api.github.com)", dns_public))

    tests.append(("B1. TCP  자기 앱 127.0.0.1:" + str(port), tcp("127.0.0.1", int(port))))
    if salesops_ip:
        tests.append(("B2. TCP  SalesOps IP:443", tcp(salesops_ip, 443)))
        tests.append(("B3. TCP  SalesOps IP:80", tcp(salesops_ip, 80)))
        tests.append(("B4. TCP  SalesOps IP:8000", tcp(salesops_ip, 8000)))
    else:
        skipped = {"ok": False, "detail": "DNS 실패로 생략", "ms": 0}
        tests.append(("B2. TCP  SalesOps IP:443", skipped))

    tests.append(("C1. TCP  외부 1.1.1.1:443", tcp("1.1.1.1", 443)))
    tests.append(("C2. TCP  외부 8.8.8.8:53", tcp("8.8.8.8", 53)))
    tests.append(("C3. TCP  외부 api.github.com:443", tcp("api.github.com", 443)))

    tests.append(("D1. HTTPS SalesOps /health", http("https://" + SALESOPS_HOST + "/health")))
    tests.append(("D2. HTTPS SalesOps /api/performance", http("https://" + SALESOPS_HOST + "/api/performance?" + urllib.parse.urlencode({"year": 2026, "month": 9}), {"Accept": "application/json", "Authorization": "Bearer " + token} if token else {"Accept": "application/json"})))
    tests.append(("D3. HTTP  SalesOps :80 /health", http("http://" + SALESOPS_HOST + "/health")))
    tests.append(("D4. HTTPS 공간4 자기주소 /", http("https://" + SELF_HOST + "/")))

    for name in INTERNAL_CANDIDATES:
        tests.append(("E. DNS  내부후보 " + name, resolve(name)))

    ext_ok = any(t[1].get("ok") for t in tests if t[0].startswith(("C1", "C2", "C3")))
    salesops_tcp_ok = any(t[1].get("ok") for t in tests if t[0].startswith(("B2", "B3", "B4")))
    internal_ok = any(t[1].get("ok") for t in tests if t[0].startswith("E."))
    hairpin = bool(salesops_ip and self_ip and salesops_ip == self_ip)

    if salesops_tcp_ok:
        verdict = "TCP는 열려 있음. 원인은 L7(인증/라우트). SalesOps 소스 수정으로 해결."
        vcolor = "#0a7a3d"
    elif not ext_ok:
        verdict = "아웃바운드 전면 차단. 서버간 HTTP 호출 불가 → 브라우저 사이드 또는 DB 직결로 전환 필요."
        vcolor = "#b3261e"
    elif internal_ok:
        verdict = "공개주소는 막혔으나 내부 호스트명이 해석됨 → 내부주소 직결 경로 가능."
        vcolor = "#8a6d00"
    else:
        verdict = "외부는 되는데 SalesOps 공개주소만 거부(hairpin 차단) → 브라우저 사이드 또는 DB 직결로 전환 필요."
        vcolor = "#b3261e"

    env_proxy = {k: v for k, v in os.environ.items() if "PROXY" in k.upper()}
    meta = [
        ("컨테이너 hostname", socket.gethostname()),
        ("PORT", port),
        ("TOKEN 설정됨", "예" if token else "아니오"),
        ("SalesOps IP", salesops_ip or "-"),
        ("공간4 자기 IP", self_ip or "-"),
        ("동일 IP(hairpin 의심)", "예" if hairpin else "아니오"),
        ("PROXY 환경변수", str(env_proxy) if env_proxy else "없음"),
        ("resolv.conf", read_text("/etc/resolv.conf", 300)),
        ("hosts", read_text("/etc/hosts", 300)),
    ]

    html = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>L4 NET PROBE</title></head>",
            "<body style='margin:0;padding:14px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:17px;line-height:1.5;color:#111'>",
            "<h1 style='font-size:22px;margin:0 0 6px'>공간4 네트워크 계층 진단</h1>",
            "<div style='color:#666;font-size:14px;margin-bottom:12px'>%s</div>" % esc(time.strftime("%Y-%m-%d %H:%M:%S")),
            "<div style='padding:14px;border-radius:9px;background:#f6f6f6;border-left:6px solid %s;font-weight:700;font-size:18px;margin-bottom:16px'>판정<br>%s</div>" % (vcolor, esc(verdict)),
            "<table style='width:100%;border-collapse:collapse;font-size:15px'>"]
    for label, res in tests:
        html.append(row(label, res))
    html.append("</table>")
    html.append("<h2 style='font-size:19px;margin:22px 0 8px'>환경 정보</h2>")
    html.append("<table style='width:100%;border-collapse:collapse;font-size:15px'>")
    for k, v in meta:
        html.append("<tr><td style='padding:8px;border-bottom:1px solid #e5e5e5;font-weight:600;white-space:nowrap'>%s</td><td style='padding:8px;border-bottom:1px solid #e5e5e5;word-break:break-all'>%s</td></tr>" % (esc(k), esc(v)))
    html.append("</table>")
    html.append("<p style='color:#666;font-size:14px;margin-top:18px'>이 페이지는 진단 전용입니다. 기존 화면/데이터는 건드리지 않습니다.</p>")
    html.append("</body></html>")

    resp = Response("".join(html), mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    return resp
