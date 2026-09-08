import base64
import gzip
import html
import json
import os
import secrets
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, Response, flash, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = "/app/user_data"
DATA_FILE = os.path.join(DATA_DIR, "performance_data.json")
SECRET_FILE = os.path.join(DATA_DIR, ".session_secret")
BUSINESSES = ["덴탈", "메디컬", "에스테틱"]
REGIONS = ["국내", "해외"]
KINDS = ["기존", "신규"]
STAGES = ["1차", "2차", "3차", "마감"]
STATUSES = ["확정", "예상", "추진", "이월", "제외"]
COUNT_STATUSES = {"확정", "예상", "추진"}
ALL_PAIRS = [(b, r) for b in BUSINESSES for r in REGIONS]

os.makedirs(DATA_DIR, exist_ok=True)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_secret():
    configured = os.environ.get("APP_SECRET_KEY", "").strip()
    if configured:
        return configured
    try:
        if os.path.exists(SECRET_FILE):
            value = open(SECRET_FILE, "r", encoding="utf-8").read().strip()
            if value:
                return value
    except Exception:
        pass
    value = secrets.token_urlsafe(48)
    try:
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(value)
    except Exception:
        pass
    return value


app = Flask(__name__)
app.secret_key = load_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)


def blank_store():
    return {"meta": {"initialized": False}, "actuals": {}, "entries": [], "comments": {}, "users": []}


