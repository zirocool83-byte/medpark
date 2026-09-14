"""SalesOps 월마감 금액을 actuals 에 자동으로 반영한다.

배경
  8월 국내 마감은 2026-09-09 에 august_domestic_close.py 로 한 번 복사해
  넣었고, 그 스크립트는 감사 파일로 잠겨 다시 돌지 않는다. 그래서 SalesOps
  에서 최종마감을 해도 현황판·누계(actuals 를 읽는 화면)는 9월 9일의 잠정
  숫자에 멈춰 있었다. 전월비교 열만 SalesOps 를 실시간으로 읽어 두 숫자가
  갈렸다.

방식
  일회성 스크립트를 반복하는 대신, SalesOps 연동값을 주기적으로 다시 읽어
  actuals 를 맞춘다. 값이 같으면 저장하지 않는다.

값의 출처
  SalesOps /api/performance 의 계약 필드를 그대로 쓴다.
  business_division, market, customer_type, final_close_amount, close.stage
  화면 숫자를 옮겨 적지 않는다.

원칙 (8월 국내 마감 때와 동일)
  1) 처음 바꾸기 전에 통째로 백업한다
  2) entries 는 한 글자도 건드리지 않는다
  3) 대상월 국내 actuals 키만 쓴다. 다른 월·해외는 건드리지 않는다
  4) 6개 축이 다 오고 합계가 0보다 클 때만 반영한다
  5) SalesOps 가 응답하지 않으면 아무것도 쓰지 않는다(마지막 값 유지)
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
MIN_INTERVAL_SECONDS = 900
REQUEST_TIMEOUT = 6

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


def _request_payload(year, month):
    """SalesOps /api/performance 원문을 그대로 받는다."""
    token = os.environ.get(live.TOKEN_ENV, "").strip()
    if not token:
        return None, "token_missing"
    url = live.SALESOPS_API + "?" + urllib.parse.urlencode({
        "year": int(year), "month": int(month),
    })
    headers = {
        "Accept": "application/json",
        "User-Agent": "MedPark-Performance-Report/actual-sync-1.0",
        "X-Requested-With": "XMLHttpRequest",
        "Authorization": "Bearer " + token,
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": live.SALESOPS_HOST,
        "X-Forwarded-Port": "443",
    }
    opener = urllib.request.build_opener(live._NoRedirect)
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with opener.open(req, timeout=REQUEST_TIMEOUT) as res:
            if getattr(res, "status", 200) != 200:
                return None, "http_%s" % getattr(res, "status", "?")
            raw = res.read().decode("utf-8", "replace")
        payload = json.loads(raw)
    except Exception as exc:
        return None, type(exc).__name__
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None, "unexpected_payload"
    return payload, None


def _domestic_close_values(payload):
    """계약 필드로 (사업부, 국내, 기존/신규) 별 최종마감액을 뽑는다."""
    values = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if row.get("market") != REGION:
            continue
        business = row.get("business_division")
        kind = row.get("customer_type")
        if business not in BUSINESSES or kind not in KINDS:
            continue
        try:
            values[(business, REGION, kind)] = int(round(float(
                row.get("final_close_amount") or 0
            )))
        except (TypeError, ValueError):
            return None, "bad_amount"
    if len(values) != len(BUSINESSES) * len(KINDS):
        return None, "expected_%d_rows_got_%d" % (
            len(BUSINESSES) * len(KINDS), len(values),
        )
    return values, None


def _stage_label(payload):
    close = payload.get("close") if isinstance(payload.get("close"), dict) else {}
    if close.get("final"):
        return "최종마감", True
    if close.get("provisional"):
        return "잠정마감", True
    if close.get("locked"):
        return "마감", True
    return str(close.get("stage") or "OPEN"), False


def sync(year=None, month=None, force=False):
    """SalesOps 마감값으로 대상월 국내 actuals 를 맞춘다."""
    if year is None or month is None:
        year, month = _previous_period()
    year, month = int(year), int(month)
    period = "%04d-%02d" % (year, month)

    payload, error = _request_payload(year, month)
    if error:
        return {"status": "not_applied", "period": period, "reason": error}

    stage_label, locked = _stage_label(payload)
    if not locked and not force:
        return {
            "status": "not_applied", "period": period,
            "reason": "not_closed", "stage": stage_label,
        }

    values, error = _domestic_close_values(payload)
    if error:
        return {"status": "not_applied", "period": period, "reason": error}

    total = sum(values.values())
    if total <= 0:
        return {"status": "not_applied", "period": period, "reason": "zero_total"}

    store = base.read_store()
    actuals = store.get("actuals") or {}
    changed = []
    for (business, region, kind), amount in sorted(values.items()):
        key = base.actual_key(year, month, business, region, kind)
        old = actuals.get(key)
        if old is None or int(old) != amount:
            changed.append({
                "business": business, "region": region, "kind": kind,
                "key": key, "old": old, "new": amount,
            })

    meta = store.get("meta") or {}
    status_key = "%s_domestic_close_status" % period
    stage_changed = meta.get(status_key) != stage_label
    if not changed and not stage_changed:
        return {
            "status": "unchanged", "period": period, "stage": stage_label,
            "total": total,
        }

    if not BACKUP.exists():
        _save_json(BACKUP, store)

    after = copy.deepcopy(store)
    after_actuals = after.setdefault("actuals", {})
    for row in changed:
        after_actuals[row["key"]] = row["new"]
    after_meta = after.setdefault("meta", {})
    after_meta[status_key] = stage_label
    after_meta["%s_domestic_close_source" % period] = (
        "SalesOps /api/performance final_close_amount 자동 동기화"
    )
    after_meta["%s_domestic_close_total" % period] = total
    after_meta["%s_domestic_close_synced_at" % period] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    base.write_store(after)

    verify = base.read_store().get("actuals") or {}
    mismatched = [
        row["key"] for row in changed
        if int(verify.get(row["key"], -1)) != row["new"]
    ]
    result = {
        "status": "applied" if not mismatched else "verify_failed",
        "period": period, "stage": stage_label, "total": total,
        "changed": changed, "mismatched": mismatched,
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
