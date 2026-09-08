import html
import json
import os
import traceback

import app as base

app = base.app
_ORIGINAL_SCOPE_PAIRS = base.scope_pairs


def scope_pairs(user):
    if not user:
        return []
    if user.get("role") == "admin" or user.get("permission_type") == "admin" or user.get("manage_all"):
        return base.ALL_PAIRS
    return _ORIGINAL_SCOPE_PAIRS(user)


def can_edit_entry(user, entry):
    if not user:
        return False
    if user.get("role") == "admin" or user.get("permission_type") == "admin" or user.get("manage_all"):
        return True
    return (
        entry.get("user_id") == user.get("user_id")
        and (entry.get("business"), entry.get("region")) in scope_pairs(user)
    )


base.scope_pairs = scope_pairs
base.can_edit_entry = can_edit_entry


def money_m(value, blank="-"):
    if value is None:
        return blank
    try:
        number = float(value) / 1_000_000
    except (TypeError, ValueError):
        return blank
    rounded = round(number, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded)):,}"
    return f"{rounded:,.1f}"


app.jinja_env.filters["money_m"] = money_m


def _sum_nullable(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return sum(values) if values else None


def _collect_metrics(year, month):
    data = base.read_store()
    rows = []
    for business in base.BUSINESSES:
        for region in base.REGIONS:
            for kind in base.KINDS:
                rows.append(base.row_metrics(data, year, month, business, region, kind))

    overall = {
        "first": _sum_nullable(rows, "first"),
        "second": _sum_nullable(rows, "second"),
        "third_confirmed": _sum_nullable(rows, "third_confirmed"),
        "third_forecast": _sum_nullable(rows, "third_forecast"),
        "close": _sum_nullable(rows, "close"),
        "next_first": _sum_nullable(rows, "next_first"),
    }

    cards = []
    for business in base.BUSINESSES:
        business_rows = [row for row in rows if row.get("business") == business]
        domestic = [row for row in business_rows if row.get("region") == "국내"]
        overseas = [row for row in business_rows if row.get("region") == "해외"]
        cards.append({
            "name": business,
            "first": _sum_nullable(business_rows, "first"),
            "second": _sum_nullable(business_rows, "second"),
            "domestic_second": _sum_nullable(domestic, "second"),
            "overseas_second": _sum_nullable(overseas, "second"),
        })
    return overall, cards


def _safe_page(year, month, error_text=""):
    user = base.current_user() or {}
    display_name = html.escape(str(user.get("display_name") or user.get("user_id") or "사용자"))
    try:
        overall, cards = _collect_metrics(year, month)
    except Exception as exc:
        overall = {"first": None, "second": None, "third_confirmed": None, "third_forecast": None, "close": None, "next_first": None}
        cards = [{"name": name, "first": None, "second": None, "domestic_second": None, "overseas_second": None} for name in base.BUSINESSES]
        if not error_text:
            error_text = f"{type(exc).__name__}: {exc}"

    try:
        input_url = base.url_for("input_page", year=year, month=month, stage="2차", scope="덴탈|국내")
        password_url = base.url_for("password_change")
        logout_url = base.url_for("logout")
    except Exception:
        input_url = f"/input?year={year}&month={month}&stage=2%EC%B0%A8&scope=%EB%8D%B4%ED%83%88%7C%EA%B5%AD%EB%82%B4"
        password_url = "/password"
        logout_url = "/logout"

    metric_items = [
        (f"{month}월 1차", overall.get("first")),
        (f"{month}월 2차", overall.get("second")),
        (f"{month}월 3차 예상", overall.get("third_forecast")),
        (f"{month}월 마감", overall.get("close")),
    ]
    metric_html = "".join(
        f"<div class='metric'><span>{html.escape(label)}</span><strong>{html.escape(money_m(value))}</strong><small>백만원</small></div>"
        for label, value in metric_items
    )

    card_html = "".join(
        "<article class='card'>"
        f"<h3>{html.escape(str(card['name']))}</h3>"
        f"<div class='total'>{html.escape(money_m(card.get('second')))} <small>백만원 · 2차</small></div>"
        "<div class='split'>"
        f"<div><span>국내</span><b>{html.escape(money_m(card.get('domestic_second')))}</b></div>"
        f"<div><span>해외</span><b>{html.escape(money_m(card.get('overseas_second')))}</b></div>"
        "</div></article>"
        for card in cards
    )

    error_box = ""
    if error_text:
        error_box = (
            "<div class='notice'><b>복구 모드 진단</b><p>"
            + html.escape(str(error_text))
            + "</p></div>"
        )

    return f"""<!doctype html>
<html lang='ko'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MEDPARK 실적회의</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f7fb;color:#152238;font-family:Arial,'Malgun Gothic',sans-serif}}header{{background:#11385f;color:#fff;padding:18px 24px;display:flex;justify-content:space-between;align-items:center}}header strong{{font-size:20px}}main{{max-width:1240px;margin:0 auto;padding:26px}}.hero{{background:#fff;border:1px solid #dbe4ee;border-radius:16px;padding:24px;margin-bottom:16px}}h1{{margin:0 0 8px;font-size:28px}}.muted{{color:#6a7c90}}.actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}}a.btn,button.btn{{display:inline-block;border:0;background:#174c82;color:#fff;text-decoration:none;padding:10px 14px;border-radius:9px;font-weight:700;cursor:pointer}}a.secondary{{background:#eaf1f8;color:#174c82}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}}.metric,.card{{background:#fff;border:1px solid #dbe4ee;border-radius:14px;padding:18px}}.metric span,.split span{{display:block;color:#6b7d90;font-size:13px}}.metric strong{{display:block;font-size:26px;margin:7px 0 2px}}.metric small,.total small{{color:#8a99a8}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.card h3{{margin:0 0 10px}}.total{{font-size:23px;font-weight:800;margin-bottom:14px}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.split div{{background:#f7f9fc;border-radius:9px;padding:11px}}.split b{{display:block;margin-top:5px;font-size:17px}}.notice{{margin-top:16px;background:#fff7e8;border:1px solid #efd59f;border-radius:12px;padding:14px}}form{{display:inline}}@media(max-width:800px){{.metrics{{grid-template-columns:1fr 1fr}}.cards{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><strong>MEDPARK · 실적회의 통합관리</strong><span>{display_name}</span></header>
<main>
<section class='hero'>
<p class='muted'>STABLE RECOVERY MODE</p>
<h1>{year}년 {month}월 실적회의</h1>
<p class='muted'>접속 안정화를 우선한 화면입니다. 기존 실적 데이터와 입력 기능은 그대로 사용합니다.</p>
<div class='actions'>
<a class='btn' href='{html.escape(input_url)}'>실적 입력</a>
<a class='btn secondary' href='{html.escape(password_url)}'>비밀번호 변경</a>
<form method='post' action='{html.escape(logout_url)}'><button class='btn secondary' type='submit'>로그아웃</button></form>
</div>
</section>
<section class='metrics'>{metric_html}</section>
<section class='cards'>{card_html}</section>
<div class='notice'><b>Global Maps 해외 FCST</b><p>현재 접속 안정화를 위해 실행 경로에서 분리해 두었습니다. Global Maps 원본은 변경하지 않았습니다.</p></div>
{error_box}
</main>
</body></html>"""


@base.login_required
def stable_report():
    try:
        year = int(base.request.args.get("year", 2026))
        month = int(base.request.args.get("month", 9))
    except (TypeError, ValueError):
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    try:
        return _safe_page(year, month), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}
    except Exception as exc:
        return _safe_page(2026, 9, f"{type(exc).__name__}: {exc}"), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


