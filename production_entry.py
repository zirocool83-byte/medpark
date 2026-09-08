import html
import json
import os
import traceback

import app as base

app = base.app
STATUS_FILE = os.path.join(base.DATA_DIR, ".global_fcst_status.json")
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


def can_manage_report(user):
    return bool(user and (user.get("role") == "admin" or user.get("permission_type") == "admin" or user.get("manage_all")))


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


def load_fcst_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict):
            return {
                "connected": bool(value.get("connected")),
                "saved": bool(value.get("saved")),
                "row_count": value.get("row_count"),
                "checked_at": str(value.get("checked_at") or ""),
                "message": str(value.get("message") or ""),
            }
    except Exception:
        pass
    return {
        "connected": False,
        "saved": False,
        "row_count": None,
        "checked_at": "",
        "message": "Global Maps 연동은 앱 안정화 후 다시 연결합니다.",
    }


@app.context_processor
def stable_context():
    return {"global_fcst_status": load_fcst_status()}


def _safe_comments(data, year, month):
    root = data.get("comments", {})
    if not isinstance(root, dict):
        root = {}
    value = root.get(f"{year}-{month:02d}", {})
    if not isinstance(value, dict):
        value = {}
    parts = value.get("parts", {})
    if not isinstance(parts, dict):
        parts = {}
    return {
        "top": str(value.get("top") or ""),
        "bottom": str(value.get("bottom") or ""),
        "updated_by": str(value.get("updated_by") or ""),
        "updated_at": str(value.get("updated_at") or ""),
        "parts": parts,
    }


