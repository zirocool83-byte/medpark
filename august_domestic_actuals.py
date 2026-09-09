"""2026년 8월 국내 실적을 actuals 에 반영한다.

배경
  8월 해외는 actuals 에 직접 들어갔고, 국내 8월은 SalesOps 연동으로
  '8월 마감' 열에만 들어온다. 월실적·누계 열은 actuals 만 읽으므로
  8월 국내 751백만원이 누계에서 빠져 있다.
  그 결과 26년 누계가 10,044 로 나오고, 국내를 더하면 10,795 가 된다.

무엇을 하나
  9월 리포트의 국내 각 행에서 prev_close(8월 마감)를 읽어
  actuals 의 2026-08 국내 키에 넣는다. 화면에 보이는 반올림값이 아니라 원값이다.

안전장치
  - confirm=yes 없이는 미리보기만 한다
  - 실행 전 저장소 전체를 백업 파일로 남긴다
  - entries 는 손대지 않는다. 바뀌면 중단하고 되돌린다
  - 이미 값이 있는 키는 건드리지 않는다
  - 반영 후 다시 읽어 검증하고, 결과를 감사 파일로 남긴다
  - 한 번 성공하면 감사 파일이 있어 다시 실행되지 않는다
"""

import copy
import json
import os
import time
from pathlib import Path

import narrative_ytd_diag as prev
import narrative_page as npage
from flask import jsonify, request

app = prev.app
base = npage.base

DATA_DIR = Path(base.DATA_DIR)
AUDIT = DATA_DIR / "august_domestic_actuals_2026_08.audit.json"
BACKUP = DATA_DIR / "august_domestic_actuals_2026_08.before.json"

YEAR, MONTH = 2026, 8
REPORT_YEAR, REPORT_MONTH = 2026, 9
REGION = "국내"


def _n(v):
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except Exception:
        return None


def _save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _planned():
    """9월 리포트에서 8월 국내 마감값을 읽어 넣을 목록을 만든다."""
    report = npage._build(REPORT_YEAR, REPORT_MONTH)
    if report is None:
        return None, "report_build_failed"
    items = []
    for row in report.get("rows", []) or []:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        business, region, kind = row.get("business"), row.get("region"), row.get("kind")
        if region != REGION or not (business and kind):
            continue
        amount = _n(row.get("prev_close"))
        if amount is None:
            continue
        items.append({"business": business, "region": region, "kind": kind, "amount": amount})
    return items, None


@app.get("/august-domestic-actuals")
def august_domestic_actuals():
    user = npage._current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    if not (user.get("manage_all") or user.get("role") == "admin"):
        return jsonify({"error": "forbidden"}), 403

    if AUDIT.exists():
        try:
            return jsonify({"status": "already_applied", "audit": json.load(open(AUDIT, encoding="utf-8"))})
        except Exception:
            return jsonify({"status": "already_applied"})

    items, err = _planned()
    if err:
        return jsonify({"error": err}), 500

    store = base.read_store()
    actuals = store.get("actuals") or {}
    preview, total, skipped = [], 0, 0
    for it in items:
        key = base.actual_key(YEAR, MONTH, it["business"], it["region"], it["kind"])
        existing = actuals.get(key)
        if existing:
            skipped += 1
            preview.append({"키": key, "기존값": existing, "신규값": it["amount"], "처리": "건너뜀"})
            continue
        total += it["amount"]
        preview.append({"키": key, "기존값": existing, "신규값": it["amount"], "처리": "반영"})

    if request.args.get("confirm") != "yes":
        return jsonify({
            "status": "preview",
            "대상": "%d년 %d월 %s" % (YEAR, MONTH, REGION),
            "반영예정_건수": len(preview) - skipped,
            "건너뜀": skipped,
            "반영예정_합계": total,
            "반영예정_합계_백만": round(total / 1e6),
            "항목": preview,
            "안내": "주소 끝에 &confirm=yes 를 붙이면 반영합니다.",
        }), 409

    before = copy.deepcopy(store)
    if not BACKUP.exists():
        _save_json(BACKUP, before)

    after = copy.deepcopy(store)
    target = after.setdefault("actuals", {})
    changed = []
    for it in items:
        key = base.actual_key(YEAR, MONTH, it["business"], it["region"], it["kind"])
        if target.get(key):
            continue
        target[key] = it["amount"]
        changed.append({"키": key, "값": it["amount"]})

    if after.get("entries", []) != before.get("entries", []):
        return jsonify({"status": "aborted", "reason": "entries_changed"}), 500

    meta = after.setdefault("meta", {})
    meta["2026-08_domestic_actuals_source"] = "SalesOps 8월 잠정마감 (리포트 prev_close)"
    meta["2026-08_domestic_actuals_total"] = total
    meta["2026-08_domestic_actuals_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    base.write_store(after)

    persisted = base.read_store()
    ok = all(persisted.get("actuals", {}).get(c["키"]) == c["값"] for c in changed)
    ok = ok and persisted.get("entries", []) == before.get("entries", [])

    result = {
        "status": "applied" if ok else "needs_review",
        "대상": "%d-%02d %s" % (YEAR, MONTH, REGION),
        "반영_건수": len(changed),
        "반영_합계": total,
        "반영_합계_백만": round(total / 1e6),
        "변경": changed,
        "entries_무변경": persisted.get("entries", []) == before.get("entries", []),
        "백업파일": str(BACKUP),
        "시각": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if ok:
        _save_json(AUDIT, result)
    return jsonify(result), (200 if ok else 500)
