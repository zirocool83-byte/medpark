"""SalesOps 월마감 금액을 actuals 에 자동으로 반영한다.

배경
  8월 국내 마감은 2026-09-09 에 august_domestic_close.py 로 한 번 복사해
  넣었고, 그 스크립트는 감사 파일로 잠겨 다시 돌지 않는다. 그래서 SalesOps
  에서 최종마감을 해도 현황판·누계(actuals 를 읽는 화면)는 9월 9일의 잠정
  숫자에 멈춰 있었다. 전월비교 열만 연동값을 읽어 두 숫자가 갈렸다.

값의 출처
  이 서버는 SalesOps 로 직접 나가지 못한다(URLError). browser_bridge 가
  사용자 브라우저로 SalesOps /api/performance 를 읽어 스냅샷으로 저장하고
  있으므로, 그 스냅샷의 final_close_amount(=close) 를 그대로 쓴다.
  직접 호출이 되는 환경이면 그 값을 먼저 쓴다. 화면 숫자를 옮겨 적지 않는다.

원칙 (8월 국내 마감 때와 동일)
  1) 처음 바꾸기 전에 통째로 백업한다
  2) entries 는 한 글자도 건드리지 않는다
  3) 대상월 국내 actuals 키만 쓴다. 다른 월·해외는 건드리지 않는다
  4) 6개 축이 다 오고 합계가 0보다 클 때만 반영한다
  5) 연동값이 없으면 아무것도 쓰지 않는다(마지막 값 유지)
  6) 저장 후 다시 읽어 확인하고, 무엇을 왜 바꿨는지 감사 기록에 남긴다

되돌리기
  DATA_DIR/salesops_actual_sync.before.json 이 이 모듈이 처음 쓰기 직전의
  저장소 전체다. 이후 변경 내역은 salesops_actual_sync.audit.json 에 쌓인다.
"""

import copy
import datetime
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import load_2025_actuals as prev
import narrative_page as npage
import root_live_fetch as live
from flask import jsonify, request

app = prev.app
base = npage.base

DATA_DIR = Path(base.DATA_DIR)
AUDIT = DATA_DIR / "salesops_actual_sync.audit.json"
BACKUP = DATA_DIR / "salesops_actual_sync.before.json"

REGION = "국내"
BUSINESSES = ("덴탈", "메디컬", "에스테틱")
KINDS = ("기존", "신규")
AXIS_COUNT = len(BUSINESSES) * len(KINDS)
MIN_INTERVAL_SECONDS = 900
REQUEST_TIMEOUT = 5

_lock = threading.Lock()
_state = {"running": False, "last_attempt_at": 0.0, "last_result": None}


def _save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _previous_period(today=None):
    today = today or datetime.date.today()
    first = today.replace(day=1)
    last_month = first - datetime.timedelta(days=1)
    return last_month.year, last_month.month


def _to_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _values_from_live(year, month):
    """직접 호출이 되는 환경에서만 쓴다. 마감 단계까지 함께 얻는다."""
    token = os.environ.get(live.TOKEN_ENV, "").strip()
    if not token:
        return None, None, "token_missing"
    url = live.SALESOPS_API + "?" + urllib.parse.urlencode({
        "year": int(year), "month": int(month),
    })
    headers = {
        "Accept": "application/json",
        "User-Agent": "MedPark-Performance-Report/actual-sync-1.1",
        "Authorization": "Bearer " + token,
        "X-Read-Only-Token": token,
    }
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as res:
            if getattr(res, "status", 200) != 200:
                return None, None, "http_%s" % getattr(res, "status", "?")
            payload = json.loads(res.read().decode("utf-8", "replace"))
    except Exception as exc:
        return None, None, type(exc).__name__
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None, None, "unexpected_payload"
    values = {}
    for row in payload["rows"]:
        if not isinstance(row, dict) or row.get("market") != REGION:
            continue
        business, kind = row.get("business_division"), row.get("customer_type")
        if business not in BUSINESSES or kind not in KINDS:
            continue
        amount = _to_int(row.get("final_close_amount") or 0)
        if amount is None:
            return None, None, "bad_amount"
        values[(business, REGION, kind)] = amount
    if len(values) != AXIS_COUNT:
        return None, None, "live_expected_%d_got_%d" % (AXIS_COUNT, len(values))
    close = payload.get("close") if isinstance(payload.get("close"), dict) else {}
    if close.get("final"):
        stage = "최종마감"
    elif close.get("provisional"):
        stage = "잠정마감"
    elif close.get("locked"):
        stage = "마감"
    else:
        stage = None
    return values, stage, None


