import threading

import clean_salesops_resilient as resilient
from flask import jsonify, make_response, request

app = resilient.app
core = resilient.active
base = core.base
ui = core.ui

_refresh_lock = threading.Lock()


def _sum(rows, field):
    vals = [r.get(field) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _domestic_keys():
    return [(b, "국내", k) for b in base.BUSINESSES for k in base.KINDS]


def _load_snapshot(year, month):
    data, saved_at = core._load_snapshot(year, month)
    return data or {}, saved_at


def _refresh_worker(year, month):
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        try:
            core._fetch(year, month, True)
        except Exception:
            pass
        py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
        try:
            core._fetch(py, pm, True)
        except Exception:
            pass
    finally:
        _refresh_lock.release()


def _get_display_sources(year, month):
    current, current_saved = _load_snapshot(year, month)
    py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
    previous, previous_saved = _load_snapshot(py, pm)

    # Only block on the network if we do not yet have a usable snapshot.
    if not current:
        try:
            current, _ = core._fetch(year, month, True)
        except Exception:
            current = {}
        if current:
            current_saved = "live"
    if not previous:
        try:
            previous, _ = core._fetch(py, pm, True)
        except Exception:
            previous = {}
        if previous:
            previous_saved = "live"

    # Refresh snapshots asynchronously; never make the visible dashboard depend on live API availability.
    threading.Thread(target=_refresh_worker, args=(year, month), daemon=True).start()
    return current, current_saved, previous, previous_saved


def _build_report(year, month):
    report = ui.report_data(year, month)
    details = [r for r in report.get("rows", []) if not r.get("is_total")]
    current, current_saved, previous, previous_saved = _get_display_sources(year, month)

    for row in details:
        if row.get("region") != "국내":
            continue
        key = (row.get("business"), "국내", row.get("kind"))
        cur = current.get(key) or {}
        prev = previous.get(key) or {}
        if cur.get("first") is not None:
            row["first"] = cur["first"]
        if cur.get("second") is not None:
            row["second"] = cur["second"]
        if month == 8 and cur.get("close") is not None:
            row["close"] = cur["close"]
            row["close_has"] = True
        if prev.get("close") is not None:
            row["prev_close"] = prev["close"]

    sum_fields = (
        "prev_close","first","second","third_confirmed","third_forecast","close",
        "next_first","carryover","qproj","october","november","december","q4proj","second_half"
    )
    totals = [r for r in report.get("rows", []) if r.get("is_total")]
    for total in totals:
        source = details if total.get("is_grand") else [r for r in details if r.get("business") == total.get("business")]
        for field in sum_fields:
            total[field] = _sum(source, field)
        total["close_has"] = bool(source) and all(r.get("close_has") for r in source)

    domestic = [r for r in details if r.get("region") == "국내"]
    report["root_snapshot"] = {
        "current_rows": sum(1 for key in _domestic_keys() if key in current),
        "previous_rows": sum(1 for key in _domestic_keys() if key in previous),
        "second_total": _sum(domestic, "second"),
        "prev_close_total": _sum(domestic, "prev_close"),
        "current_saved": current_saved,
        "previous_saved": previous_saved,
    }
    return report


def _banner(report):
    meta = report.get("root_snapshot", {})
    ready = meta.get("current_rows") == 6 and meta.get("previous_rows") == 6
    if ready:
        return (
            "<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #91c8a7;"
            "background:#f1faf4;border-radius:7px;font-size:12px'>"
            f"<b>SalesOps 국내연동 OK</b> · 8월 잠정마감 {ui.money_m(meta.get('prev_close_total'))}백만원"
            f" · 9월 2차 {ui.money_m(meta.get('second_total'))}백만원"
            " · 최근 정상값 표시/자동갱신</div>"
        )
    return (
        "<div style='margin:8px 0 10px;padding:9px 12px;border:1px solid #d89c9c;"
        "background:#fff4f4;border-radius:7px;font-size:12px'>"
        "<b>국내 연동 스냅샷 준비중</b> · 자동 재시도 중</div>"
    )


@app.before_request
def root_snapshot_before_request():
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
    html = ui.render_report(report, user, request.args.get("capture") == "1")
    if request.args.get("capture") != "1":
        html = html.replace("<div class='table-wrap'>", _banner(report) + "<div class='table-wrap'>", 1)
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-MedPark-Root-Runtime"] = "snapshot-first-1.0"
    return resp


@app.get("/root-snapshot-check")
def root_snapshot_check():
    current, _ = _load_snapshot(2026, 9)
    previous, _ = _load_snapshot(2026, 8)
    keys = _domestic_keys()
    cur_rows = [current.get(k) or {} for k in keys]
    prev_rows = [previous.get(k) or {} for k in keys]
    second_total = sum(r.get("second") for r in cur_rows if r.get("second") is not None)
    second_non_null = sum(1 for r in cur_rows if r.get("second") is not None)
    close_non_null = sum(1 for r in prev_rows if r.get("close") is not None)
    ok = len([k for k in keys if k in current]) == 6 and len([k for k in keys if k in previous]) == 6 and second_non_null == 6 and close_non_null == 6 and second_total == 797318256
    return jsonify({
        "status": "ok" if ok else "not_ready",
        "current_rows": len([k for k in keys if k in current]),
        "previous_rows": len([k for k in keys if k in previous]),
        "second_non_null": second_non_null,
        "second_total": second_total,
        "prev_close_non_null": close_non_null,
    }), (200 if ok else 409)
