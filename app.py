import base64
import hashlib
import hmac
import json
import os
import shutil
import struct
import threading
import uuid
from datetime import datetime
from functools import wraps
import secrets

from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "/app/user_data")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "performance_data.json")
BOOTSTRAP_FILE = os.path.join(BASE_DIR, "bootstrap.enc")
SECRET_FILE = os.path.join(DATA_DIR, ".session_secret")
LOCK = threading.RLock()

def load_session_secret():
    configured = os.environ.get("APP_SECRET_KEY", "").strip()
    if configured:
        return configured
    if os.path.exists(SECRET_FILE):
        return open(SECRET_FILE, "r", encoding="utf-8").read().strip()
    value = secrets.token_urlsafe(48)
    with open(SECRET_FILE, "w", encoding="utf-8") as f:
        f.write(value)
    return value

app = Flask(__name__)
app.secret_key = load_session_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)

BUSINESSES = ["덴탈", "메디컬", "에스테틱"]
REGIONS = ["국내", "해외"]
KINDS = ["기존", "신규"]
STAGES = ["1차", "2차", "3차", "마감"]
STATUSES = ["확정", "예상", "추진", "이월", "제외"]
COUNT_STATUSES = {"확정", "예상", "추진"}

PERMISSION_LABELS = {
    "admin": "전체 관리",
    "domestic_all": "국내 전체",
    "dental_domestic": "국내 덴탈",
    "overseas_all": "해외 전체",
    "aesthetics_all": "에스테틱 전체",
}
ALL_PAIRS = [(b, r) for b in BUSINESSES for r in REGIONS]


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def blank_store():
    return {
        "meta": {"initialized": False},
        "actuals": {},
        "entries": [],
        "comments": {},
        "users": [],
    }


def ensure_store():
    if not os.path.exists(DATA_FILE):
        write_store(blank_store())
        return
    try:
        data = read_store_raw()
    except Exception:
        backup = DATA_FILE + ".broken." + datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(DATA_FILE, backup)
        write_store(blank_store())
        return
    changed = False
    for key, default in (
        ("meta", {"initialized": False}),
        ("actuals", {}),
        ("entries", []),
        ("comments", {}),
        ("users", []),
    ):
        if key not in data:
            data[key] = default
            changed = True
    if "initialized" not in data["meta"]:
        data["meta"]["initialized"] = False
        changed = True
    if changed:
        write_store(data)


def read_store_raw():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def read_store():
    with LOCK:
        ensure_store()
        return read_store_raw()


def write_store(data):
    with LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def is_initialized():
    try:
        return bool(read_store().get("meta", {}).get("initialized"))
    except Exception:
        return False


def money(value, blank="-"):
    if value is None:
        return blank
    return f"{int(round(value)):,}"


def pct(value, blank="-"):
    if value is None:
        return blank
    return f"{value * 100:.1f}%"


app.jinja_env.filters["money"] = money
app.jinja_env.filters["pct"] = pct


def decrypt_bootstrap(setup_key):
    raw = open(BOOTSTRAP_FILE, "r", encoding="utf-8").read().strip()
    packed = base64.urlsafe_b64decode(raw.encode("ascii"))
    if len(packed) < 48:
        raise ValueError("bootstrap payload error")
    nonce, body, tag = packed[:16], packed[16:-32], packed[-32:]
    master = hashlib.sha256(setup_key.encode("utf-8")).digest()
    enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"mac", hashlib.sha256).digest()
    expected = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("setup key mismatch")
    plain = bytearray()
    counter = 0
    for offset in range(0, len(body), 32):
        block = body[offset : offset + 32]
        stream = hmac.new(
            enc_key, nonce + struct.pack(">Q", counter), hashlib.sha256
        ).digest()
        plain.extend(bytes(a ^ b for a, b in zip(block, stream)))
        counter += 1
    return json.loads(bytes(plain).decode("utf-8"))


