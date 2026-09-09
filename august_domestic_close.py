"""2026년 8월 국내 잠정마감을 actuals 에 넣는다.

배경
  8월 해외는 별도 스크립트로 actuals 에 직접 넣었고,
  8월 국내는 SalesOps 연동으로 '8월 마감' 열에만 들어온다.
  월실적·누계 열은 actuals 만 읽으므로 국내 8월이 통째로 빠져 있다.
  그래서 누계가 10,044.2백만원으로 나오고, 국내 751.1 을 더하면 10,795.3 이 된다.

원칙
  실적 원장이므로 8월 해외 때와 같은 안전장치를 그대로 쓴다.
  1) 먼저 통째로 백업한다
  2) entries 는 한 글자도 건드리지 않는다
  3) 값의 출처는 SalesOps 리포트 연동값이다. 화면 숫자를 옮겨 적지 않는다
  4) 한 번만 실행되고, 감사 파일이 남으면 다시 실행하지 않는다
  5) 저장 후 실제로 반영됐는지 다시 읽어 확인한다

되돌리기
  DATA_DIR/august_domestic_close_20260909.before.json 이 직전 상태 전체다.
"""

import copy
import json
import os
from pathlib import Path

import narrative_ytd_diag as prev
import narrative_page as npage
from flask import jsonify

app = prev.app
base = npage.base
DATA_DIR = Path(base.DATA_DIR)
AUDIT = DATA_DIR / "august_domestic_close_20260909.audit.json"
BACKUP = DATA_DIR / "august_domestic_close_20260909.before.json"

YEAR, MONTH = 2026, 8
REGION = "국내"


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


def _source_values():
    """SalesOps 연동값에서 8월 국내 마감을 (사업부, 구분) 별로 가져온다.

    9월 리포트의 prev_close 가 8월 마감이다.
    """
    report = npage._build(2026, 9)
    if report is None:
        return None, "report_build_failed"
    values = {}
    for row in report.get("rows", []) or []:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        if row.get("region") != REGION:
            continue
        business, kind = row.get("business"), row.get("kind")
        amount = row.get("prev_close")
        if not (business and kind) or amount is None:
            continue
        try:
            values[(business, REGION, kind)] = int(round(float(amount)))
        except Exception:
            return None, "bad_amount"
    if len(values) != 6:
        return None, "expected_6_rows_got_%d" % len(values)
    return values, None


def run_once():
    if AUDIT.exists():
        return _load_json(AUDIT)

    values, err = _source_values()
    if err:
        return {"status": "not_applied", "reason": err}

    total = sum(values.values())
    if total <= 0:
        return {"status": "not_applied", "reason": "zero_total"}

    before = base.read_store()
    if not BACKUP.exists():
        _save_json(BACKUP, before)

    after = copy.deepcopy(before)
    actuals = after.setdefault("actuals", {})
    changed = []
    for (business, region, kind), amount in values.items():
        key = base.actual_key(YEAR, MONTH, business, region, kind)
        changed.append({"business": business, "region": region, "kind": kind,
                        "old": actuals.get(key), "new": amount})
        actuals[key] = amount

    meta = after.setdefault("meta", {})
    meta["2026-08_domestic_close_status"] = "잠정마감"
    meta["2026-08_domestic_close_source"] = "SalesOps 연동값(9월 리포트 prev_close)"
    meta["2026-08_domestic_close_total"] = total

    if after.get("entries", []) != before.get("entries", []):
        return {"status": "not_applied", "reason": "entries_changed"}

    base.write_store(after)

    persisted = base.read_store()
    ok = all(
        persisted.get("actuals", {}).get(base.actual_key(YEAR, MONTH, b, r, k)) == v
        for (b, r, k), v in values.items()
    )
    ok = ok and persisted.get("entries", []) == before.get("entries", [])

    result = {
        "status": "applied" if ok else "needs_review",
        "period": "2026-08",
        "region": REGION,
        "total": total,
        "total_억": round(total / 1e8, 2),
        "changed": changed,
        "entries_untouched": persisted.get("entries", []) == before.get("entries", []),
    }
    _save_json(AUDIT, result)
    return result


try:
    RESULT = run_once()
except Exception as exc:
    RESULT = {"status": "not_applied", "reason": type(exc).__name__ + ": " + str(exc)[:200]}


@app.get("/august-domestic-close/status")
def august_domestic_close_status():
    user = npage._current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    if not (user.get("manage_all") or user.get("role") == "admin"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify(RESULT), (200 if RESULT.get("status") == "applied" else 409)
