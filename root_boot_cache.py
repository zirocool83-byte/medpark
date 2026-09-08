import threading
import time

import root_live_fetch as live
from flask import jsonify, make_response, request

app = live.app
base = live.base
ui = live.ui

# Remove the older root handler that performed a network request during every page load.
app.before_request_funcs[None] = [
    fn for fn in app.before_request_funcs.get(None, [])
    if getattr(fn, '__name__', '') != 'root_live_before_request'
]

_CACHE = {}
_META = {}
_REFRESH_LOCK = threading.Lock()


def _prime(year, month, attempts=12):
    last_meta = {"ok": False, "reason": "not_started", "source": "live"}
    for i in range(attempts):
        data, meta = live._request_once(year, month)
        last_meta = meta
        if meta.get("ok") and data:
            _CACHE[(year, month)] = data
            _META[(year, month)] = meta
            return True
        if i < attempts - 1:
            time.sleep(0.25 + i * 0.05)
    snap, saved_at = live._load_snapshot(year, month)
    if snap:
        _CACHE[(year, month)] = snap
        _META[(year, month)] = {
            "ok": True,
            "reason": "snapshot_boot",
            "source": "snapshot",
            "saved_at": saved_at,
            "warning": last_meta.get("reason"),
            "rows": len(snap),
        }
        return True
    _CACHE[(year, month)] = {}
    _META[(year, month)] = last_meta
    return False


def _refresh_period(year, month):
    data, meta = live._request_once(year, month)
    if meta.get("ok") and data:
        _CACHE[(year, month)] = data
        _META[(year, month)] = meta
        return True
    return False


def _refresh_pair(year, month):
    if not _REFRESH_LOCK.acquire(blocking=False):
        return
    try:
        _refresh_period(year, month)
        py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
        _refresh_period(py, pm)
    finally:
        _REFRESH_LOCK.release()


def _get(year, month):
    key = (year, month)
    if key not in _CACHE or not _CACHE[key]:
        _prime(year, month, attempts=5)
    return _CACHE.get(key, {}), _META.get(key, {"ok": False, "reason": "cache_empty", "source": "memory"})


def _sum(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _build_report(year, month):
    report = ui.report_data(year, month)
    details = [r for r in report.get("rows", []) if not r.get("is_total")]
    cur, cm = _get(year, month)
    py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
    prev, pmmeta = _get(py, pm)

    for row in details:
        if row.get("region") != "국내":
            continue
        key = (row.get("business"), "국내", row.get("kind"))
        c = cur.get(key) or {}
        p = prev.get(key) or {}
        if c.get("first") is not None:
            row["first"] = c["first"]
        if c.get("second") is not None:
            row["second"] = c["second"]
        if month == 8 and c.get("close") is not None:
            row["close"] = c["close"]
            row["close_has"] = True
        if p.get("close") is not None:
            row["prev_close"] = p["close"]

    fields = (
        "prev_close","first","second","third_confirmed","third_forecast","close",
        "next_first","carryover","qproj","october","november","december","q4proj","second_half"
    )
    for total in [r for r in report.get("rows", []) if r.get("is_total")]:
        source = details if total.get("is_grand") else [r for r in details if r.get("business") == total.get("business")]
        for f in fields:
            total[f] = _sum(source, f)
        total["close_has"] = bool(source) and all(r.get("close_has") for r in source)

    domestic = [r for r in details if r.get("region") == "국내"]
    report["boot_cache"] = {
        "current": cm,
        "previous": pmmeta,
        "second_total": _sum(domestic, "second"),
        "prev_close_total": _sum(domestic, "prev_close"),
        "domestic_rows": len(domestic),
    }
    return report


def _banner(report):
    m = report.get("boot_cache", {})
    c = m.get("current", {})
    p = m.get("previous", {})
    ready = c.get("ok") and p.get("ok") and m.get("domestic_rows") == 6
    if ready:
        src = "실시간" if c.get("source") == "live" and p.get("source") == "live" else "최근 정상값"
        return (
            "<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #91c8a7;background:#f1faf4;border-radius:7px;font-size:12px'>"
            f"<b>SalesOps 국내연동 OK</b> · {src} · 8월 잠정마감 {ui.money_m(m.get('prev_close_total'))}백만원"
            f" · 9월 2차 {ui.money_m(m.get('second_total'))}백만원 · 자동갱신</div>"
        )
    reason = c.get("reason") or p.get("reason") or "cache_empty"
    return (
        "<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #d89c9c;background:#fff4f4;border-radius:7px;font-size:12px'>"
        f"<b>국내 데이터 준비중</b> · {ui.esc(reason)}</div>"
    )


# Prime every process at startup. User page rendering never depends on a live network call.
_prime(2026, 9)
_prime(2026, 8)


@app.before_request
def root_boot_cache_before_request():
    if request.path != "/":
        return None
    user = base.current_user()
    if not user:
        return None
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    report = _build_report(year, month)
    threading.Thread(target=_refresh_pair, args=(year, month), daemon=True).start()
    html = ui.render_report(report, user, request.args.get("capture") == "1")
    if request.args.get("capture") != "1":
        html = html.replace("<div class='table-wrap'>", _banner(report) + "<div class='table-wrap'>", 1)
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-MedPark-Root-Runtime"] = "boot-cache-1.0"
    return resp


@app.get('/root-cache-check')
def root_cache_check():
    cur, cm = _get(2026, 9)
    prev, pm = _get(2026, 8)
    keys = [(b, "국내", k) for b in base.BUSINESSES for k in base.KINDS]
    cr = [cur.get(k) or {} for k in keys]
    pr = [prev.get(k) or {} for k in keys]
    second_total = sum(r.get("second") for r in cr if r.get("second") is not None)
    current_rows = sum(1 for k in keys if k in cur)
    previous_rows = sum(1 for k in keys if k in prev)
    second_non_null = sum(1 for r in cr if r.get("second") is not None)
    close_non_null = sum(1 for r in pr if r.get("close") is not None)
    ok = cm.get("ok") and pm.get("ok") and current_rows == 6 and previous_rows == 6 and second_non_null == 6 and second_total == 797318256 and close_non_null == 6
    return jsonify({
        "status": "ok" if ok else "not_ready",
        "current_source": cm.get("source"),
        "previous_source": pm.get("source"),
        "current_rows": current_rows,
        "previous_rows": previous_rows,
        "second_non_null": second_non_null,
        "second_total": second_total,
        "prev_close_non_null": close_non_null,
    }), (200 if ok else 409)