def seed_from_bootstrap(setup_key):
    data = decrypt_bootstrap(setup_key)
    if not isinstance(data, dict):
        raise ValueError("invalid bootstrap")
    users = data.get("users", [])
    for user in users:
        password = user.pop("initial_password", "medpark2026")
        user["password_hash"] = generate_password_hash(password)
        user["created_at"] = now_text()
        user["updated_at"] = now_text()
    data.setdefault("meta", {})
    data["meta"]["initialized"] = True
    data["meta"]["initialized_at"] = now_text()
    if os.path.exists(DATA_FILE):
        backup = DATA_FILE + ".before_setup." + datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(DATA_FILE, backup)
    write_store(data)


def get_user(user_id):
    if not user_id:
        return None
    data = read_store()
    for user in data.get("users", []):
        if user.get("user_id") == user_id and user.get("active", True):
            return user
    return None


def current_user():
    return get_user(session.get("user_id"))


def scope_pairs(user):
    if not user:
        return []
    p = user.get("permission_type", "")
    if user.get("role") == "admin" or p == "admin":
        return ALL_PAIRS
    if p == "domestic_all":
        return [(b, "국내") for b in BUSINESSES]
    if p == "dental_domestic":
        return [("덴탈", "국내")]
    if p == "overseas_all":
        return [(b, "해외") for b in BUSINESSES]
    if p == "aesthetics_all":
        return [("에스테틱", "국내"), ("에스테틱", "해외")]
    custom = []
    for item in user.get("scopes", []):
        if isinstance(item, list) and len(item) == 2 and tuple(item) in ALL_PAIRS:
            custom.append(tuple(item))
    return custom


def can_access_pair(user, business, region):
    return (business, region) in scope_pairs(user)


def can_edit_entry(user, entry):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return (
        entry.get("user_id") == user.get("user_id")
        and can_access_pair(user, entry.get("business"), entry.get("region"))
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user.get("role") != "admin":
            flash("관리자 권한이 필요합니다.", "error")
            return redirect(url_for("report"))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def route_guard():
    endpoint = request.endpoint or ""
    public = {"static", "setup", "health"}
    if endpoint in public:
        return None
    if not is_initialized():
        return redirect(url_for("setup"))
    if endpoint == "login":
        return None
    if not current_user():
        return redirect(url_for("login", next=request.full_path))
    return None


@app.context_processor
def inject_context():
    user = current_user()
    return {
        "current_user": user,
        "permission_label": PERMISSION_LABELS.get((user or {}).get("permission_type", ""), "-"),
    }


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if is_initialized():
        return redirect(url_for("login") if not current_user() else url_for("report"))
    key = request.args.get("key", "").strip() if request.method == "GET" else request.form.get("key", "").strip()
    if key:
        try:
            seed_from_bootstrap(key)
            flash("초기 실적자료와 사용자 계정을 적용했습니다.", "success")
            return redirect(url_for("login"))
        except Exception:
            flash("초기 설정키가 맞지 않습니다.", "error")
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("report"))
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip().lower()
        password = request.form.get("password", "")
        data = read_store()
        user = next((u for u in data.get("users", []) if u.get("user_id", "").lower() == user_id and u.get("active", True)), None)
        if user and check_password_hash(user.get("password_hash", ""), password):
            session.clear()
            session["user_id"] = user["user_id"]
            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("report"))
        flash("아이디 또는 비밀번호를 확인하세요.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/password", methods=["GET", "POST"])
@login_required
def password_change():
    user = current_user()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(user.get("password_hash", ""), current):
            flash("현재 비밀번호가 맞지 않습니다.", "error")
        elif len(new) < 8:
            flash("새 비밀번호는 8자 이상으로 입력하세요.", "error")
        elif new != confirm:
            flash("새 비밀번호 확인이 일치하지 않습니다.", "error")
        else:
            data = read_store()
            target = next(u for u in data["users"] if u["user_id"] == user["user_id"])
            target["password_hash"] = generate_password_hash(new)
            target["updated_at"] = now_text()
            write_store(data)
            flash("비밀번호를 변경했습니다.", "success")
            return redirect(url_for("report"))
    return render_template("password.html")


def actual_key(year, month, business, region, kind):
    return f"{year}-{month:02d}|{business}|{region}|{kind}"


