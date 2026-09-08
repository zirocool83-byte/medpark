import json

import runtime_patch as rt
from flask import request

app = rt.app
ui = rt.ui
base = rt.base


def _columns(year, month):
    prev_month = 12 if month == 1 else month - 1
    next_month = 1 if month == 12 else month + 1
    quarter = (month - 1) // 3 + 1
    cols = [
        ("ytd", "누계"),
        ("avg", "월평균"),
        ("prev_ytd", "전년누계"),
        ("growth", "누계증감률"),
    ]
    for m in range(1, month):
        cols.append((f"m{m}", f"{m}월 실적"))
    cols.extend([
        ("prev_first", f"{prev_month}월 1차"),
        ("prev_preclose", f"{prev_month}월 가마감"),
        ("prev_close", f"{prev_month}월 마감"),
        ("first", f"{month}월 1차"),
        ("second", f"{month}월 2차"),
        ("third_confirmed", f"{month}월 3차 확정"),
        ("third_forecast", f"{month}월 3차 예상"),
        ("close", f"{month}월 마감"),
        ("next_first", f"{next_month}월 1차"),
        ("qproj", f"{quarter}Q 전망"),
        ("october", "10월"),
        ("november", "11월"),
        ("december", "12월"),
        ("q4proj", "4Q 전망"),
        ("second_half", "하반기 전망"),
    ])
    return cols


def _preset_columns(month, preset):
    recent_month = month - 2
    common = ["ytd", "avg", "prev_ytd", "growth"]
    if recent_month >= 1:
        common.append(f"m{recent_month}")
    common.append("prev_close")
    if preset == "third":
        return common + ["first", "second", "third_confirmed", "third_forecast", "next_first", "qproj"]
    if preset == "close":
        return common + ["third_confirmed", "third_forecast", "close", "next_first", "qproj"]
    return common + ["first", "second", "next_first", "qproj"]


def _value(row, key):
    if key.startswith("m") and key[1:].isdigit():
        return ui.money_m(row.get("hist", {}).get(int(key[1:]), 0))
    if key == "growth":
        return ui.pct(row.get("growth"))
    return ui.money_m(row.get(key))


def _grouped_controls(columns, month):
    groups = [
        ("요약", ["ytd", "avg", "prev_ytd", "growth"]),
        ("월 실적", [f"m{m}" for m in range(1, month)]),
        ("전월 비교", ["prev_first", "prev_preclose", "prev_close"]),
        ("당월 회차", ["first", "second", "third_confirmed", "third_forecast", "close"]),
        ("차월 · 전망", ["next_first", "qproj", "october", "november", "december", "q4proj", "second_half"]),
    ]
    label_map = dict(columns)
    html = []
    for title, keys in groups:
        items = []
        for key in keys:
            if key not in label_map:
                continue
            items.append(
                f"<label class='col-choice'><input type='checkbox' data-col-toggle='{ui.esc(key)}'>"
                f"<span>{ui.esc(label_map[key])}</span></label>"
            )
        if items:
            html.append(f"<div class='choice-group'><strong>{ui.esc(title)}</strong><div>{''.join(items)}</div></div>")
    return "".join(html)


_original_render_report = ui.render_report
_original_topbar = ui.topbar


def topbar(user):
    html = _original_topbar(user)
    if "PPT 간편보기" not in html:
        html = html.replace("</nav>", "<a href='/ppt-view'>PPT 간편보기</a></nav>", 1)
    return html


ui.topbar = topbar


def render_report(report, user, capture=False):
    html = _original_render_report(report, user, capture)
    if not capture and "PPT 간편보기" not in html:
        year = report.get("year", 2026)
        month = report.get("month", 9)
        marker = "PPT 캡처 화면</a>"
        link = f"PPT 캡처 화면</a><a class='btn primary' href='/ppt-view?year={year}&month={month}'>PPT 간편보기</a>"
        html = html.replace(marker, link, 1)
    return html


ui.render_report = render_report


