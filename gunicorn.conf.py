import base64
import gzip
import json
import os
from datetime import datetime

DATA_AUDIT_VERSION = "2026-09-08-v3"

# 원본: 실적회의_통합관리_간편형_v2.xlsx / 2. 전년대비(총괄)
# 메디컬 해외 2025는 원본 셀 자체가 #REF!라 임의값을 만들지 않고 제외한다.
REFERENCE_2025 = {
    ("덴탈", "국내"): [335511544, 375179052, 608722454, 352873233, 256739986, 353787874, 337250963, 367850899, 359735402, 330408068, 320436999, 1068741794],
    ("덴탈", "해외"): [155964862, 315392944, 489602621, 694646898, 227522059, 138470265, 121366684, 239898519, 332797660, 293924457, 345038153, 663621452],
    ("메디컬", "국내"): [361676104, 498287439, 419549483, 558869444, 432084383, 445465111, 538971484, 518770725, 480592022, 433882777, 426264450, 639096224],
    ("에스테틱", "국내"): [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 12500000, 23054546],
    ("에스테틱", "해외"): [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
}

# 원본: 1. 사업계획(총괄) (2), 2026년 1~7월 실제 마감
REFERENCE_2026_ACTUAL = {
    ("덴탈", "국내", "기존"): [235976546, 175764592, 239492098, 337401555, 314269677, 388189294, 284191000],
    ("덴탈", "국내", "신규"): [0, 0, 0, 0, 0, 0, 545000],
    ("덴탈", "해외", "기존"): [362580030, 274826416, 423582641, 311693599, 247520053, 567116791, 767798357],
    ("덴탈", "해외", "신규"): [0, 0, 0, 0, 0, 0, 2100000],
    ("메디컬", "국내", "기존"): [601915129, 390623383, 596632926, 635229324, 541589900, 464697041, 527118620],
    ("메디컬", "국내", "신규"): [0, 0, 0, 0, 0, 0, 0],
    ("메디컬", "해외", "기존"): [19235952, 0, 0, 36501012, 9455, 7727897, 0],
    ("메디컬", "해외", "신규"): [0, 0, 0, 0, 0, 0, 0],
    ("에스테틱", "국내", "기존"): [48900000, 125800000, 49800000, 82400000, 84500000, 31600000, 21000000],
    ("에스테틱", "국내", "신규"): [0, 0, 0, 0, 0, 0, 0],
    ("에스테틱", "해외", "기존"): [427272, 683760, 14170702, 90882709, 63436477, 49956855, 0],
    ("에스테틱", "해외", "신규"): [0, 0, 0, 0, 0, 0, 0],
}

# (8월1차, 8월2차, 8월3차확정, 8월3차예상, 9월1차)
REFERENCE_FCST = {
    ("덴탈", "국내", "기존"): (187190152, 187080000, 132634418, 165891910, 140000000),
    ("덴탈", "국내", "신규"): (15000000, 15000000, 5528184, 5528184, 30000000),
    ("덴탈", "해외", "기존"): (836638000, 993681072.623, 553000000, 723000000, 1021000000),
    ("덴탈", "해외", "신규"): (30030000, 0, 0, 0, 29000000),
    ("메디컬", "국내", "기존"): (496573000, 512000000, 428803782, 532869896, 510250384),
    ("메디컬", "국내", "신규"): (13600000, 14000000, 6120000, 6120000, 21000000),
    ("메디컬", "해외", "기존"): (0, 0, 34000000, 34000000, 8000000),
    ("메디컬", "해외", "신규"): (50372000, 34084050, 0, 0, 0),
    ("에스테틱", "국내", "기존"): (10000000, 5000000, 7000000, 7000000, 7000000),
    ("에스테틱", "국내", "신규"): (0, 0, 0, 0, 0),
    ("에스테틱", "해외", "기존"): (0, 0, 9300000, 9300000, 0),
    ("에스테틱", "해외", "신규"): (4290000, 11999380, 0, 0, 18000000),
}


def _data_paths():
    data_dir = os.environ.get("DATA_DIR", "/app/user_data")
    return data_dir, os.path.join(data_dir, "performance_data.json")


def _read_data():
    _, data_file = _data_paths()
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_data(data):
    data_dir, data_file = _data_paths()
    os.makedirs(data_dir, exist_ok=True)
    tmp = data_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, data_file)


