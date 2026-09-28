"""해외 연동 — medpark-global 의 회차별 금액을 현황판 해외 행에 채운다.

왜 필요한가
  현황판 해외 행은 수동 입력으로 남아 있었다. 국내는 SalesOps 연동으로 자동
  반영되는데 해외만 사람이 옮겨 적어야 했다. 해외 원천은 medpark-global
  (오더 파이프라인)이고, 그쪽에 /api/overseas-performance 를 만들어 두었다.

어떻게 가져오는가
  이 서버는 외부로 직접 나가지 못한다(URLError). 국내와 같은 방식으로
  사용자 브라우저가 medpark-global 을 읽어 /overseas-sync 로 넘기고, 서버는
  그 값을 스냅샷 파일에 저장한다.

회차 매핑 (medpark-global 이 이미 회차별 기준을 적용해 내려준다)
  1차 예상 first_fcst_amount      2차 예상 second_fcst_amount
  3차 예상 third_estimated_amount 가마감   flash_close_amount
  잠정마감 provisional_close_amount 확정마감 final_close_amount
  기존/신규는 그쪽 판정(사람 지정 우선, 없으면 출고 이력)을 그대로 쓴다.

당겨오는 달
  이번 달 · 전월 · 다음 달 셋이다. 이번 달을 조회한 화면에 '다음 달 1차'
  칸이 있는데 브릿지가 이번 달과 전월만 읽어 늘 비어 있었다. 9월 회의에서
  10월 출발선을 같이 보려면 다음 달까지 읽어야 한다. 국내 브릿지도 같다.

원칙
  국내 값은 건드리지 않는다. 해외 행만 덮어쓴다(다음 달 1차 칸은 예외).
  값이 없으면 아무것도 쓰지 않는다(마지막 값 유지).
  차수가 아직 없는 칸은 0 이 아니라 빈칸으로 둔다(국내·해외 공통).
"""

import datetime
import json
import os
from pathlib import Path

import third_round_live as prev
import browser_bridge as bridge
import root_boot_cache as cache
import root_live_fetch as live
from flask import jsonify, request

app = prev.app
base = live.base
ui = live.ui

GLOBAL_API = os.environ.get(
    "GLOBAL_API",
    "https://medparkallo-medpark-global.mycafe24.ai/api/overseas-performance",
)
SNAPSHOT_DIR = Path(base.DATA_DIR)
FIELD_MAP = {
    "first": "first_fcst_amount",
    "second": "second_fcst_amount",
    "third_forecast": "third_estimated_amount",
    "flash_close": "flash_close_amount",
    "provisional_close": "provisional_close_amount",
    "final_close": "final_close_amount",
}


def _path(year, month):
    return SNAPSHOT_DIR / ("overseas_snapshot_%04d_%02d.json" % (year, month))


