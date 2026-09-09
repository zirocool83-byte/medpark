"""회의 자료 PPT 내려받기.

표는 서버가 리포트 데이터로 직접 그린다. 캡처도 붙여넣기도 없다.
문안은 화면이 만든다. 숫자 조립 규칙을 서버와 화면에 두 번 구현하지 않기 위해서다.

증감 표기는 ▲ 빨강 / ▼ 파랑 / - 회색으로 통일한다.
화면이 아직 +, △ 로 찍는 자리는 여기서 바꿔 준다.

주의: HTTP 헤더는 latin-1 만 담는다. 파일 이름에 한글을 그대로 넣으면 응답이 터진다.
"""

import re
from datetime import datetime
from urllib.parse import quote

import narrative_page as prev
import narrative_ppt as builder
import narrative_table as tbl
import narrative_table_cfg as tcfg
from flask import Response, jsonify, request

app = prev.app
MARK = "mp-pptx-ui"

COLOR = {"blue": builder.BLUE, "red": builder.RED, "black": builder.BLACK}

FIELDS = ("ytd", "prev_ytd", "prev_preclose", "prev_close",
          "first", "second", "third_confirmed", "third_forecast",
          "next_first", "second_half")


def _to_int(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


def _table_index(year, month, meeting):
    """리포트를 (사업부, 지역, 구분) 단위로 모은다."""
    index = {}
    report = prev._build(year, month)
    for row in (report or {}).get("rows", []) or []:
        if not isinstance(row, dict) or row.get("is_total"):
            continue
        business, region, kind = row.get("business"), row.get("region"), row.get("kind")
        if not (business and region and kind):
            continue
        rec = {f: _to_int(row.get(f)) for f in FIELDS}
        # 잠정마감 기록이 상세 단위로는 없으므로 마감값을 그대로 쓴다.
        rec["prev_provisional"] = rec.get("prev_close")
        index[(business, region, kind)] = rec

    if meeting == "pre":
        ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
        nxt = prev._build(ny, nm)
        for row in (nxt or {}).get("rows", []) or []:
            if not isinstance(row, dict) or row.get("is_total"):
                continue
            key = (row.get("business"), row.get("region"), row.get("kind"))
            if key in index:
                index[key]["preclose_cur"] = _to_int(row.get("prev_preclose"))
    return index


def _ctx(year, month):
    pm = 12 if month == 1 else month - 1
    nm = 1 if month == 12 else month + 1
    return {"cy": year, "py": year - 1, "cm": month, "pm": pm, "nm": nm}


def _frames(year, month, meeting):
    index = _table_index(year, month, meeting)
    if not index:
        return {}, 0
    ctx = _ctx(year, month)
    full_cols = tcfg.columns(meeting, ctx, plan=False)
    plan_cols = tcfg.columns(meeting, ctx, plan=True)
    rows_full = tbl.make_rows(index, full_cols)
    rows_plan = tbl.make_rows(index, plan_cols)
    lay = tcfg.LAYOUT["full"]
    lay_plan = tcfg.LAYOUT["plan"]
    frames = {
        "close": tbl.build_table(rows_full, full_cols, lay["x"], lay["y"], lay["w"], lay["h"], 91),
        "fcst": tbl.build_table(rows_full, full_cols, lay["x"], lay["y"], lay["w"], lay["h"], 92),
        "plan": tbl.build_table(rows_plan, plan_cols, lay_plan["x"], lay_plan["y"],
                                lay_plan["w"], lay_plan["h"], 93),
    }
    return frames, len(index)


@app.get("/narrative-pptx-health")
def narrative_pptx_health():
    if not prev._current_user():
        return jsonify({"error": "unauthorized"}), 401
    try:
        frames, n = _frames(2026, 9, "r1")
        table_ok = bool(frames)
    except Exception as exc:
        return jsonify({"table_error": type(exc).__name__ + ": " + str(exc)[:200]}), 500
    return jsonify({
        "template_exists": builder.TEMPLATE.exists(),
        "template_bytes": builder.TEMPLATE.stat().st_size if builder.TEMPLATE.exists() else 0,
        "table_ok": table_ok,
        "table_cells": n,
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
            try:
                indent = int(item.get("i") or 0)
            except Exception:
                indent = 0
            paras.append(builder.para(text[:400],
                                      color=COLOR.get(item.get("c"), builder.BLACK),
                                      bold=bool(item.get("b")), indent=indent))
        blocks[slot] = paras

    key = str(payload.get("key") or "")
    matched = re.match(r"^(\d{4})-(\d{2}):([a-z0-9_]{1,16})$", key)
    frames = {}
    if matched:
        try:
            frames, _ = _frames(int(matched.group(1)), int(matched.group(2)), matched.group(3))
        except Exception:
            frames = {}

    if not any(blocks.values()) and not frames:
        return jsonify({"error": "empty"}), 400
    try:
        data, report = builder.build(blocks, frames)
    except FileNotFoundError:
        return jsonify({"error": "template_missing"}), 500
    except Exception as exc:
        return jsonify({"error": type(exc).__name__ + ": " + str(exc)[:200]}), 500

    safe = re.sub(r'[^0-9A-Za-z_-]', '', key.replace(":", "_"))[:40] or "round"
    stamp = datetime.now().strftime("%m%d")
    ascii_name = "meeting_%s_%s.pptx" % (safe, stamp)
    korean_name = "실적회의_%s_%s.pptx" % (safe, stamp)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": 'attachment; filename="%s"; filename*=UTF-8\'\'%s'
                                   % (ascii_name, quote(korean_name, safe="")),
            "X-MedPark-PPT-Tables": ",".join(report.get("tables") or []),
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
  // 증감 표기 통일: +12 → ▲12,  △12 → ▼12
  function arrow(s){
    if (!s) return s;
    return String(s).replace(/△/g, '▼').replace(/\\+/g, '▲');
  }
  function txt(id){ var e = $(id); return e ? arrow((e.textContent || '').trim()) : ''; }
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
      if (th && (th.className || '').indexOf('cur') >= 0) return j;
    }
    return colCount(pfx) || 2;
  }
  function cellVal(id){
    var e = $(id);
    if (!e) return '';
    if (e.tagName === 'INPUT') return (e.value || '').trim();
    return (e.textContent || '').trim();
  }
  function firstTok(s){ return (s || '').split(' ')[0]; }

  function section(pfx, heading, subHeading){
    var out = [], cur = curIdx(pfx), n = colCount(pfx);
    var curLabel = txt('th-' + pfx + cur);
    var baseLabel = cur >= 2 ? txt('th-' + pfx + (cur-1)) : '';
    out.push(P(heading, 'black', true));
    if (subHeading) out.push(P(subHeading, 'black', false));
    var total = cellVal(pfx + '_tot_' + cur);
    var delta = txt(pfx + '_tot_d');
    var line = 'ㄱ. ' + curLabel + ' : ' + (total || '미입력');
    if (baseLabel && delta && delta !== '—') line += '      ' + baseLabel + ' 대비 ' + delta;
    out.push(P(line, 'blue', true, 1));
    for (var s=0;s<SCOPES.length;s++){
      var sc = SCOPES[s];
      var sub = cellVal(pfx + '_' + sc[0] + '_sub_' + cur);
      if (!sub || sub === '—') continue;
      var sd = txt(pfx + '_' + sc[0] + '_sub_d');
      var parts = [];
      for (var b=0;b<BIZ.length;b++){
        var v = cellVal(pfx + '_' + sc[0] + '_' + b + '_' + cur);
        if (!v) continue;
        var d = txt(pfx + '_' + sc[0] + '_' + b + '_d');
        parts.push(BIZ[b] + ' ' + v + (d && d !== '—' ? '(' + firstTok(d) + ')' : ''));
      }
      out.push(P('- ' + sc[1] + ' : ' + sub + (sd && sd !== '—' ? ' (' + firstTok(sd) + ')' : ''), 'black', false, 2));
      if (parts.length) out.push(P('  ' + parts.join('  /  '), 'black', false, 3));
    }
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
    var out = [], items = [];
    var rows = document.querySelectorAll('#' + target + ' .lrow');
    for (var i=0;i<rows.length;i++){
      var r = rows[i];
      var who = r.querySelector('.who');
      if (!who || !(who.value || '').trim()) continue;
      var amt = r.querySelector('.amt');
      var scope = r.querySelector('.scope');
      var biz = r.querySelector('.biz');
      var why = r.querySelector('.why');
      items.push('- ' + (scope ? scope.value : '') +
                 (biz && biz.value !== '전체' ? ' ' + biz.value : '') +
                 ' ' + who.value.trim() +
                 (amt && amt.value ? ' ' + amt.value : '') +
                 ' : ' + (why ? why.value : ''));
    }
    if (!items.length) return out;
    out.push(P(label, 'black', true, 1));
    for (var k=0;k<items.length;k++) out.push(P(items[k], 'black', false, 2));
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
    var meetLabel = (meetSel && meetSel.options[meetSel.selectedIndex])
      ? meetSel.options[meetSel.selectedIndex].text : '';
    var close = section('c', '1) 매출', '(1) ' + closeH + ' 요약  [' + meetLabel + ']');
    close = close.concat(factorLines('c_factors', 'ㄴ. 변동 요인'));
    var note = $('note_close');
    if (note && (note.value || '').trim()) close.push(P('* ' + note.value.trim(), 'red', true, 1));

    var fcst = section('f', '1) 매출', '(2) ' + fcstH + ' 요약');
    fcst = fcst.concat(factorLines('f_factors', 'ㄴ. 변동 요인'));

    var left = [P('1) 매출', 'black', true), P('(3) 매출 분석', 'black', false)];
    var headLine = txt('out_head');
    if (headLine && headLine.indexOf('숫자를') < 0){
      var segs = headLine.split('|');
      for (var i=0;i<segs.length;i++){
        if (segs[i].trim()) left.push(P('- ' + segs[i].trim(), 'blue', true, 1));
      }
    }
    return {close: close, fcst: fcst, plan_left: left, plan_right: listLines()};
  }

  // 화면의 증감 칸도 ▲/▼ 로 보이게 한다.
  function fixDeltas(root){
    var cells = (root || document).querySelectorAll('td.delta');
    for (var i=0;i<cells.length;i++){
      var t = cells[i].textContent || '';
      if (t.indexOf('+') < 0 && t.indexOf('△') < 0) continue;
      cells[i].textContent = arrow(t);
    }
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
    function fail(m){ msg.style.color = '#8C2018'; msg.textContent = m; btn.disabled = false; }
    function info(m){ msg.style.color = '#5C6B7A'; msg.textContent = m; }

    btn.addEventListener('click', function(){
      btn.disabled = true;
      info('문단 만드는 중…');
      var body;
      try {
        body = buildBlocks();
        body.key = $('year').value + '-' + ('0' + $('month').value).slice(-2) + ':' + $('meeting').value;
      } catch (e) {
        fail('문단 생성 실패: ' + (e && e.message ? e.message : e));
        return;
      }
      info('표와 파일 만드는 중…');
      var timer = setTimeout(function(){ fail('응답이 없습니다. 다시 눌러주십시오.'); }, 30000);
      fetch('/narrative-pptx', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      }).then(function(r){
        if (!r.ok) return r.text().then(function(t){ throw new Error('HTTP ' + r.status + ' ' + t.slice(0,160)); });
        return r.blob();
      }).then(function(blob){
        clearTimeout(timer);
        if (!blob || blob.size < 1000) throw new Error('빈 파일을 받았습니다');
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = body.key.replace(':', '_') + '_회의자료.pptx';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function(){ URL.revokeObjectURL(url); }, 3000);
        info('내려받았습니다 (' + Math.round(blob.size/1024) + 'KB). 표까지 들어 있습니다.');
        btn.disabled = false;
      }).catch(function(e){
        clearTimeout(timer);
        fail('실패: ' + (e && e.message ? e.message : e));
      });
    });
    bar.appendChild(btn); bar.appendChild(msg);

    fixDeltas();
    try {
      var obs = new MutationObserver(function(){ fixDeltas(); });
      ['c_body','f_body'].forEach(function(id){
        var el = $(id);
        if (el) obs.observe(el, {childList:true, subtree:true, characterData:true});
      });
    } catch (e) {}
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
