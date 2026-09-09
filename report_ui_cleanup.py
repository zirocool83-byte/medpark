"""운영 화면 정리.

리포트를 만드는 원래 코드는 건드리지 않는다.
완성된 HTML 위에 규칙만 얹는다. 이 모듈을 빼면 원래 화면으로 돌아온다.

정리 항목
  1. 개발용 초록 띠(SalesOps 국내연동 OK)는 감춘다. 실패 띠는 그대로 둔다.
  2. 마감미입력 경고는 마감 시즌에만 보인다.
     - 전월 마감: 익월 1~15일
     - 당월 가마감: 23일~말일
  3. 중복된 제목 텍스트는 첫 개만 남긴다.
  4. 회의 문안 생성기 링크를 표 위로 옮겨 표를 가리지 않게 한다.
  5. /narrative 화면에 회차 삭제 단추를 붙인다.
"""

import json

import narrative_users_probe as prev
from flask import request

app = prev.app

REPORT_PATHS = ("/", "/performance-report")
MARK = "mp-ui-cleanup"
OLD_LINK_ID = "mp-narrative-link"

DEFAULT_SEASON = {
    "close": {"from_day": 1, "to_day": 15},
    "preclose": {"from_day": 23, "to_day": 31},
}


def _season():
    try:
        import narrative_config
        season = (getattr(narrative_config, "CONFIG", {}) or {}).get("close_season")
        if isinstance(season, dict) and season:
            return season
    except Exception:
        pass
    return DEFAULT_SEASON


def _report_script():
    season = json.dumps(_season(), ensure_ascii=False)
    return """
<style id='""" + MARK + """-style'>
  #""" + OLD_LINK_ID + """{position:static!important;display:inline-block;margin:10px 0 4px;
    box-shadow:none!important;font-size:14px!important;padding:8px 13px!important}
  .mp-linkbar{display:flex;justify-content:flex-end;gap:8px;padding:0 8px}
</style>
<script>
(function(){
  var SEASON = """ + season + """;
  function inSeason(name){
    var rule = SEASON[name];
    if (!rule) return true;
    var d = new Date().getDate();
    return d >= (rule.from_day || 1) && d <= (rule.to_day || 31);
  }
  function monthOf(){
    try {
      var u = new URL(location.href);
      var m = parseInt(u.searchParams.get('month') || '', 10);
      if (m >= 1 && m <= 12) return m;
    } catch(e){}
    return new Date().getMonth() + 1;
  }
  function leaves(re){
    var out = [];
    var all = document.body.querySelectorAll('*');
    for (var i=0;i<all.length;i++){
      var el = all[i];
      if (el.children.length) continue;
      var t = (el.textContent || '').trim();
      if (t && re.test(t)) out.push(el);
    }
    return out;
  }

  // 1) 개발용 성공 띠 감추기
  leaves(/SalesOps\\s*국내연동\\s*OK/).forEach(function(el){
    var box = el.closest('div') || el;
    box.style.display = 'none';
  });

  // 2) 마감미입력 경고: 시즌에만
  (function(){
    var now = new Date();
    var thisMonth = now.getMonth() + 1;
    var shown = monthOf();
    var prevMonth = thisMonth === 1 ? 12 : thisMonth - 1;
    var closeSeason = inSeason('close') && shown === prevMonth;
    var preSeason = inSeason('preclose') && shown === thisMonth;
    if (closeSeason || preSeason) return;
    leaves(/마감\\s*미입력/).forEach(function(el){
      var box = el.closest('span,div,li,td') || el;
      box.style.display = 'none';
    });
  })();

  // 3) 중복 제목 정리
  (function(){
    var seen = {};
    leaves(/^PERFORMANCE REPORT WRITER$/i).forEach(function(el){
      var t = (el.textContent || '').trim().toUpperCase();
      if (seen[t]) { el.style.display = 'none'; return; }
      seen[t] = true;
    });
  })();

  // 4) 문안 생성기 링크를 표 위로
  (function(){
    var link = document.getElementById('""" + OLD_LINK_ID + """');
    if (!link) return;
    var bar = document.createElement('div');
    bar.className = 'mp-linkbar';
    link.parentNode.removeChild(link);
    bar.appendChild(link);
    document.body.insertBefore(bar, document.body.firstChild);
  })();
})();
</script>
"""


NARRATIVE_SCRIPT = """
<script id='""" + MARK + """-narr'>
(function(){
  function ready(fn){
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  ready(function(){
    var box = document.getElementById('histBox');
    if (!box) return;
    var bar = document.createElement('div');
    bar.style.cssText = 'margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '이 회차 기록 삭제';
    btn.style.cssText = 'background:#FAE8E6;color:#8C2018;border:1px solid #E0A9A2;border-radius:4px;' +
      'padding:10px 15px;font-size:15px;font-family:inherit;cursor:pointer;min-height:42px;font-weight:700';
    var msg = document.createElement('span');
    msg.style.cssText = 'font-size:15px;color:#5C6B7A';
    function key(){
      var y = document.getElementById('year').value;
      var m = ('0' + document.getElementById('month').value).slice(-2);
      return y + '-' + m + ':' + document.getElementById('meeting').value;
    }
    btn.addEventListener('click', function(){
      var k = key();
      if (!window.confirm(k + ' 회차 기록을 지웁니다. 되돌릴 수 없습니다. 진행할까요?')) return;
      msg.textContent = '삭제 중…';
      fetch('/narrative-round-delete?confirm=yes&key=' + encodeURIComponent(k), {credentials:'same-origin'})
        .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
        .then(function(res){
          if (!res.ok || !res.j.deleted) throw new Error((res.j && (res.j.reason || res.j.error)) || '실패');
          msg.textContent = '삭제됨. 새로고침합니다.';
          setTimeout(function(){ location.reload(); }, 700);
        })
        .catch(function(e){ msg.textContent = '삭제 실패: ' + e.message; });
    });
    bar.appendChild(btn); bar.appendChild(msg);
    box.parentNode.insertBefore(bar, box.nextSibling);
  });
})();
</script>
"""


def _inject(resp, snippet):
    try:
        if resp.direct_passthrough or resp.status_code != 200:
            return resp
        ctype = str(resp.headers.get("Content-Type") or "")
        if "text/html" not in ctype.lower():
            return resp
        body = resp.get_data(as_text=True)
        if MARK in body or "</body>" not in body:
            return resp
        resp.set_data(body.replace("</body>", snippet + "</body>", 1))
    except Exception:
        pass
    return resp


@app.after_request
def mp_ui_cleanup(resp):
    try:
        if request.args.get("capture") == "1":
            return resp
        if request.path in REPORT_PATHS:
            return _inject(resp, _report_script())
        if request.path == "/narrative":
            return _inject(resp, NARRATIVE_SCRIPT)
    except Exception:
        pass
    return resp