def read_store_raw():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def write_store(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def load_seed():
    packed = os.environ.get("AUTO_SEED_GZ", "").strip()
    if not packed:
        return None
    try:
        raw = gzip.decompress(base64.b64decode(packed)).decode("utf-8")
        seed = json.loads(raw)
        if isinstance(seed, dict) and seed.get("users"):
            seed.setdefault("meta", {})
            seed["meta"]["initialized"] = True
            seed["meta"]["clean_rebuild_seeded_at"] = now_text()
            return seed
    except Exception:
        return None
    return None


def ensure_store():
    try:
        data = read_store_raw() if os.path.exists(DATA_FILE) else None
    except Exception:
        data = None
    if isinstance(data, dict) and data.get("users"):
        data.setdefault("meta", {}).setdefault("initialized", True)
        data.setdefault("actuals", {})
        data.setdefault("entries", [])
        data.setdefault("comments", {})
        return data
    seed = load_seed()
    if seed is not None:
        write_store(seed)
        return seed
    data = blank_store()
    write_store(data)
    return data


def read_store():
    return ensure_store()


def esc(value):
    return html.escape(str(value if value is not None else ""))


def money_m(value):
    if value is None:
        return "-"
    try:
        n = float(value) / 1_000_000
    except Exception:
        return "-"
    if abs(n - round(n)) < 0.05:
        return f"{int(round(n)):,}"
    return f"{n:,.1f}"


def int_value(value):
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except Exception:
        return 0


def get_user(user_id):
    if not user_id:
        return None
    data = read_store()
    for user in data.get("users", []):
        if str(user.get("user_id", "")).lower() == str(user_id).lower() and user.get("active", True):
            return user
    return None


def current_user():
    return get_user(session.get("user_id"))


def scope_pairs(user):
    if not user:
        return []
    if user.get("role") == "admin" or user.get("permission_type") == "admin" or user.get("manage_all"):
        return ALL_PAIRS
    p = user.get("permission_type", "")
    if p == "domestic_all":
        return [(b, "국내") for b in BUSINESSES]
    if p == "dental_domestic":
        return [("덴탈", "국내")]
    if p == "overseas_all":
        return [(b, "해외") for b in BUSINESSES]
    if p == "aesthetics_all":
        return [("에스테틱", "국내"), ("에스테틱", "해외")]
    out = []
    for item in user.get("scopes", []):
        if isinstance(item, list) and len(item) == 2 and tuple(item) in ALL_PAIRS:
            out.append(tuple(item))
    return out


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect("/login?next=" + request.full_path)
        return fn(*args, **kwargs)
    return wrapped


def can_edit(user, entry):
    if not user:
        return False
    if user.get("role") == "admin" or user.get("manage_all"):
        return True
    return entry.get("user_id") == user.get("user_id") and (entry.get("business"), entry.get("region")) in scope_pairs(user)


def actual_key(year, month, business, region, kind):
    return f"{year}-{month:02d}|{business}|{region}|{kind}"


def matching_entries(data, year, month, stage, business=None, region=None, kind=None):
    rows = []
    for e in data.get("entries", []):
        if e.get("year") != year or e.get("month") != month or e.get("stage") != stage:
            continue
        if business is not None and e.get("business") != business:
            continue
        if region is not None and e.get("region") != region:
            continue
        if kind is not None and e.get("kind") != kind:
            continue
        rows.append(e)
    return rows


def stage_total(data, year, month, stage, business=None, region=None, kind=None):
    rows = matching_entries(data, year, month, stage, business, region, kind)
    if not rows:
        return None
    return sum(int_value(e.get("amount")) for e in rows if e.get("status") in COUNT_STATUSES)


def close_total(data, year, month, business=None, region=None, kind=None):
    total = stage_total(data, year, month, "마감", business, region, kind)
    if total is not None:
        return total
    values = []
    for b in ([business] if business else BUSINESSES):
        for r in ([region] if region else REGIONS):
            for k in ([kind] if kind else KINDS):
                v = data.get("actuals", {}).get(actual_key(year, month, b, r, k))
                if v is not None:
                    values.append(int_value(v))
    return sum(values) if values else None


def sync_close_actual(data, year, month, business, region, kind):
    total = stage_total(data, year, month, "마감", business, region, kind)
    if total is not None:
        data.setdefault("actuals", {})[actual_key(year, month, business, region, kind)] = total


def layout(title, body, user=None):
    user_text = esc((user or {}).get("display_name") or (user or {}).get("user_id") or "")
    nav = ""
    if user:
        nav = "<a href='/'>대시보드</a><a href='/input'>실적입력</a>"
        if user.get("role") == "admin" or user.get("manage_all"):
            nav += "<a href='/users'>사용자</a><a href='/export'>백업내보내기</a>"
        nav += "<a href='/password'>비밀번호</a><form method='post' action='/logout' style='display:inline'><button>로그아웃</button></form>"
    return f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)} · MEDPARK</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,'Malgun Gothic',sans-serif;background:#f4f7fb;color:#17233a}}header{{background:#11385f;color:#fff;padding:16px 24px;display:flex;justify-content:space-between;gap:14px;align-items:center}}header strong{{font-size:20px}}nav{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}nav a,nav button{{color:#fff;background:transparent;border:1px solid rgba(255,255,255,.28);padding:7px 10px;border-radius:8px;text-decoration:none;cursor:pointer}}main{{max-width:1250px;margin:0 auto;padding:24px}}.panel{{background:#fff;border:1px solid #dbe4ee;border-radius:14px;padding:20px;margin-bottom:14px}}.grid4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.kpi{{background:#fff;border:1px solid #dbe4ee;border-radius:13px;padding:18px}}.kpi span{{display:block;color:#6c7e91;font-size:13px}}.kpi strong{{display:block;font-size:27px;margin:7px 0}}.btn,button.primary{{background:#174c82;color:#fff;border:0;border-radius:8px;padding:10px 14px;text-decoration:none;cursor:pointer;font-weight:700}}input,select,textarea{{width:100%;padding:9px;border:1px solid #ccd8e5;border-radius:8px;background:#fff}}label{{display:block;margin-bottom:10px;font-weight:700}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:9px;border-bottom:1px solid #e4ebf2;text-align:left}}th{{background:#f0f4f8}}.flash{{padding:11px 14px;border-radius:9px;margin-bottom:12px;background:#eef5ff}}.muted{{color:#6c7e91}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.split div{{background:#f6f8fb;padding:10px;border-radius:8px}}@media(max-width:800px){{.grid4,.grid3{{grid-template-columns:1fr 1fr}}header{{align-items:flex-start;flex-direction:column}}}}@media(max-width:520px){{.grid4,.grid3{{grid-template-columns:1fr}}}}</style></head><body><header><strong>MEDPARK · 실적회의</strong><div><nav>{nav}</nav><small>{user_text}</small></div></header><main>{body}</main></body></html>"""


def flashes():
    from flask import get_flashed_messages
    return "".join(f"<div class='flash'>{esc(m)}</div>" for m in get_flashed_messages())


