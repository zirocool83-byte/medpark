"""회의 자료 PPT 내려받기.

/narrative 화면에 단추를 붙이고, 화면이 만든 개조식 문단을 받아
회사 장표 3장으로 만들어 내려준다.

문단은 화면에서 만든다. 서버가 숫자 조립 규칙을 두 번 구현하지 않기 위해서다.
"""

import re
from datetime import datetime

import narrative_page as prev
import narrative_ppt as builder
from flask import Response, jsonify, request

app = prev.app
MARK = "mp-pptx-ui"

COLOR = {"blue": builder.BLUE, "red": builder.RED, "black": builder.BLACK}


@app.get("/narrative-pptx-health")
def narrative_pptx_health():
    if not prev._current_user():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "template_path": str(builder.TEMPLATE),
        "template_exists": builder.TEMPLATE.exists(),
        "template_bytes": builder.TEMPLATE.stat().st_size if builder.TEMPLATE.exists() else 0,
    })


@app.post("/narrative-pptx")
def narrative_pptx():
    user = prev._current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    blocks = {}
    for slot in ("close", "fcst", "plan_left", "plan_right"):
        paras = []
        for item in (payload.get(slot) or [])[:60]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("t") or "")
            if not text.strip():
                paras.append(builder.blank())
                continue
            paras.append(builder.para(
                text[:400],
                color=COLOR.get(item.get("c"), builder.BLACK),
                bold=bool(item.get("b")),
                indent=int(item.get("i") or 0),
            ))
        blocks[slot] = paras
    if not any(blocks.values()):
        return jsonify({"error": "empty"}), 400
    try:
        data, report = builder.build(blocks)
    except FileNotFoundError:
        return jsonify({"error": "template_missing"}), 500
    except Exception as exc:
        return jsonify({"error": type(exc).__name__ + ": " + str(exc)[:200]}), 500

    key = re.sub(r'[^0-9A-Za-z:_-]', '', str(payload.get("key") or "round"))[:40].replace(":", "_")
    name = "실적회의_%s_%s.pptx" % (key, datetime.now().strftime("%m%d"))
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + name.replace(" ", "_"),
            "X-MedPark-PPT-Replaced": ",".join(report.get("replaced") or []),
            "X-MedPark-PPT-Missing": ",".join(report.get("missing") or []),
        },
    )