def _seed_data():
    current = _read_data()
    valid = (
        isinstance(current, dict)
        and current.get("meta", {}).get("initialized") is True
        and len(current.get("users", [])) == 10
    )

    if not valid:
        packed = os.environ.get("AUTO_SEED_GZ", "").strip()
        if not packed:
            raise RuntimeError("AUTO_SEED_GZ missing")
        try:
            seed = json.loads(gzip.decompress(base64.b64decode(packed)).decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"AUTO_SEED_GZ decode failed: {e}")
        if len(seed.get("users", [])) != 10 or len(seed.get("actuals", {})) < 84:
            raise RuntimeError("Invalid performance seed")
        seed.setdefault("meta", {})["initialized"] = True
        seed["meta"]["runtime_seeded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current = seed

    changed = False
    actuals = current.setdefault("actuals", {})

    # 2025 전년대비용 월별 실제 실적 보완. 기존값이 있어도 원본 기준으로 정합화한다.
    for (business, region), values in REFERENCE_2025.items():
        for month, value in enumerate(values, 1):
            key = f"2025-{month:02d}|{business}|{region}|기존"
            if actuals.get(key) != value:
                actuals[key] = value
                changed = True

    meta = current.setdefault("meta", {})
    if meta.get("data_audit_version") != DATA_AUDIT_VERSION:
        meta["data_audit_version"] = DATA_AUDIT_VERSION
        meta["display_unit"] = "KRW_million"
        meta["source_warning"] = "2025 메디컬 해외 원본 #REF! - 임의값 미입력"
        changed = True

    if changed or not valid:
        _write_data(current)


def on_starting(server):
    _seed_data()


def post_worker_init(worker):
    import app as base
    from flask import jsonify, redirect, url_for

    def scope_pairs(user):
        if not user:
            return []
        p = user.get("permission_type", "")
        if p == "admin":
            return base.ALL_PAIRS
        if p == "domestic_all":
            return [(b, "국내") for b in base.BUSINESSES]
        if p == "dental_domestic":
            return [("덴탈", "국내")]
        if p == "overseas_all":
            return [(b, "해외") for b in base.BUSINESSES]
        if p == "aesthetics_all":
            return [("에스테틱", "국내"), ("에스테틱", "해외")]
        return []

    def can_edit_entry(user, entry):
        if not user:
            return False
        if user.get("role") == "admin" or user.get("manage_all"):
            return True
        return (
            entry.get("user_id") == user.get("user_id")
            and (entry.get("business"), entry.get("region")) in scope_pairs(user)
        )

    def money_m(value, blank="-"):
        if value is None:
            return blank
        number = float(value) / 1_000_000
        rounded = round(number, 1)
        if abs(rounded - round(rounded)) < 1e-9:
            return f"{int(round(rounded)):,}"
        return f"{rounded:,.1f}"

    def setup_redirect():
        return redirect(url_for("login"))

    def health_runtime():
        data = base.read_store()
        return jsonify({
            "status": "ok",
            "initialized": bool(data.get("meta", {}).get("initialized")),
            "users": len(data.get("users", [])),
            "entries": len(data.get("entries", [])),
            "actuals": len(data.get("actuals", {})),
            "seed_version": data.get("meta", {}).get("seed_version", ""),
            "data_audit_version": data.get("meta", {}).get("data_audit_version", ""),
            "display_unit": "KRW_million",
            "runtime_patch": True,
        })

    base.scope_pairs = scope_pairs
    base.can_edit_entry = can_edit_entry
    base.app.jinja_env.filters["money_m"] = money_m
    base.app.view_functions["setup"] = setup_redirect
    base.app.view_functions["health"] = health_runtime

    # 1) 사용자/권한 검증
    data = base.read_store()
    users = {u.get("user_id"): u for u in data.get("users", [])}
    expected_users = {
        "mp001": ("김홍윤", "domestic_all", True),
        "mp002": ("김태현", "admin", True),
        "mp003": ("박재흥", "dental_domestic", False),
        "mp004": ("김경태", "overseas_all", False),
        "mp005": ("박정현", "overseas_all", False),
        "mp006": ("장윤선", "overseas_all", False),
        "mp007": ("최령", "overseas_all", False),
        "mp008": ("김예원", "overseas_all", False),
        "mp009": ("이인경", "aesthetics_all", False),
        "mp010": ("유동혁", "aesthetics_all", False),
    }
    assert set(users) == set(expected_users), "User list mismatch"
    for uid, (name, permission, manage_all) in expected_users.items():
        user = users[uid]
        assert user.get("display_name") == name
        assert user.get("permission_type") == permission
        assert bool(user.get("manage_all")) == manage_all

    # 2) 2025 원본 월별값 검증 (#REF인 메디컬 해외는 검증/입력 제외)
    actuals = data.get("actuals", {})
    for (business, region), values in REFERENCE_2025.items():
        for month, expected in enumerate(values, 1):
            key = f"2025-{month:02d}|{business}|{region}|기존"
            assert actuals.get(key) == expected, ("2025", key, actuals.get(key), expected)

    # 3) 2026 1~7월 실제 마감값 84개 전수 검증
    for (business, region, kind), values in REFERENCE_2026_ACTUAL.items():
        for month, expected in enumerate(values, 1):
            key = f"2026-{month:02d}|{business}|{region}|{kind}"
            actual = actuals.get(key)
            if expected == 0 and actual is None:
                actual = 0
            assert abs(float(actual) - float(expected)) < 0.01, ("2026 actual", key, actual, expected)

    # 4) 8월 1/2/3차와 9월 1차를 사업부/지역/기존신규 12개 행 전수 검증
    for (business, region, kind), expected in REFERENCE_FCST.items():
        first, second, third_confirmed, third_forecast, next_first = expected
        s1 = base.snapshot(data, 2026, 8, "1차", business, region, kind)
        s2 = base.snapshot(data, 2026, 8, "2차", business, region, kind)
        s3 = base.snapshot(data, 2026, 8, "3차", business, region, kind)
        n1 = base.snapshot(data, 2026, 9, "1차", business, region, kind)
        checks = [
            (s1["forecast"] if s1["has"] else 0, first, "8월1차"),
            (s2["forecast"] if s2["has"] else 0, second, "8월2차"),
            (s3["confirmed"] if s3["has"] else 0, third_confirmed, "8월3차확정"),
            (s3["forecast"] if s3["has"] else 0, third_forecast, "8월3차예상"),
            (n1["forecast"] if n1["has"] else 0, next_first, "9월1차"),
        ]
        for actual, exp, label in checks:
            assert abs(float(actual or 0) - float(exp)) < 0.01, (label, business, region, kind, actual, exp)

    # 5) 핵심 전체 합계 및 전년누계 검증
    report = base.report_data(2026, 8)
    grand = next(r for r in report["rows"] if r.get("is_grand"))
    totals = {
        "2026_1_7": (grand["ytd"], 9417886063),
        "2025_1_7_known": (grand["prev_ytd"], 8017934887),
        "8월1차": (grand["first"], 1643693152),
        "8월2차": (grand["second"], 1772844502.6230001),
        "8월3차확정": (grand["third_confirmed"], 1176386384),
        "8월3차예상": (grand["third_forecast"], 1483709990),
        "9월1차": (grand["next_first"], 1784250384),
    }
    for label, (actual, expected) in totals.items():
        assert abs(float(actual) - float(expected)) < 0.01, (label, actual, expected)

    # 6) 실제 렌더링 단위 검증
    client = base.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "mp001"
    response = client.get("/?year=2026&month=8")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "단위: 백만원" in html
    assert "1,483.7" in html

    print("Performance audit passed: 2025 reference, 2026 actuals/FCST, users/permissions, KRW-million display.")