def actual_value(data, year, month, business, region, kind):
    return data.get("actuals", {}).get(actual_key(year, month, business, region, kind))


def matching_entries(data, year, month, stage, business, region, kind):
    return [e for e in data.get("entries", []) if e.get("year") == year and e.get("month") == month and e.get("stage") == stage and e.get("business") == business and e.get("region") == region and e.get("kind") == kind]


def snapshot(data, year, month, stage, business, region, kind):
    rows = matching_entries(data, year, month, stage, business, region, kind)
    if not rows:
        return {"has": False, "confirmed": None, "forecast": None, "carryover": 0, "excluded": 0, "rows": []}
    confirmed = sum(e.get("amount", 0) for e in rows if e.get("status") == "확정")
    forecast = sum(e.get("amount", 0) for e in rows if e.get("status") in COUNT_STATUSES)
    carryover = sum(e.get("amount", 0) for e in rows if e.get("status") == "이월")
    excluded = sum(e.get("amount", 0) for e in rows if e.get("status") == "제외")
    return {"has": True, "confirmed": confirmed, "forecast": forecast, "carryover": carryover, "excluded": excluded, "rows": rows}


def best_month(data, year, month, business, region, kind):
    actual = actual_value(data, year, month, business, region, kind)
    if actual is not None:
        return actual
    for stage in ["마감", "3차", "2차", "1차"]:
        snap = snapshot(data, year, month, stage, business, region, kind)
        if snap["has"]:
            return snap["forecast"] or 0
    return 0


def row_metrics(data, year, month, business, region, kind):
    hist = {m: actual_value(data, year, m, business, region, kind) or 0 for m in range(1, month)}
    ytd = sum(hist.values())
    avg = ytd / max(month - 1, 1)
    prev_ytd = sum(actual_value(data, year - 1, m, business, region, kind) or 0 for m in range(1, month))
    growth = ((ytd - prev_ytd) / prev_ytd) if prev_ytd else None
    current = {stage: snapshot(data, year, month, stage, business, region, kind) for stage in STAGES}
    prev_month, prev_year = ((12, year - 1) if month == 1 else (month - 1, year))
    next_month, next_year = ((1, year + 1) if month == 12 else (month + 1, year))
    prev_first = snapshot(data, prev_year, prev_month, "1차", business, region, kind)
    prev_preclose = snapshot(data, prev_year, prev_month, "3차", business, region, kind)
    prev_close = snapshot(data, prev_year, prev_month, "마감", business, region, kind)
    next_first = snapshot(data, next_year, next_month, "1차", business, region, kind)
    close_actual = actual_value(data, year, month, business, region, kind)
    close_snap = current["마감"]
    close = close_snap["forecast"] if close_snap["has"] else close_actual
    close_has = close_snap["has"] or close_actual is not None
    q = (month - 1) // 3 + 1
    qmonths = list(range((q - 1) * 3 + 1, q * 3 + 1))
    qproj = sum(best_month(data, year, m, business, region, kind) for m in qmonths)
    q4 = sum(best_month(data, year, m, business, region, kind) for m in [10, 11, 12])
    second_half = sum(best_month(data, year, m, business, region, kind) for m in range(7, 13))
    return {
        "business": business, "region": region, "kind": kind, "hist": hist,
        "ytd": ytd, "avg": avg, "prev_ytd": prev_ytd, "growth": growth,
        "prev_first": prev_first["forecast"] if prev_first["has"] else None,
        "prev_preclose": prev_preclose["forecast"] if prev_preclose["has"] else None,
        "prev_close": prev_close["forecast"] if prev_close["has"] else actual_value(data, prev_year, prev_month, business, region, kind),
        "first": current["1차"]["forecast"] if current["1차"]["has"] else None,
        "second": current["2차"]["forecast"] if current["2차"]["has"] else None,
        "third_confirmed": current["3차"]["confirmed"] if current["3차"]["has"] else None,
        "third_forecast": current["3차"]["forecast"] if current["3차"]["has"] else None,
        "close": close, "close_has": close_has,
        "next_first": next_first["forecast"] if next_first["has"] else None,
        "carryover": current["3차"]["carryover"] if current["3차"]["has"] else 0,
        "qproj": qproj,
        "october": best_month(data, year, 10, business, region, kind),
        "november": best_month(data, year, 11, business, region, kind),
        "december": best_month(data, year, 12, business, region, kind),
        "q4proj": q4, "second_half": second_half,
    }