@app.get("/health")
def health():
    data = read_store()
    return {
        "status": "ok",
        "runtime": "clean-rebuild-v1",
        "initialized": bool(data.get("meta", {}).get("initialized")),
        "users": len(data.get("users", [])),
        "entries": len(data.get("entries", [])),
        "actuals": len(data.get("actuals", {})),
        "seed_available": bool(os.environ.get("AUTO_SEED_GZ", "").strip()),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect("/")
    msg = flashes()
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip().lower()
        password = request.form.get("password", "")
        user = get_user(user_id)
        if user and check_password_hash(user.get("password_hash", ""), password):
            session.clear()
            session["user_id"] = user.get("user_id")
            return redirect("/")
        flash("아이디 또는 비밀번호를 확인하세요.")
        return redirect("/login")
    seed_missing = not bool(read_store().get("users"))
    warning = "<div class='flash'>초기 사용자 데이터가 없습니다. AUTO_SEED_GZ 확인이 필요합니다.</div>" if seed_missing else ""
    body = f"""{msg}{warning}<section class='panel' style='max-width:420px;margin:60px auto'><h1>실적회의 로그인</h1><p class='muted'>공간4 CLEAN REBUILD</p><form method='post'><label>아이디<input name='user_id' autocomplete='username' required></label><label>비밀번호<input type='password' name='password' autocomplete='current-password' required></label><button class='primary' type='submit'>로그인</button></form></section>"""
    return layout("로그인", body)


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/")
@login_required
def dashboard():
    user = current_user()
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    data = read_store()
    first = stage_total(data, year, month, "1차")
    second = stage_total(data, year, month, "2차")
    third = stage_total(data, year, month, "3차")
    close = close_total(data, year, month)
    kpis = [("1차 예상", first), ("2차 예상", second), ("3차 예상", third), ("마감", close)]
    kpi_html = "".join(f"<div class='kpi'><span>{label}</span><strong>{money_m(value)}</strong><small>백만원</small></div>" for label, value in kpis)
    cards = []
    for b in BUSINESSES:
        total2 = stage_total(data, year, month, "2차", b)
        dom2 = stage_total(data, year, month, "2차", b, "국내")
        ov2 = stage_total(data, year, month, "2차", b, "해외")
        cards.append(f"<article class='panel'><h3>{esc(b)}</h3><div style='font-size:24px;font-weight:800'>{money_m(total2)} <small>백만원</small></div><div class='split'><div><span class='muted'>국내 2차</span><b>{money_m(dom2)}</b></div><div><span class='muted'>해외 2차</span><b>{money_m(ov2)}</b></div></div></article>")
    body = f"""{flashes()}<section class='panel'><h1>{year}년 {month}월 실적회의</h1><p class='muted'>새로 구축한 독립 실행판 · Global Maps는 아직 연결하지 않음</p><form method='get' style='display:flex;gap:8px;max-width:350px'><select name='year'>{''.join(f'<option value="{y}" '+('selected' if y==year else '')+f'>{y}</option>' for y in [2025,2026,2027])}</select><select name='month'>{''.join(f'<option value="{m}" '+('selected' if m==month else '')+f'>{m}월</option>' for m in range(1,13))}</select><button class='primary'>조회</button></form></section><section class='grid4'>{kpi_html}</section><section class='grid3' style='margin-top:12px'>{''.join(cards)}</section>"""
    return layout("대시보드", body, user)


@app.route("/input", methods=["GET", "POST"])
@login_required
def input_page():
    user = current_user()
    pairs = scope_pairs(user)
    if not pairs:
        return layout("권한없음", "<div class='panel'>입력 권한이 없습니다.</div>", user), 403
    try:
        year = int(request.values.get("year", 2026))
        month = int(request.values.get("month", 9))
    except Exception:
        year, month = 2026, 9
    stage = request.values.get("stage", "2차")
    if stage not in STAGES:
        stage = "2차"
    scope = request.values.get("scope", "")
    selected = pairs[0]
    if "|" in scope:
        candidate = tuple(scope.split("|", 1))
        if candidate in pairs:
            selected = candidate
    business, region = selected
    if request.method == "POST" and request.form.get("action") == "add":
        kind = request.form.get("kind", "기존")
        status = request.form.get("status", "예상")
        if kind not in KINDS:
            kind = "기존"
        if status not in STATUSES:
            status = "예상"
        if stage == "마감":
            status = "확정"
        data = read_store()
        data.setdefault("entries", []).append({
            "id": str(uuid.uuid4()), "year": year, "month": month, "stage": stage,
            "business": business, "region": region, "kind": kind, "status": status,
            "item": request.form.get("item", "").strip() or "미기재",
            "amount": int_value(request.form.get("amount")),
            "note": request.form.get("note", "").strip(),
            "writer": user.get("display_name", ""), "user_id": user.get("user_id"),
            "updated_at": now_text(), "seeded": False,
        })
        if stage == "마감":
            sync_close_actual(data, year, month, business, region, kind)
        write_store(data)
        flash("저장했습니다.")
        return redirect(f"/input?year={year}&month={month}&stage={stage}&scope={business}%7C{region}")
    data = read_store()
    rows = [e for e in data.get("entries", []) if e.get("year")==year and e.get("month")==month and e.get("stage")==stage and e.get("business")==business and e.get("region")==region]
    pair_opts = "".join(f"<option value='{esc(b)}|{esc(r)}' {'selected' if (b,r)==selected else ''}>{esc(b)} · {esc(r)}</option>" for b,r in pairs)
    stage_opts = "".join(f"<option value='{s}' {'selected' if s==stage else ''}>{s}</option>" for s in STAGES)
    rows_html = "".join(f"<tr><td>{esc(e.get('kind'))}</td><td>{esc(e.get('status'))}</td><td>{esc(e.get('item'))}</td><td>{money_m(e.get('amount'))}</td><td>{esc(e.get('writer'))}</td><td>{esc(e.get('note'))}</td></tr>" for e in rows) or "<tr><td colspan='6'>입력내역 없음</td></tr>"
    body = f"""{flashes()}<section class='panel'><h1>{year}년 {month}월 {stage} 실적입력</h1><form method='get' style='display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px'><input type='number' name='year' value='{year}'><input type='number' name='month' min='1' max='12' value='{month}'><select name='stage'>{stage_opts}</select><select name='scope'>{pair_opts}</select><button class='primary'>조회</button></form></section><section class='panel'><form method='post'><input type='hidden' name='action' value='add'><input type='hidden' name='year' value='{year}'><input type='hidden' name='month' value='{month}'><input type='hidden' name='stage' value='{esc(stage)}'><input type='hidden' name='scope' value='{esc(business)}|{esc(region)}'><div class='grid3'><label>기존/신규<select name='kind'>{''.join(f'<option>{k}</option>' for k in KINDS)}</select></label><label>상태<select name='status'>{''.join(f'<option>{s}</option>' for s in STATUSES)}</select></label><label>금액(원)<input name='amount' inputmode='numeric' required></label></div><label>항목<input name='item'></label><label>메모<textarea name='note' rows='3'></textarea></label><button class='primary'>저장</button></form></section><section class='panel'><h2>현재 입력내역</h2><div style='overflow:auto'><table><thead><tr><th>구분</th><th>상태</th><th>항목</th><th>금액(백만원)</th><th>작성자</th><th>메모</th></tr></thead><tbody>{rows_html}</tbody></table></div></section>"""
    return layout("실적입력", body, user)


@app.route("/password", methods=["GET", "POST"])
@login_required
def password_change():
    user = current_user()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(user.get("password_hash", ""), current):
            flash("현재 비밀번호가 맞지 않습니다.")
        elif len(new) < 8:
            flash("새 비밀번호는 8자 이상이어야 합니다.")
        elif new != confirm:
            flash("새 비밀번호 확인이 일치하지 않습니다.")
        else:
            data = read_store()
            target = next((u for u in data.get("users", []) if u.get("user_id")==user.get("user_id")), None)
            if target:
                target["password_hash"] = generate_password_hash(new)
                target["updated_at"] = now_text()
                write_store(data)
                flash("비밀번호를 변경했습니다.")
                return redirect("/")
    body = f"""{flashes()}<section class='panel' style='max-width:500px'><h1>비밀번호 변경</h1><form method='post'><label>현재 비밀번호<input type='password' name='current_password' required></label><label>새 비밀번호<input type='password' name='new_password' required></label><label>새 비밀번호 확인<input type='password' name='confirm_password' required></label><button class='primary'>변경</button></form></section>"""
    return layout("비밀번호", body, user)


@app.get("/users")
@login_required
def users_page():
    user = current_user()
    if not (user.get("role") == "admin" or user.get("manage_all")):
        return layout("권한없음", "<div class='panel'>관리 권한이 없습니다.</div>", user), 403
    rows = "".join(f"<tr><td>{esc(u.get('user_id'))}</td><td>{esc(u.get('display_name'))}</td><td>{esc(u.get('role'))}</td><td>{esc(u.get('permission_type'))}</td><td>{'사용' if u.get('active',True) else '중지'}</td></tr>" for u in read_store().get("users", []))
    return layout("사용자", f"<section class='panel'><h1>사용자 현황</h1><table><thead><tr><th>ID</th><th>이름</th><th>역할</th><th>권한</th><th>상태</th></tr></thead><tbody>{rows}</tbody></table></section>", user)


@app.get("/export")
@login_required
def export_data():
    user = current_user()
    if not (user.get("role") == "admin" or user.get("manage_all")):
        return "forbidden", 403
    payload = json.dumps(read_store(), ensure_ascii=False, indent=2)
    return Response(payload, mimetype="application/json", headers={"Content-Disposition": "attachment; filename=performance_data_export.json"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False, use_reloader=False)