@base.login_required
def ppt_view():
    user = base.current_user()
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    capture = request.args.get("capture") == "1"

    report = ui.report_data(year, month)
    columns = _columns(year, month)
    default_second = _preset_columns(month, "second")
    default_third = _preset_columns(month, "third")
    default_close = _preset_columns(month, "close")

    ths = "".join(
        f"<th data-col='{ui.esc(key)}'>{ui.esc(label)}</th>" for key, label in columns
    )
    rows_html = []
    for row in report.get("rows", []):
        cls = "grand" if row.get("is_grand") else ("subtotal" if row.get("is_total") else "")
        if row.get("is_total"):
            prefix = f"<td colspan='3'>{ui.esc(row.get('label'))}</td>"
        else:
            prefix = (
                f"<td>{ui.esc(row.get('business'))}</td>"
                f"<td>{ui.esc(row.get('region'))}</td>"
                f"<td>{ui.esc(row.get('kind'))}</td>"
            )
        vals = "".join(
            f"<td data-col='{ui.esc(key)}'>{_value(row, key)}</td>" for key, _ in columns
        )
        rows_html.append(f"<tr class='{cls}'>{prefix}{vals}</tr>")

    controls = "" if capture else f"""
    <section class='ppt-controls no-capture'>
      <div class='preset-row'>
        <strong>PPT 표시항목</strong>
        <button type='button' class='btn preset' data-preset='second'>2차 회의</button>
        <button type='button' class='btn preset' data-preset='third'>3차 · 가마감</button>
        <button type='button' class='btn preset' data-preset='close'>최종마감</button>
        <button type='button' class='btn' id='select-all'>전체 선택</button>
        <button type='button' class='btn' id='clear-all'>전체 해제</button>
      </div>
      <p class='helper'>사업부 / 국내·해외 / 기존·신규는 고정입니다. 나머지 열은 자유롭게 추가·제외할 수 있고 이 브라우저에 선택값을 기억합니다.</p>
      <div class='choice-grid'>{_grouped_controls(columns, month)}</div>
      <div class='capture-actions'>
        <a class='btn' href='/?year={year}&month={month}'>전체현황</a>
        <button type='button' class='btn primary' id='open-capture'>PPT 캡처 화면 열기</button>
      </div>
    </section>
    """

    top = "" if capture else ui.topbar(user)
    body_class = "capture" if capture else ""
    storage_key = f"medpark_ppt_cols_{year}_{month:02d}"

    script = f"""
<script>
(function(){{
  const storageKey = {json.dumps(storage_key)};
  const available = {json.dumps([k for k, _ in columns], ensure_ascii=False)};
  const presets = {{
    second: {json.dumps(default_second, ensure_ascii=False)},
    third: {json.dumps(default_third, ensure_ascii=False)},
    close: {json.dumps(default_close, ensure_ascii=False)}
  }};
  const toggles = Array.from(document.querySelectorAll('[data-col-toggle]'));

  function sanitize(cols){{
    return cols.filter(c => available.includes(c));
  }}
  function stored(){{
    try {{
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? sanitize(parsed) : null;
    }} catch(e) {{ return null; }}
  }}
  function save(cols){{
    try {{ localStorage.setItem(storageKey, JSON.stringify(cols)); }} catch(e) {{}}
  }}
  function apply(cols, persist){{
    cols = sanitize(cols);
    document.querySelectorAll('[data-col]').forEach(el => {{
      el.style.display = cols.includes(el.dataset.col) ? '' : 'none';
    }});
    toggles.forEach(cb => cb.checked = cols.includes(cb.dataset.colToggle));
    if (persist) save(cols);
    const visibleCount = cols.length + 3;
    const table = document.querySelector('.ppt-table');
    if (table) {{
      table.classList.toggle('dense', visibleCount > 14);
      table.classList.toggle('very-dense', visibleCount > 18);
    }}
    const count = document.getElementById('visible-count');
    if (count) count.textContent = visibleCount + '개 열';
  }}
  let initial = stored();
  if (!initial || !initial.length) initial = presets.second;
  apply(initial, false);

  toggles.forEach(cb => cb.addEventListener('change', () => {{
    apply(toggles.filter(x => x.checked).map(x => x.dataset.colToggle), true);
  }}));
  document.querySelectorAll('[data-preset]').forEach(btn => btn.addEventListener('click', () => {{
    apply(presets[btn.dataset.preset] || presets.second, true);
  }}));
  const allBtn = document.getElementById('select-all');
  if (allBtn) allBtn.addEventListener('click', () => apply(available, true));
  const clearBtn = document.getElementById('clear-all');
  if (clearBtn) clearBtn.addEventListener('click', () => apply([], true));
  const captureBtn = document.getElementById('open-capture');
  if (captureBtn) captureBtn.addEventListener('click', () => {{
    window.open('/ppt-view?year={year}&month={month}&capture=1', '_blank');
  }});
}})();
</script>
"""

    css = ui.css() + """
.ppt-controls{background:#fff;border:1px solid #d7e1eb;border-radius:10px;padding:14px;margin-bottom:12px}.preset-row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.choice-grid{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:8px;margin-top:10px}.choice-group{border:1px solid #dce5ee;border-radius:8px;padding:10px}.choice-group>strong{display:block;font-size:12px;margin-bottom:7px;color:#33465a}.choice-group>div{display:flex;flex-direction:column;gap:5px}.col-choice{display:flex;align-items:center;gap:6px;margin:0;font-size:11px;font-weight:500}.col-choice input{width:auto;margin:0}.capture-actions{display:flex;gap:8px;margin-top:12px}.helper{font-size:11px;color:#65768a;margin:8px 0}.ppt-sheet{background:#fff;border:1px solid #c4d1de;padding:10px}.ppt-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:8px}.ppt-head h1{margin:0;font-size:24px}.ppt-head p{margin:4px 0 0;font-size:11px;color:#65768a}.ppt-count{font-size:11px;color:#65768a}.ppt-table{min-width:0;width:100%;font-size:9.5px;table-layout:auto}.ppt-table th,.ppt-table td{padding:5px 5px}.ppt-table.dense{font-size:8.5px}.ppt-table.dense th,.ppt-table.dense td{padding:4px 3px}.ppt-table.very-dense{font-size:7.5px}.ppt-table.very-dense th,.ppt-table.very-dense td{padding:3px 2px}.capture .topbar,.capture .ppt-controls{display:none}.capture .page{padding:4px;background:#fff}.capture .ppt-sheet{border:0;padding:4px}.capture .ppt-head h1{font-size:20px}@media(max-width:1100px){.choice-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:700px){.choice-grid{grid-template-columns:1fr}}
"""

    html = f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{year}년 {month}월 PPT 간편보기 · MEDPARK</title><style>{css}</style></head><body class='{body_class}'>{top}<main class='page'>{controls}<section class='ppt-sheet'><div class='ppt-head'><div><p class='eyebrow'>PPT COMPACT VIEW</p><h1>{year}년 {month}월 실적회의</h1><p>단위: 백만원 · 선택한 항목만 표시</p></div><span class='ppt-count' id='visible-count'></span></div><div class='table-wrap'><table class='report ppt-table'><thead><tr><th>사업부</th><th>구분</th><th>기존/신규</th>{ths}</tr></thead><tbody>{''.join(rows_html)}</tbody></table></div></section></main>{script}</body></html>"""
    return html


if "ppt_view" not in app.view_functions:
    app.add_url_rule("/ppt-view", endpoint="ppt_view", view_func=ppt_view, methods=["GET"])


_original_health = app.view_functions.get("health")


def ppt_health():
    payload = _original_health() if _original_health else {"status": "ok"}
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["runtime"] = "excel-layout-v5-ppt-select"
        payload["ppt_view"] = "/ppt-view"
    return payload


app.view_functions["health"] = ppt_health
