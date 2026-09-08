import sys

import l4_net_probe2 as prev
from flask import jsonify, request

app = prev.app
live = sys.modules.get("root_live_fetch")
base = live.base

SALESOPS_API = "https://medparkallo-medpark-salesops.mycafe24.ai/api/performance"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return int(round(float(v)))
    except Exception:
        return None


def _parse_doc(doc):
    index = {}
    if not isinstance(doc, dict):
        return index
    for r in (doc.get("rows") or []):
        if not isinstance(r, dict):
            continue
        b = r.get("business_division")
        mk = r.get("market")
        ct = r.get("customer_type")
        if not (b and mk and ct):
            continue
        index[(b, mk, ct)] = {
            "business": b,
            "region": mk,
            "kind": ct,
            "first": _num(r.get("first_fcst_amount")),
            "second": _num(r.get("second_fcst_amount")),
            "close": _num(r.get("final_close_amount")),
        }
    return index


def _fetch_from_snapshot(year, month):
    cached, saved = live._load_snapshot(year, month)
    if cached:
        return cached, {"ok": True, "reason": "browser_bridge", "source": "snapshot", "saved_at": saved, "rows": len(cached)}
    return {}, {"ok": False, "reason": "브라우저 동기화 대기중", "source": "snapshot"}


live._fetch = _fetch_from_snapshot


@app.post("/salesops-sync")
def salesops_sync():
    user = base.current_user()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    saved = []
    errors = []
    for item in (payload.get("months") or []):
        try:
            year = int(item.get("year"))
            month = int(item.get("month"))
            index = _parse_doc(item.get("payload"))
            if not index:
                errors.append({"year": year, "month": month, "error": "no_rows"})
                continue
            live._save_snapshot(year, month, index)
            saved.append({"year": year, "month": month, "rows": len(index)})
        except Exception as exc:
            errors.append({"error": type(exc).__name__ + ": " + str(exc)[:120]})
    return jsonify({"ok": bool(saved), "saved": saved, "errors": errors})


@app.get("/salesops-sync-status")
def salesops_sync_status():
    out = {}
    for y, m in ((2026, 9), (2026, 8)):
        idx, meta = _fetch_from_snapshot(y, m)
        dom = [v for k, v in idx.items() if k[1] == "국내"]
        out["%d-%02d" % (y, m)] = {
            "rows": len(idx),
            "domestic_rows": len(dom),
            "second_total": sum(r["second"] for r in dom if r.get("second") is not None) if dom else None,
            "close_total": sum(r["close"] for r in dom if r.get("close") is not None) if dom else None,
            "saved_at": meta.get("saved_at"),
        }
    return jsonify(out)


SCRIPT = """
<script>
(function(){
  var API = "%s";
  var box = document.createElement('div');
  box.style.cssText = "position:fixed;left:8px;right:8px;bottom:8px;z-index:99999;padding:11px 13px;border-radius:9px;font-size:16px;font-weight:700;font-family:-apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.18);border:1px solid #ccc;background:#fff8e1";
  box.textContent = "SalesOps 국내 데이터 불러오는 중...";
  function say(t, bg){ box.textContent = t; box.style.background = bg; }
  function start(){
    document.body.appendChild(box);
    var u = new URL(location.href);
    var y = parseInt(u.searchParams.get('year') || '2026', 10);
    var m = parseInt(u.searchParams.get('month') || '9', 10);
    var py = (m === 1) ? y - 1 : y;
    var pm = (m === 1) ? 12 : m - 1;
    var pairs = [[y, m], [py, pm]];
    var months = [];
    function step(i){
      if (i >= pairs.length) { return post(); }
      var yy = pairs[i][0], mm = pairs[i][1];
      fetch(API + '?year=' + yy + '&month=' + mm, { credentials: 'include', headers: { 'Accept': 'application/json' } })
        .then(function(r){
          if (!r.ok) { throw new Error('SalesOps 응답 HTTP ' + r.status); }
          return r.json();
        })
        .then(function(j){ months.push({ year: yy, month: mm, payload: j }); step(i + 1); })
        .catch(function(e){ say('국내 연동 실패 (SalesOps 호출): ' + e.message, '#fdecea'); });
    }
    function post(){
      fetch('/salesops-sync', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ months: months })
      })
      .then(function(r){ return r.json(); })
      .then(function(j){
        if (!j.ok) { throw new Error(JSON.stringify(j)); }
        if (!sessionStorage.getItem('mp_bridge_reloaded')) {
          sessionStorage.setItem('mp_bridge_reloaded', '1');
          location.reload();
          return;
        }
        var n = (j.saved || []).map(function(s){ return s.year + '-' + s.month + ' ' + s.rows + '행'; }).join(' / ');
        say('국내 연동 완료 · ' + n, '#eaf7ee');
        setTimeout(function(){ box.style.display = 'none'; }, 4000);
      })
      .catch(function(e){ say('국내 연동 실패 (저장): ' + e.message, '#fdecea'); });
    }
    step(0);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); } else { start(); }
})();
</script>
""" % SALESOPS_API


@app.after_request
def inject_bridge(resp):
    try:
        if request.path != "/":
            return resp
        if request.args.get("capture") == "1":
            return resp
        ctype = str(resp.headers.get("Content-Type") or "")
        if "text/html" not in ctype.lower():
            return resp
        body = resp.get_data(as_text=True)
        if "</body>" in body and "mp_bridge_reloaded" not in body:
            resp.set_data(body.replace("</body>", SCRIPT + "</body>", 1))
    except Exception:
        pass
    return resp