def _num(value):
    try:
        if value is None or value == "":
            return None
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _save(year, month, index):
    path = _path(year, month)
    payload = {
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": {"|".join(key): value for key, value in index.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def _load(year, month):
    try:
        with open(_path(year, month), encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}, None
    index = {}
    for key, value in (payload.get("rows") or {}).items():
        parts = key.split("|")
        if len(parts) == 3:
            index[(parts[0], parts[1], parts[2])] = value
    return index, payload.get("saved_at")


def _parse(payload):
    """medpark-global 계약 필드를 그대로 읽는다."""
    index = {}
    if not isinstance(payload, dict):
        return index
    for row in (payload.get("rows") or []):
        if not isinstance(row, dict) or row.get("market") != "해외":
            continue
        key = (row.get("business_division"), "해외", row.get("customer_type"))
        if not all(key):
            continue
        index[key] = {
            field: _num(row.get(source)) for field, source in FIELD_MAP.items()
        }
    return _blank_missing(index)


# 차수가 아직 없으면 0 이 아니라 빈칸이어야 한다.
# medpark-global 은 없는 차수를 빈값으로 내리지만 SalesOps 는 0 으로 내린다.
# 여섯 행이 모두 0 이면 그 차수는 아직 만들지 않은 것이다. 0 을 그대로
# 앉히면 현황판에 "가마감 0원"으로 찍혀 회의에서 오해를 낳는다.
_ROUND_FIELDS = ("first", "second", "third_confirmed", "third_forecast",
                 "close", "prev_first", "prev_preclose", "prev_close")


def _all_zero(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    return bool(nums) and not any(nums)


def _blank_missing(index):
    if not index:
        return index
    fields = set()
    for row in index.values():
        fields.update(row)
    for field in fields:
        if not _all_zero([row.get(field) for row in index.values()]):
            continue
        for row in index.values():
            if isinstance(row.get(field), (int, float)):
                row[field] = None
    return index


@app.post("/overseas-sync")
def overseas_sync():
    try:
        user = base.current_user()
    except Exception:
        user = None
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    saved, errors = [], []
    for item in (payload.get("months") or []):
        try:
            year = int(item.get("year"))
            month = int(item.get("month"))
            index = _parse(item.get("payload"))
            if not index:
                errors.append({"year": year, "month": month, "error": "no_rows"})
                continue
            _save(year, month, index)
            saved.append({"year": year, "month": month, "rows": len(index)})
        except Exception as exc:
            errors.append({"error": type(exc).__name__ + ": " + str(exc)[:120]})
    try:
        cache._CACHE.clear()
        cache._META.clear()
    except Exception:
        pass
    return jsonify({"ok": bool(saved), "saved": saved, "errors": errors})


@app.get("/overseas-health")
def overseas_health():
    out = {}
    try:
        y0 = int(request.args.get("year") or 0)
        m0 = int(request.args.get("month") or 0)
    except Exception:
        y0 = m0 = 0
    if y0 and 1 <= m0 <= 12:
        py, pm = ((y0 - 1, 12) if m0 == 1 else (y0, m0 - 1))
        ny, nx = ((y0 + 1, 1) if m0 == 12 else (y0, m0 + 1))
        wanted = ((y0, m0), (py, pm), (ny, nx))
    else:
        wanted = ((2026, 9), (2026, 8), (2026, 10))
    for year, month in wanted:
        index, saved_at = _load(year, month)
        out["%d-%02d" % (year, month)] = {
            "rows": len(index), "saved_at": saved_at,
            "totals": {
                field: sum(
                    int(row.get(field) or 0) for row in index.values()
                ) for field in FIELD_MAP
            },
        }
    return jsonify({"global_api": GLOBAL_API, "snapshots": out})


# ---------- 리포트 조립: 해외 행을 채운다 ----------

def _fill_overseas(module, report, year, month):
    rows = report.get("rows") if isinstance(report, dict) else None
    if not rows:
        return report
    current, _ = _load(year, month)
    py, pm = ((year - 1, 12) if month == 1 else (year, month - 1))
    previous, _ = _load(py, pm)
    # 다음 달 1차. 회의는 이번 달 숫자와 다음 달 출발선을 같이 본다.
    # 그래서 이번 달을 조회한 화면에 '다음 달 1차' 칸이 있다.
    ny, nm = ((year + 1, 1) if month == 12 else (year, month + 1))
    nxt_over, _ = _load(ny, nm)
    try:
        nxt_dom = live._fetch(ny, nm)[0] or {}
    except Exception:
        nxt_dom = {}
    details = [row for row in rows if not row.get("is_total")]
    for row in details:
        key = (row.get("business"), row.get("region"), row.get("kind"))
        src = nxt_over if row.get("region") == "해외" else nxt_dom
        nxt = (src.get(key) or {}).get("first")
        if nxt is not None:
            row["next_first"] = nxt
    for row in details:
        if row.get("region") != "해외":
            continue
        key = (row.get("business"), "해외", row.get("kind"))
        cur = current.get(key) or {}
        old = previous.get(key) or {}
        for field in ("first", "second"):
            if cur.get(field) is not None:
                row[field] = cur[field]
        # 당월 3차 예상은 third_confirmed 칸, 가마감은 third_forecast 칸에 앉는다
        # (third_round_live 가 국내에 쓰는 자리 규칙과 같다).
        if cur.get("third_forecast") is not None:
            row["third_confirmed"] = cur["third_forecast"]
        if cur.get("flash_close") is not None:
            row["third_forecast"] = cur["flash_close"]
        close = cur.get("final_close") or cur.get("provisional_close")
        if close is not None:
            row["close"] = close
            row["close_has"] = True
        # 전월 비교: 가마감 → 잠정마감 → 확정마감. 국내와 같은 자리를 쓴다.
        if old.get("flash_close") is not None:
            row["prev_first"] = old["flash_close"]
        if old.get("provisional_close") is not None:
            row["prev_preclose"] = old["provisional_close"]
        if old.get("final_close") is not None:
            row["prev_close"] = old["final_close"]
    # 국내도 같은 규칙을 적용한다. SalesOps 가 없는 차수를 0 으로 내려서
    # third_round_live 가 그 0 을 그대로 앉혔다. 여섯 행이 모두 0 인 칸은 비운다.
    dom = [row for row in details if row.get("region") == "국내"]
    for field in _ROUND_FIELDS:
        if _all_zero([row.get(field) for row in dom]):
            for row in dom:
                if isinstance(row.get(field), (int, float)):
                    row[field] = None
                if field == "close":
                    row["close_has"] = False

    summer = getattr(module, "_sum", None) or live._sum
    fields = (
        "prev_first", "prev_preclose", "prev_close", "first", "second",
        "third_confirmed", "third_forecast", "close", "next_first", "carryover",
        "qproj", "october", "november", "december", "q4proj", "second_half",
    )
    for total in [row for row in rows if row.get("is_total")]:
        scope = details if total.get("is_grand") else [
            row for row in details if row.get("business") == total.get("business")
        ]
        for field in fields:
            total[field] = summer(scope, field) or None
    return report


def _wrap(module):
    original = module._build_report

    def _build_report(year, month):
        return _fill_overseas(module, original(year, month), year, month)

    module._build_report = _build_report


for _module in (live, cache):
    _wrap(_module)


# ---------- 브라우저가 medpark-global 을 읽어 넘긴다 ----------

_SCRIPT = """
<script>
(function(){
  var API = "__GLOBAL_API__";
  function flag(k){ try { return sessionStorage.getItem(k); } catch(e){ return '1'; } }
  function setFlag(k){ try { sessionStorage.setItem(k, '1'); } catch(e){} }
  var u = new URL(location.href);
  var y = parseInt(u.searchParams.get('year') || '2026', 10);
  var m = parseInt(u.searchParams.get('month') || '9', 10);
  var py = (m === 1) ? y - 1 : y;
  var pm = (m === 1) ? 12 : m - 1;
  var ny = (m === 12) ? y + 1 : y;
  var nx = (m === 12) ? 1 : m + 1;
  var pairs = [[y, m], [py, pm], [ny, nx]];
  var months = [];
  function step(i){
    if (i >= pairs.length) { return post(); }
    var yy = pairs[i][0], mm = pairs[i][1];
    var ym = yy + '-' + (mm < 10 ? '0' + mm : mm);
    fetch(API + '?month=' + ym, { credentials: 'omit', headers: { 'Accept': 'application/json' } })
      .then(function(r){ if (!r.ok) { throw new Error('HTTP:' + r.status); } return r.json(); })
      .then(function(j){ months.push({ year: yy, month: mm, payload: j }); step(i + 1); })
      .catch(function(){ step(i + 1); });
  }
  function post(){
    if (!months.length) { return; }
    fetch('/overseas-sync', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ months: months })
    })
    .then(function(r){ return r.json(); })
    .then(function(j){
      if (j.ok && !flag('mp_overseas_reloaded')) { setFlag('mp_overseas_reloaded'); location.reload(); }
    })
    .catch(function(){});
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function(){ step(0); });
  } else { step(0); }
})();
</script>
"""

_original_render_report = ui.render_report


def render_report(report, user, capture=False):
    html = _original_render_report(report, user, capture)
    if capture:
        return html
    script = _SCRIPT.replace("__GLOBAL_API__", GLOBAL_API)
    return html.replace("</body>", script + "</body>", 1)


ui.render_report = render_report


# 국내 브릿지도 다음 달까지 당겨오게 한다. 이번 달을 조회한 화면에
# '다음 달 1차' 칸이 있는데 브릿지가 이번 달과 전월만 읽어서 늘 비어 있었다.
# browser_bridge 를 고치지 않고 주입 스크립트만 바꾼다.
_BRIDGE_OLD = "var pairs = [[y, m], [py, pm]];"
_BRIDGE_NEW = ("var ny = (m === 12) ? y + 1 : y;"
               " var nx = (m === 12) ? 1 : m + 1;"
               " var pairs = [[y, m], [py, pm], [ny, nx]];")
try:
    if _BRIDGE_OLD in bridge.SCRIPT:
        bridge.SCRIPT = bridge.SCRIPT.replace(_BRIDGE_OLD, _BRIDGE_NEW, 1)
except Exception:
    pass

try:
    cache._CACHE.clear()
    cache._META.clear()
except Exception:
    pass