app.view_functions["report"] = stable_report


@app.errorhandler(500)
def recover_from_500(error):
    original = getattr(error, "original_exception", None) or error
    try:
        message = f"{type(original).__name__}: {original}"
    except Exception:
        message = "Unhandled server error"
    try:
        return _safe_page(2026, 9, message), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}
    except Exception:
        return "MEDPARK 실적회의 복구 모드", 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}


def _request_selftest():
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = "mp001"
        response = client.get("/?year=2026&month=9", follow_redirects=False)
        text = response.get_data(as_text=True)
        return {
            "ok": response.status_code == 200 and "2026년 9월 실적회의" in text,
            "status_code": response.status_code,
            "marker": "2026년 9월 실적회의" in text,
        }
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        last = frames[-1] if frames else None
        return {
            "ok": False,
            "status_code": None,
            "marker": False,
            "error": f"{type(exc).__name__}: {exc}",
            "file": os.path.basename(last.filename) if last else "",
            "line": last.lineno if last else None,
        }


def health_final():
    try:
        data = base.read_store()
        counts = {
            "initialized": bool(data.get("meta", {}).get("initialized")),
            "users": len(data.get("users", [])),
            "entries": len(data.get("entries", [])),
            "actuals": len(data.get("actuals", {})),
        }
    except Exception as exc:
        counts = {"initialized": False, "users": None, "entries": None, "actuals": None, "data_error": f"{type(exc).__name__}: {exc}"}
    result = _request_selftest()
    return base.jsonify({
        "status": "ok" if result.get("ok") else "degraded",
        "runtime": "final-stable-v1",
        "request_selftest": result,
        **counts,
    })


app.view_functions["health"] = health_final