def _sum_nullable(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return sum(values) if values else None


def report_data_stable(year, month):
    data = base.read_store()
    details = []
    display = []

    for business in base.BUSINESSES:
        group = []
        for region in base.REGIONS:
            for kind in base.KINDS:
                row = base.row_metrics(data, year, month, business, region, kind)
                details.append(row)
                group.append(row)
                display.append(row)
        display.append(base.sum_rows(group, f"{business} 소계", business))

    grand = base.sum_rows(details, f"{year}년 전체")
    display.append(grand)

    parts_status = []
    for business in base.BUSINESSES:
        for region in base.REGIONS:
            rows = [r for r in details if r.get("business") == business and r.get("region") == region]
            parts_status.append({
                "name": f"{business} {region}",
                "done": bool(rows) and all(r.get("close_has") for r in rows),
            })

    close_done = sum(1 for p in parts_status if p["done"])
    third_total = grand.get("third_forecast")
    close_total = grand.get("close") if grand.get("close_has") else None
    diff = close_total - third_total if close_total is not None and third_total is not None else None
    error_rate = abs(diff) / third_total if diff is not None and third_total else None

    comments = _safe_comments(data, year, month)
    user = base.current_user()
    manage_all = can_manage_report(user)
    editable_pairs = set(base.ALL_PAIRS if manage_all else scope_pairs(user))

    part_notes = []
    has_part_notes = False
    for business in base.BUSINESSES:
        for region in base.REGIONS:
            note_key = f"{business}|{region}"
            saved = comments["parts"].get(note_key, {})
            if not isinstance(saved, dict):
                saved = {}
            summary = str(saved.get("summary") or "").strip()
            risk = str(saved.get("risk") or "").strip()
            action = str(saved.get("action") or "").strip()
            has_note = bool(summary or risk or action)
            has_part_notes = has_part_notes or has_note
            part_notes.append({
                "key": note_key,
                "business": business,
                "region": region,
                "name": f"{business} {region}",
                "summary": summary,
                "risk": risk,
                "action": action,
                "updated_by": str(saved.get("updated_by") or ""),
                "updated_at": str(saved.get("updated_at") or ""),
                "has": has_note,
                "can_edit": (business, region) in editable_pairs,
            })

    dashboard = {
        "prev_close": grand.get("prev_close"),
        "first": grand.get("first"),
        "second": grand.get("second"),
        "third_confirmed": grand.get("third_confirmed"),
        "third_forecast": grand.get("third_forecast"),
        "close": grand.get("close"),
        "next_first": grand.get("next_first"),
        "delta_12": (
            grand.get("second") - grand.get("first")
            if grand.get("second") is not None and grand.get("first") is not None
            else None
        ),
    }

    business_cards = []
    for business in base.BUSINESSES:
        business_rows = [r for r in details if r.get("business") == business]
        domestic = [r for r in business_rows if r.get("region") == "국내"]
        overseas = [r for r in business_rows if r.get("region") == "해외"]
        first = _sum_nullable(business_rows, "first")
        second = _sum_nullable(business_rows, "second")
        business_cards.append({
            "name": business,
            "first": first,
            "second": second,
            "third": _sum_nullable(business_rows, "third_forecast"),
            "domestic_first": _sum_nullable(domestic, "first"),
            "domestic_second": _sum_nullable(domestic, "second"),
            "overseas_first": _sum_nullable(overseas, "first"),
            "overseas_second": _sum_nullable(overseas, "second"),
            "delta_12": second - first if second is not None and first is not None else None,
        })

    return {
        "year": year,
        "month": month,
        "rows": display,
        "details": details,
        "comments": comments,
        "parts": parts_status,
        "close_done": close_done,
        "close_total": close_total,
        "third_total": third_total,
        "diff": diff,
        "error_rate": error_rate,
        "prev_month": 12 if month == 1 else month - 1,
        "next_month": 1 if month == 12 else month + 1,
        "quarter": (month - 1) // 3 + 1,
        "part_notes": part_notes,
        "has_part_notes": has_part_notes,
        "can_manage_report": manage_all,
        "dashboard": dashboard,
        "business_cards": business_cards,
    }


base.report_data = report_data_stable


def _fallback_report(year, month, report=None, error=None):
    user = base.current_user() or {}
    name = html.escape(str(user.get("display_name") or "사용자"))
    err = html.escape(f"{type(error).__name__}: {error}" if error else "")
    first = money_m((report or {}).get("dashboard", {}).get("first"))
    second = money_m((report or {}).get("dashboard", {}).get("second"))
    third = money_m((report or {}).get("dashboard", {}).get("third_forecast"))
    close = money_m((report or {}).get("dashboard", {}).get("close"))
    return f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>MEDPARK 실적회의</title><style>body{{font-family:Arial,'Malgun Gothic',sans-serif;margin:0;background:#f3f6fa;color:#172033}}header{{background:#12335a;color:#fff;padding:18px 24px}}main{{max-width:1200px;margin:0 auto;padding:24px}}.card{{background:#fff;border:1px solid #d6e0ea;border-radius:14px;padding:20px;margin-bottom:16px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.kpi{{border:1px solid #d6e0ea;border-radius:10px;padding:16px}}.kpi span{{display:block;color:#6b7b8f;font-size:12px}}.kpi strong{{display:block;font-size:24px;margin-top:7px}}a{{display:inline-block;background:#17477f;color:#fff;text-decoration:none;padding:10px 14px;border-radius:8px;margin-right:8px}}.warn{{background:#fff7e6;border-color:#edd29c}}@media(max-width:700px){{.grid{{grid-template-columns:1fr 1fr}}}}</style></head><body><header><strong>MEDPARK</strong> · 실적회의 통합관리 <span style='float:right'>{name}</span></header><main><div class='card'><h1>{year}년 {month}월 실적회의</h1><p>메인 화면 오류를 우회한 안전 모드입니다. 데이터와 입력 기능은 유지됩니다.</p><a href='/input?year={year}&month={month}&stage=2%EC%B0%A8'>실적입력</a><a href='/password'>비밀번호</a></div><div class='card grid'><div class='kpi'><span>{month}월 1차</span><strong>{first}</strong></div><div class='kpi'><span>{month}월 2차</span><strong>{second}</strong></div><div class='kpi'><span>{month}월 3차 예상</span><strong>{third}</strong></div><div class='kpi'><span>{month}월 마감</span><strong>{close}</strong></div></div><div class='card warn'><strong>진단 정보</strong><p>{err or '전체 화면 렌더링 오류를 감지해 안전 화면으로 전환했습니다.'}</p></div></main></body></html>""", 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


@base.login_required
def safe_report_view():
    try:
        year = int(base.request.args.get("year", 2026))
        month = int(base.request.args.get("month", 9))
    except (TypeError, ValueError):
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    capture = base.request.args.get("capture") == "1"
    report = None
    try:
        report = report_data_stable(year, month)
        try:
            return base.render_template("report.html", report=report, capture=capture)
        except Exception as exc:
            return _fallback_report(year, month, report, exc)
    except Exception as exc:
        return _fallback_report(year, month, report, exc)


app.view_functions["report"] = safe_report_view


@app.before_request
def september_default():
    if base.request.method == "GET" and base.request.path == "/" and "month" not in base.request.args and base.current_user():
        return base.redirect(base.url_for("report", year=2026, month=9))
    return None


def save_comments_stable():
    user = base.current_user()
    if not user:
        return base.redirect(base.url_for("login", next=base.request.full_path))
    try:
        year = int(base.request.form.get("year", 2026))
        month = int(base.request.form.get("month", 9))
    except (TypeError, ValueError):
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9

    mode = base.request.form.get("mode", "overall")
    if mode == "global_fcst":
        base.flash("Global Maps 연동은 앱 안정화 후 다시 연결합니다.", "error")
        return base.redirect(base.url_for("report", year=year, month=month))

    data = base.read_store()
    root = data.setdefault("comments", {})
    if not isinstance(root, dict):
        root = {}
        data["comments"] = root
    bucket = root.setdefault(f"{year}-{month:02d}", {})
    if not isinstance(bucket, dict):
        bucket = {}
        root[f"{year}-{month:02d}"] = bucket
    parts = bucket.setdefault("parts", {})
    if not isinstance(parts, dict):
        parts = {}
        bucket["parts"] = parts

    if mode == "part":
        raw_scope = base.request.form.get("scope", "")
        if "|" not in raw_scope:
            base.flash("담당 파트를 확인하세요.", "error")
            return base.redirect(base.url_for("report", year=year, month=month))
        business, region = raw_scope.split("|", 1)
        pair = (business, region)
        if pair not in base.ALL_PAIRS or (not can_manage_report(user) and pair not in scope_pairs(user)):
            base.flash("해당 파트의 실적자료 작성 권한이 없습니다.", "error")
            return base.redirect(base.url_for("report", year=year, month=month))
        parts[raw_scope] = {
            "summary": base.request.form.get("summary", "").strip(),
            "risk": base.request.form.get("risk", "").strip(),
            "action": base.request.form.get("action", "").strip(),
            "updated_by": user.get("display_name", ""),
            "updated_at": base.now_text(),
        }
    else:
        if not can_manage_report(user):
            base.flash("전체 실적자료 수정 권한이 없습니다.", "error")
            return base.redirect(base.url_for("report", year=year, month=month))
        bucket["top"] = base.request.form.get("top", "").strip()
        bucket["bottom"] = base.request.form.get("bottom", "").strip()
        bucket["updated_by"] = user.get("display_name", "")
        bucket["updated_at"] = base.now_text()

    base.write_store(data)
    base.flash("실적자료를 저장했습니다.", "success")
    return base.redirect(base.url_for("report", year=year, month=month))


app.view_functions["save_comments"] = save_comments_stable


def _render_selftest():
    try:
        with app.test_request_context("/?year=2026&month=9"):
            base.session["user_id"] = "mp001"
            report = report_data_stable(2026, 9)
            base.render_template("report.html", report=report, capture=False)
        return {"ok": True, "error": ""}
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        last = frames[-1] if frames else None
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "file": os.path.basename(last.filename) if last else "",
            "line": last.lineno if last else None,
            "function": last.name if last else "",
        }


def health_stable():
    data = base.read_store()
    return base.jsonify({
        "status": "ok",
        "runtime": "safe-report-v2",
        "initialized": bool(data.get("meta", {}).get("initialized")),
        "users": len(data.get("users", [])),
        "entries": len(data.get("entries", [])),
        "actuals": len(data.get("actuals", {})),
        "report_render": _render_selftest(),
    })


app.view_functions["health"] = health_stable