SCRIPT = """
<script id='""" + MARK + """'>
(function(){
  var $ = function(id){ return document.getElementById(id); };
  function ready(fn){
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  function txt(id){ var e = $(id); return e ? (e.textContent || '').trim() : ''; }
  function P(t, c, b, i){ return {t: t, c: c || 'black', b: !!b, i: i || 0}; }

  var BIZ = ['덴탈','메디컬','에스테틱'];
  var SCOPES = [['dom','국내'],['ovs','해외']];

  function colCount(pfx){
    var n = 0;
    for (var j=1;j<=3;j++){
      var th = $('th-' + pfx + j);
      if (th && th.style.display !== 'none' && (th.textContent||'').trim()) n++;
    }
    return n;
  }
  function curIdx(pfx){
    for (var j=1;j<=3;j++){
      var th = $('th-' + pfx + j);
      if (th && th.className.indexOf('cur') >= 0) return j;
    }
    return colCount(pfx);
  }
  function cellVal(id){
    var e = $(id);
    if (!e) return '';
    if (e.tagName === 'INPUT') return (e.value || '').trim();
    return (e.textContent || '').trim();
  }

  // 섹션 하나를 개조식 문단으로
  function section(pfx, heading, subHeading){
    var out = [], cur = curIdx(pfx), n = colCount(pfx);
    var curLabel = txt('th-' + pfx + cur);
    var baseLabel = cur >= 2 ? txt('th-' + pfx + (cur-1)) : '';
    out.push(P(heading, 'black', true));
    if (subHeading) out.push(P(subHeading, 'black', false));
    var total = cellVal(pfx + '_tot_' + cur);
    var delta = txt(pfx + '_tot_d');
    var line = 'ㄱ. ' + curLabel + ' : ' + total;
    if (baseLabel && delta && delta !== '—') line += '      ' + baseLabel + ' 대비 ' + delta;
    out.push(P(line, 'blue', true, 1));
    SCOPES.forEach(function(sc){
      var sub = cellVal(pfx + '_' + sc[0] + '_sub_' + cur);
      if (!sub || sub === '—') return;
      var sd = txt(pfx + '_' + sc[0] + '_sub_d');
      var parts = [];
      for (var b=0;b<BIZ.length;b++){
        var v = cellVal(pfx + '_' + sc[0] + '_' + b + '_' + cur);
        if (!v) continue;
        var d = txt(pfx + '_' + sc[0] + '_' + b + '_d');
        parts.push(BIZ[b] + ' ' + v + (d && d !== '—' ? '(' + d.split(' ')[0] + ')' : ''));
      }
      var s = '- ' + sc[1] + ' : ' + sub + (sd && sd !== '—' ? ' (' + sd.split(' ')[0] + ')' : '');
      out.push(P(s, 'black', false, 2));
      if (parts.length) out.push(P('  ' + parts.join('  /  '), 'black', false, 3));
    });
    // 차수 흐름
    if (n >= 3){
      var flow = [];
      for (var j=1;j<=n;j++){
        var v = cellVal(pfx + '_tot_' + j);
        if (v && v !== '—') flow.push(txt('th-' + pfx + j) + ' ' + v);
      }
      if (flow.length >= 3) out.push(P('- 차수 흐름 : ' + flow.join(' ▶ '), 'blue', false, 2));
    }
    return out;
  }

  function factorLines(target, label){
    var out = [];
    var rows = document.querySelectorAll('#' + target + ' .lrow');
    var items = [];
    for (var i=0;i<rows.length;i++){
      var r = rows[i];
      var who = r.querySelector('.who'), amt = r.querySelector('.amt');
      if (!who || !(who.value || '').trim()) continue;
      var scope = r.querySelector('.scope'), biz = r.querySelector('.biz'), why = r.querySelector('.why');
      items.push('- ' + scope.value + (biz && biz.value !== '전체' ? ' ' + biz.value : '') +
                 ' ' + who.value.trim() + (amt && amt.value ? ' ' + amt.value : '') +
                 ' : ' + (why ? why.value : ''));
    }
    if (!items.length) return out;
    out.push(P(label, 'black', true, 1));
    items.forEach(function(s){ out.push(P(s, 'black', false, 2)); });
    return out;
  }

  function listLines(){
    var out = [];
    var secs = document.querySelectorAll('#listSections section');
    for (var i=0;i<secs.length;i++){
      var h2 = secs[i].querySelector('h2');
      var title = h2 ? (h2.textContent || '').replace('담당·기한 필수','').trim() : '항목';
      out.push(P('ㄴ. ' + title, 'blue', true, 1));
      var rows = secs[i].querySelectorAll('.lrow');
      var any = false;
      for (var k=0;k<rows.length;k++){
        var vals = [];
        var fields = rows[k].querySelectorAll('input, select');
        for (var f=0;f<fields.length;f++){
          var v = (fields[f].value || '').trim();
          if (v && v !== '전체' && v !== '담당 선택') vals.push(v);
        }
        if (vals.length >= 2){ out.push(P('- ' + vals.join(' / '), 'black', false, 2)); any = true; }
      }
      if (!any) out.push(P('- 입력된 항목이 없습니다', 'red', true, 2));
    }
    return out;
  }

  function buildBlocks(){
    var closeH = txt('h-close'), fcstH = txt('h-fcst');
    var meetSel = $('meeting');
    var meetLabel = meetSel ? meetSel.options[meetSel.selectedIndex].text : '';
    var close = section('c', '1) 매출', '(1) ' + closeH + ' 요약  [' + meetLabel + ']');
    close = close.concat(factorLines('c_factors', 'ㄴ. 변동 요인'));
    var note = $('note_close');
    if (note && (note.value || '').trim()){
      close.push(P('* ' + note.value.trim(), 'red', true, 1));
    }
    var fcst = section('f', '1) 매출', '(2) ' + fcstH + ' 요약');
    fcst = fcst.concat(factorLines('f_factors', 'ㄴ. 변동 요인'));

    var left = [P('1) 매출', 'black', true), P('(3) 매출 분석', 'black', false)];
    var headLine = txt('out_head');
    if (headLine && headLine.indexOf('숫자를') < 0){
      headLine.split('|').forEach(function(s){
        if (s.trim()) left.push(P('- ' + s.trim(), 'blue', true, 1));
      });
    }
    var right = listLines();
    return {close: close, fcst: fcst, plan_left: left, plan_right: right};
  }

  ready(function(){
    var bar = document.querySelector('.bar');
    if (!bar) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'PPT 3장 내려받기';
    btn.className = 'primary';
    var msg = document.createElement('span');
    msg.style.cssText = 'font-size:15px;color:#5C6B7A';
    btn.addEventListener('click', function(){
      msg.textContent = '만드는 중…';
      var body = buildBlocks();
      body.key = ($('year').value + '-' + ('0'+$('month').value).slice(-2) + ':' + $('meeting').value);
      fetch('/narrative-pptx', {
        method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body)
      }).then(function(r){
        if (!r.ok) return r.json().then(function(j){ throw new Error(j.error || r.status); });
        return r.blob();
      }).then(function(blob){
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = body.key.replace(':','_') + '_회의자료.pptx';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function(){ URL.revokeObjectURL(url); }, 3000);
        msg.textContent = '내려받았습니다. 표 자리에 엑셀 캡처를 붙이면 완성입니다.';
      }).catch(function(e){ msg.textContent = '실패: ' + e.message; });
    });
    bar.appendChild(btn); bar.appendChild(msg);
  });
})();
</script>
"""


@app.after_request
def mp_pptx_ui(resp):
    try:
        if request.path != "/narrative":
            return resp
        if resp.direct_passthrough or resp.status_code != 200:
            return resp
        ctype = str(resp.headers.get("Content-Type") or "")
        if "text/html" not in ctype.lower():
            return resp
        body = resp.get_data(as_text=True)
        if MARK in body or "</body>" not in body:
            return resp
        resp.set_data(body.replace("</body>", SCRIPT + "</body>", 1))
    except Exception:
        pass
    return resp