def sum_rows(rows, label, business=None):
    def sum_nullable(key):
        values = [r[key] for r in rows if r.get(key) is not None]
        return sum(values) if values else None
    ytd = sum(r["ytd"] for r in rows)
    prev = sum(r["prev_ytd"] for r in rows)
    return {
        "is_total": True, "is_grand": label.endswith("전체"), "label": label,
        "business": business, "region": "[소계]", "kind": "",
        "hist": {m: sum(r["hist"].get(m, 0) for r in rows) for m in range(1, 13)},
        "ytd": ytd, "avg": sum(r["avg"] for r in rows), "prev_ytd": prev,
        "growth": ((ytd - prev) / prev) if prev else None,
        "prev_first": sum_nullable("prev_first"), "prev_preclose": sum_nullable("prev_preclose"),
        "prev_close": sum_nullable("prev_close"), "first": sum_nullable("first"), "second": sum_nullable("second"),
        "third_confirmed": sum_nullable("third_confirmed"), "third_forecast": sum_nullable("third_forecast"),
        "close": sum_nullable("close"), "close_has": all(r.get("close_has") for r in rows),
        "next_first": sum_nullable("next_first"), "carryover": sum(r.get("carryover", 0) for r in rows),
        "qproj": sum(r["qproj"] for r in rows), "october": sum(r["october"] for r in rows),
        "november": sum(r["november"] for r in rows), "december": sum(r["december"] for r in rows),
        "q4proj": sum(r["q4proj"] for r in rows), "second_half": sum(r["second_half"] for r in rows),
    }


def report_data(year, month):
    data = read_store()
    details, display = [], []
    for business in BUSINESSES:
        group = []
        for region in REGIONS:
            for kind in KINDS:
                row = row_metrics(data, year, month, business, region, kind)
                details.append(row); group.append(row); display.append(row)
        display.append(sum_rows(group, f"{business} 소계", business))
    grand = sum_rows(details, f"{year}년 전체")
    display.append(grand)
    top_key = f"{year}-{month:02d}"
    comments = data.get("comments", {}).get(top_key, {"top": "", "bottom": "", "updated_by": "", "updated_at": ""})
    parts = []
    for business in BUSINESSES:
        for region in REGIONS:
            part_rows = [x for x in details if x["business"] == business and x["region"] == region]
            parts.append({"name": f"{business} {region}", "done": all(x["close_has"] for x in part_rows)})
    close_done = sum(1 for p in parts if p["done"])
    third_total = grand["third_forecast"]
    close_total = grand["close"] if grand["close_has"] else None
    diff = close_total - third_total if close_total is not None and third_total is not None else None
    error_rate = abs(diff) / third_total if diff is not None and third_total else None
    return {
        "year": year, "month": month, "rows": display, "details": details, "comments": comments,
        "parts": parts, "close_done": close_done, "close_total": close_total, "third_total": third_total,
        "diff": diff, "error_rate": error_rate, "prev_month": 12 if month == 1 else month - 1,
        "next_month": 1 if month == 12 else month + 1, "quarter": (month - 1) // 3 + 1,
    }


@app.get("/")
@login_required
def report():
    try:
        year = int(request.args.get("year", 2026)); month = int(request.args.get("month", 8))
    except ValueError:
        year, month = 2026, 8
    if month < 1 or month > 12:
        month = 8
    capture = request.args.get("capture") == "1"
    return render_template("report.html", report=report_data(year, month), capture=capture)


