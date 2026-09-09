"""2025년 실적을 actuals 에 넣는다.

배경
  SalesOps 와 ERP 를 최근에 바꿔서 저장소에 2025년 데이터가 하나도 없다.
  (actuals 2025 키 0개, 2026 키 96개)
  그래서 리포트의 '2025년 누계'와 '누계 증감률'이 계속 0으로 나온다.

값의 출처
  narrative_history.Y2025 — 김태현 님의 '2026년 월별 실적 및 누적현황' 엑셀,
  시트 '2. 전년대비(총괄)'의 2025년 실적 블록 월별 값.
  원본 총계 14,874,549,034원과 대조해 검증한다.

기존/신규
  2025년 자료에는 그 구분이 없다. 신규 구분은 2026년 계획관리용이므로
  2025년은 전액 기존에 넣고 신규는 0으로 둔다.

원칙 (8월 국내 마감 때와 동일)
  1) 먼저 통째로 백업
  2) entries 는 건드리지 않음
  3) 2025 키만 추가. 이미 값이 있는 키는 덮지 않음
  4) 합계가 원본과 맞을 때만 반영
  5) 저장 후 다시 읽어 확인
  6) 감사 파일이 있으면 재실행하지 않음

되돌리기
  DATA_DIR/load_2025_actuals_20260909.before.json 이 직전 상태 전체다.
"""

import copy
import json
import os
from pathlib import Path

import prior_year_probe as prev
import narrative_page as npage
from flask import jsonify

try:
    import narrative_history as hist
except Exception:
    hist = None

app = prev.app
base = npage.base
DATA_DIR = Path(base.DATA_DIR)
AUDIT = DATA_DIR / "load_2025_actuals_20260909.audit.json"
BACKUP = DATA_DIR / "load_2025_actuals_20260909.before.json"

YEAR = 2025
EXPECTED_TOTAL = 14874549034


def _save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_once():
    if AUDIT.exists():
        return _load_json(AUDIT)
    if hist is None:
        return {"status": "not_applied", "reason": "history_module_missing"}

    # 넣을 값 조립: 기존 행에 전액, 신규 행은 0
    planned = {}
    total = 0
    for combo, months in hist.Y2025.items():
        try:
            business, region = combo.split("|")
        except ValueError:
            return {"status": "not_applied", "reason": "bad_combo:" + str(combo)}
        for month in range(1, 13):
            amount = int(months.get(month) or 0)
            total += amount
            planned[(YEAR, month, business, region, "기존")] = amount
            planned[(YEAR, month, business, region, "신규")] = 0

    if total != EXPECTED_TOTAL:
        return {"status": "not_applied", "reason": "total_mismatch",
                "got": total, "expected": EXPECTED_TOTAL}

    before = base.read_store()
    if not BACKUP.exists():
        _save_json(BACKUP, before)

    after = copy.deepcopy(before)
    actuals = after.setdefault("actuals", {})

    added, skipped = 0, 0
    for (year, month, business, region, kind), amount in planned.items():
        key = base.actual_key(year, month, business, region, kind)
        if key in actuals:
            skipped += 1
            continue
        actuals[key] = amount
        added += 1

    meta = after.setdefault("meta", {})
    meta["2025_actuals_source"] = "2026년 월별 실적 및 누적현황 엑셀 · 시트 2. 전년대비(총괄)"
    meta["2025_actuals_total"] = total
    meta["2025_actuals_note"] = "기존/신규 구분 없음. 전액 기존에 반영"

    if after.get("entries", []) != before.get("entries", []):
        return {"status": "not_applied", "reason": "entries_changed"}

    base.write_store(after)

    persisted = base.read_store()
    pa = persisted.get("actuals", {})
    check = 0
    for (year, month, business, region, kind), amount in planned.items():
        key = base.actual_key(year, month, business, region, kind)
        if pa.get(key) is not None:
            check += int(pa.get(key) or 0)
    ok = (check == total) and (persisted.get("entries", []) == before.get("entries", []))

    result = {
        "status": "applied" if ok else "needs_review",
        "year": YEAR,
        "keys_added": added,
        "keys_skipped": skipped,
        "total": total,
        "total_억": round(total / 1e8, 2),
        "persisted_total_억": round(check / 1e8, 2),
        "entries_untouched": persisted.get("entries", []) == before.get("entries", []),
    }
    _save_json(AUDIT, result)
    return result


try:
    RESULT = run_once()
except Exception as exc:
    RESULT = {"status": "not_applied", "reason": type(exc).__name__ + ": " + str(exc)[:200]}


@app.get("/load-2025-actuals/status")
def load_2025_actuals_status():
    user = npage._current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    if not (user.get("manage_all") or user.get("role") == "admin"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify(RESULT), (200 if RESULT.get("status") == "applied" else 409)