def _values_from_snapshot(year, month):
    """browser_bridge 가 사용자 브라우저로 받아 저장한 연동 스냅샷을 쓴다."""
    try:
        index, saved_at = live._load_snapshot(year, month)
    except Exception as exc:
        return None, None, "snapshot_error:" + type(exc).__name__
    if not index:
        return None, None, "snapshot_empty"
    values = {}
    for (business, region, kind), row in index.items():
        if region != REGION or business not in BUSINESSES or kind not in KINDS:
            continue
        if not isinstance(row, dict):
            continue
        amount = _to_int(row.get("close"))
        if amount is None:
            continue
        values[(business, REGION, kind)] = amount
    if len(values) != AXIS_COUNT:
        return None, None, "snapshot_expected_%d_got_%d" % (AXIS_COUNT, len(values))
    return values, saved_at, None


def sync(year=None, month=None, force=False):
    """SalesOps 연동값으로 대상월 국내 actuals 를 맞춘다."""
    if year is None or month is None:
        year, month = _previous_period()
    year, month = int(year), int(month)
    period = "%04d-%02d" % (year, month)

    values, stage, live_error = _values_from_live(year, month)
    source = "live"
    saved_at = None
    if live_error:
        values, saved_at, snapshot_error = _values_from_snapshot(year, month)
        source = "snapshot"
        stage = None
        if snapshot_error:
            return {
                "status": "not_applied", "period": period,
                "reason": snapshot_error, "live_reason": live_error,
            }

    total = sum(values.values())
    if total <= 0:
        return {"status": "not_applied", "period": period, "reason": "zero_total"}

    store = base.read_store()
    actuals = store.get("actuals") or {}
    changed = []
    for (business, region, kind), amount in sorted(values.items()):
        key = base.actual_key(year, month, business, region, kind)
        old = actuals.get(key)
        if old is None or _to_int(old) != amount:
            changed.append({
                "business": business, "region": region, "kind": kind,
                "key": key, "old": old, "new": amount,
            })

    meta = store.get("meta") or {}
    status_key = "%s_domestic_close_status" % period
    stage_changed = bool(stage) and meta.get(status_key) != stage
    if not changed and not stage_changed and not force:
        return {
            "status": "unchanged", "period": period, "total": total,
            "source": source, "snapshot_saved_at": saved_at,
        }

    if not BACKUP.exists():
        _save_json(BACKUP, store)

    after = copy.deepcopy(store)
    after_actuals = after.setdefault("actuals", {})
    for row in changed:
        after_actuals[row["key"]] = row["new"]
    after_meta = after.setdefault("meta", {})
    if stage:
        after_meta[status_key] = stage
    after_meta["%s_domestic_close_source" % period] = (
        "SalesOps 연동값(%s) 자동 동기화" % source
    )
    after_meta["%s_domestic_close_total" % period] = total
    after_meta["%s_domestic_close_synced_at" % period] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    base.write_store(after)

    verify = base.read_store().get("actuals") or {}
    mismatched = [
        row["key"] for row in changed
        if _to_int(verify.get(row["key"])) != row["new"]
    ]
    result = {
        "status": "applied" if not mismatched else "verify_failed",
        "period": period, "total": total, "source": source,
        "snapshot_saved_at": saved_at, "stage": stage,
        "live_reason": live_error, "changed": changed, "mismatched": mismatched,
        "entries_untouched": (
            len(after.get("entries") or []) == len(store.get("entries") or [])
        ),
        "applied_at": after_meta["%s_domestic_close_synced_at" % period],
    }
    history = _load_json(AUDIT, [])
    if not isinstance(history, list):
        history = [history]
    history.append(result)
    _save_json(AUDIT, history[-50:])
    return result


def _sync_in_background():
    def run():
        try:
            result = sync()
        except Exception as exc:
            result = {
                "status": "error",
                "reason": type(exc).__name__ + ": " + str(exc)[:200],
            }
        _state["last_result"] = result
        _state["running"] = False
    _state["running"] = True
    threading.Thread(target=run, name="salesops-actual-sync", daemon=True).start()


@app.before_request
def salesops_actual_sync_before_request():
    path = request.path or "/"
    if path.startswith("/static") or path.startswith("/entry-status"):
        return None
    if path.startswith("/salesops-sync") or path.startswith("/salesops-actual-sync"):
        return None
    now = time.time()
    with _lock:
        if _state["running"]:
            return None
        if now - _state["last_attempt_at"] < MIN_INTERVAL_SECONDS:
            return None
        _state["last_attempt_at"] = now
        _sync_in_background()
    return None


@app.get("/salesops-actual-sync")
def salesops_actual_sync_endpoint():
    period = (request.args.get("period") or "").strip()
    force = (request.args.get("force") or "").strip().lower() in {"1", "true", "yes"}
    year = month = None
    if period:
        parts = period.split("-")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return jsonify({"status": "bad_request", "reason": "period_format"}), 400
        year, month = int(parts[0]), int(parts[1])
    result = sync(year, month, force=force)
    return jsonify({
        "result": result,
        "last_background_result": _state["last_result"],
        "audit_tail": _load_json(AUDIT, [])[-5:],
    })