def int_value(raw):
    try:
        return int(str(raw or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def sync_actual(data, year, month, business, region, kind):
    snap = snapshot(data, year, month, "마감", business, region, kind)
    if snap["has"]:
        data.setdefault("actuals", {})[actual_key(year, month, business, region, kind)] = snap["forecast"] or 0


@app.route("/input", methods=["GET", "POST"])
@login_required
def input_page():
    user = current_user(); pairs = scope_pairs(user)
    if not pairs:
        flash("입력 권한이 지정되지 않았습니다.", "error"); return redirect(url_for("report"))
    try:
        year = int(request.values.get("year", 2026)); month = int(request.values.get("month", 8))
    except ValueError:
        year, month = 2026, 8
    stage = request.values.get("stage", "3차"); scope = request.values.get("scope", "")
    if stage not in STAGES: stage = "3차"
    selected = pairs[0]
    if "|" in scope:
        business, region = scope.split("|", 1)
        if (business, region) in pairs: selected = (business, region)
    business, region = selected
    if request.method == "POST" and request.form.get("action") == "add":
        kind = request.form.get("kind", "기존"); status = request.form.get("status", "예상")
        if kind not in KINDS: kind = "기존"
        if status not in STATUSES: status = "예상"
        if stage == "마감": status = "확정"
        amount = int_value(request.form.get("amount")); item = request.form.get("item", "").strip() or "미기재"; note = request.form.get("note", "").strip()
        data = read_store()
        data.setdefault("entries", []).append({
            "id": str(uuid.uuid4()), "year": year, "month": month, "stage": stage,
            "business": business, "region": region, "kind": kind, "status": status,
            "item": item, "amount": amount, "note": note, "writer": user["display_name"],
            "user_id": user["user_id"], "updated_at": now_text(), "seeded": False,
        })
        if stage == "마감": sync_actual(data, year, month, business, region, kind)
        write_store(data); flash("저장했습니다. 취합본에 바로 반영됩니다.", "success")
        return redirect(url_for("input_page", year=year, month=month, stage=stage, scope=f"{business}|{region}"))
    data = read_store()
    rows = [e for e in data.get("entries", []) if e.get("year") == year and e.get("month") == month and e.get("stage") == stage and e.get("business") == business and e.get("region") == region]
    rows.sort(key=lambda x: (x.get("kind", ""), x.get("status", ""), x.get("writer", ""), x.get("item", "")))
    for row in rows: row["can_edit"] = can_edit_entry(user, row)
    sums = {s: sum(e.get("amount", 0) for e in rows if e.get("status") == s) for s in STATUSES}
    current = sum(e.get("amount", 0) for e in rows if e.get("status") in COUNT_STATUSES)
    return render_template("input.html", year=year, month=month, stage=stage, business=business, region=region, scope=f"{business}|{region}", allowed_pairs=pairs, rows=rows, sums=sums, current=current, stages=STAGES, statuses=STATUSES, kinds=KINDS)


@app.post("/entry/<entry_id>/edit")
@login_required
def edit_entry(entry_id):
    user = current_user(); data = read_store()
    entry = next((e for e in data.get("entries", []) if e.get("id") == entry_id), None)
    if not entry:
        flash("입력건을 찾을 수 없습니다.", "error"); return redirect(url_for("input_page"))
    if not can_edit_entry(user, entry):
        flash("본인 입력건만 수정할 수 있습니다.", "error"); return redirect(url_for("input_page"))
    kind = request.form.get("kind", entry.get("kind", "기존")); status = request.form.get("status", entry.get("status", "예상"))
    if kind not in KINDS: kind = entry.get("kind", "기존")
    if status not in STATUSES: status = entry.get("status", "예상")
    old_kind = entry.get("kind"); entry["kind"] = kind; entry["status"] = "확정" if entry.get("stage") == "마감" else status
    entry["item"] = request.form.get("item", entry.get("item", "")).strip() or "미기재"; entry["amount"] = int_value(request.form.get("amount")); entry["note"] = request.form.get("note", "").strip(); entry["last_editor"] = user["display_name"]; entry["updated_at"] = now_text(); entry["seeded"] = False
    if entry.get("stage") == "마감":
        sync_actual(data, entry["year"], entry["month"], entry["business"], entry["region"], old_kind)
        sync_actual(data, entry["year"], entry["month"], entry["business"], entry["region"], entry["kind"])
    write_store(data); flash("수정했습니다.", "success")
    return redirect(url_for("input_page", year=entry["year"], month=entry["month"], stage=entry["stage"], scope=f'{entry["business"]}|{entry["region"]}'))


@app.post("/entry/<entry_id>/delete")
@login_required
def delete_entry(entry_id):
    user = current_user(); data = read_store(); target = next((e for e in data.get("entries", []) if e.get("id") == entry_id), None)
    if not target:
        flash("입력건을 찾을 수 없습니다.", "error"); return redirect(url_for("input_page"))
    if not can_edit_entry(user, target):
        flash("본인 입력건만 삭제할 수 있습니다.", "error"); return redirect(url_for("input_page"))
    data["entries"] = [e for e in data["entries"] if e.get("id") != entry_id]
    if target.get("stage") == "마감": sync_actual(data, target["year"], target["month"], target["business"], target["region"], target["kind"])
    write_store(data); flash("삭제했습니다.", "success")
    return redirect(url_for("input_page", year=target["year"], month=target["month"], stage=target["stage"], scope=f'{target["business"]}|{target["region"]}'))


@app.post("/comments")
@admin_required
def save_comments():
    user = current_user(); year = int(request.form.get("year", 2026)); month = int(request.form.get("month", 8)); data = read_store(); key = f"{year}-{month:02d}"
    data.setdefault("comments", {})[key] = {"top": request.form.get("top", "").strip(), "bottom": request.form.get("bottom", "").strip(), "updated_by": user["display_name"], "updated_at": now_text()}
    write_store(data); flash("회의 코멘트를 저장했습니다.", "success")
    return redirect(url_for("report", year=year, month=month))


@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    data = read_store()
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip().lower(); display_name = request.form.get("display_name", "").strip(); permission_type = request.form.get("permission_type", "dental_domestic"); password = request.form.get("password", "") or "medpark2026"
        if not user_id.startswith("mp") or len(user_id) < 5: flash("아이디는 mp001 형식으로 입력하세요.", "error")
        elif not display_name: flash("이름을 입력하세요.", "error")
        elif permission_type not in PERMISSION_LABELS: flash("권한을 확인하세요.", "error")
        elif any(u.get("user_id") == user_id for u in data.get("users", [])): flash("이미 존재하는 아이디입니다.", "error")
        else:
            role = "admin" if permission_type == "admin" else "member"
            data.setdefault("users", []).append({"user_id": user_id, "display_name": display_name, "role": role, "permission_type": permission_type, "active": True, "password_hash": generate_password_hash(password), "created_at": now_text(), "updated_at": now_text()})
            write_store(data); flash("사용자를 추가했습니다.", "success"); return redirect(url_for("users"))
    users_sorted = sorted(data.get("users", []), key=lambda u: u.get("user_id", ""))
    return render_template("users.html", users=users_sorted, permission_labels=PERMISSION_LABELS)


@app.post("/users/<user_id>/reset")
@admin_required
def user_reset(user_id):
    data = read_store(); target = next((u for u in data.get("users", []) if u.get("user_id") == user_id), None)
    if target:
        target["password_hash"] = generate_password_hash("medpark2026"); target["updated_at"] = now_text(); write_store(data); flash(f"{user_id} 비밀번호를 medpark2026으로 초기화했습니다.", "success")
    return redirect(url_for("users"))


@app.post("/users/<user_id>/toggle")
@admin_required
def user_toggle(user_id):
    user = current_user()
    if user_id == user.get("user_id"):
        flash("현재 로그인한 본인 계정은 비활성화할 수 없습니다.", "error"); return redirect(url_for("users"))
    data = read_store(); target = next((u for u in data.get("users", []) if u.get("user_id") == user_id), None)
    if target:
        target["active"] = not target.get("active", True); target["updated_at"] = now_text(); write_store(data); flash("사용자 상태를 변경했습니다.", "success")
    return redirect(url_for("users"))


@app.get("/health")
def health():
    data = read_store()
    return jsonify({"status": "ok", "initialized": bool(data.get("meta", {}).get("initialized")), "users": len(data.get("users", [])), "entries": len(data.get("entries", [])), "actuals": len(data.get("actuals", {})), "seed_version": data.get("meta", {}).get("seed_version", "")})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
