import json

import ppt_patch as ppt
from flask import request

app = ppt.app
base = ppt.base

_original_ppt_view = app.view_functions.get("ppt_view")
_original_health = app.view_functions.get("health")


def _inject_highlight(html_text, year, month, capture=False):
    preset_key = f"medpark_ppt_preset_{year}_{month:02d}"
    auto_key = f"medpark_ppt_auto_highlight_{year}_{month:02d}"

    if not capture:
        marker = "<button type='button' class='btn' id='clear-all'>전체 해제</button>\n      </div>"
        toggle = (
            "<button type='button' class='btn' id='clear-all'>전체 해제</button>"
            "<label class='auto-highlight-toggle' title='회의 회차 기준으로 핵심 숫자 열을 자동 강조합니다'>"
            "<input type='checkbox' id='auto-highlight' checked>"
            "<span>핵심 열 자동강조</span>"
            "</label>\n      </div>"
        )
        html_text = html_text.replace(marker, toggle, 1)

    highlight_css = """
<style>
.auto-highlight-toggle{display:inline-flex;align-items:center;gap:6px;margin:0;padding:7px 9px;border:1px solid #c9d6e3;border-radius:7px;background:#f8fafc;color:#173e6b;font-size:11px;font-weight:800;cursor:pointer}
.auto-highlight-toggle input{width:auto;margin:0}
.ppt-table th.hl-primary,.ppt-table td.hl-primary{background:#d9e9f7!important;color:#10375f!important;font-weight:900!important;box-shadow:inset 2px 0 #164a80,inset -2px 0 #164a80}
.ppt-table th.hl-compare,.ppt-table td.hl-compare{background:#edf1f5!important;color:#2d4157!important;font-weight:800!important}
.ppt-table th.hl-support,.ppt-table td.hl-support{background:#eef8f4!important;color:#285f4b!important;font-weight:700!important}
.ppt-table th.hl-primary{background:#164a80!important;color:#fff!important}
.ppt-table th.hl-compare{background:#66788b!important;color:#fff!important}
.ppt-table th.hl-support{background:#dcefe7!important;color:#214f3e!important}
</style>
"""
    html_text = html_text.replace("</head>", highlight_css + "</head>", 1)

    script = f"""
<script>
(function(){{
  const presetKey = {json.dumps(preset_key)};
  const autoKey = {json.dumps(auto_key)};
  const roles = {{
    second: {{ primary: ['second'], compare: ['prev_close'], support: ['first'] }},
    third: {{ primary: ['third_forecast'], compare: ['prev_close'], support: ['second','third_confirmed'] }},
    close: {{ primary: ['close'], compare: ['third_forecast'], support: ['prev_close'] }}
  }};

  function getAuto(){{
    try {{
      const raw = localStorage.getItem(autoKey);
      return raw === null ? true : raw === '1';
    }} catch(e) {{ return true; }}
  }}
  function getPreset(){{
    try {{ return localStorage.getItem(presetKey) || 'second'; }} catch(e) {{ return 'second'; }}
  }}
  function setPreset(value){{
    try {{ localStorage.setItem(presetKey, value); }} catch(e) {{}}
  }}
  function setAuto(value){{
    try {{ localStorage.setItem(autoKey, value ? '1' : '0'); }} catch(e) {{}}
  }}
  function mark(keys, cls){{
    (keys || []).forEach(key => {{
      document.querySelectorAll('[data-col="' + key + '"]').forEach(el => el.classList.add(cls));
    }});
  }}
  function applyHighlight(){{
    document.querySelectorAll('[data-col]').forEach(el => {{
      el.classList.remove('hl-primary','hl-compare','hl-support');
    }});
    const enabled = getAuto();
    const cb = document.getElementById('auto-highlight');
    if (cb) cb.checked = enabled;
    if (!enabled) return;
    const cfg = roles[getPreset()] || roles.second;
    mark(cfg.compare, 'hl-compare');
    mark(cfg.support, 'hl-support');
    mark(cfg.primary, 'hl-primary');
  }}

  document.querySelectorAll('[data-preset]').forEach(btn => {{
    btn.addEventListener('click', () => {{
      setPreset(btn.dataset.preset || 'second');
      setTimeout(applyHighlight, 0);
    }});
  }});
  const cb = document.getElementById('auto-highlight');
  if (cb) cb.addEventListener('change', () => {{ setAuto(cb.checked); applyHighlight(); }});
  document.querySelectorAll('[data-col-toggle]').forEach(x => x.addEventListener('change', applyHighlight));
  const allBtn = document.getElementById('select-all');
  if (allBtn) allBtn.addEventListener('click', () => setTimeout(applyHighlight, 0));
  const clearBtn = document.getElementById('clear-all');
  if (clearBtn) clearBtn.addEventListener('click', () => setTimeout(applyHighlight, 0));

  applyHighlight();
}})();
</script>
"""
    html_text = html_text.replace("</body>", script + "</body>", 1)
    return html_text


def highlighted_ppt_view():
    if _original_ppt_view is None:
        return "PPT view unavailable", 500
    result = _original_ppt_view()
    if not isinstance(result, str):
        return result
    try:
        year = int(request.args.get("year", 2026))
        month = int(request.args.get("month", 9))
    except Exception:
        year, month = 2026, 9
    if month < 1 or month > 12:
        month = 9
    return _inject_highlight(result, year, month, request.args.get("capture") == "1")


if _original_ppt_view is not None:
    app.view_functions["ppt_view"] = highlighted_ppt_view


def highlight_health():
    payload = _original_health() if _original_health else {"status": "ok"}
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["runtime"] = "excel-layout-v6-ppt-highlight"
        payload["ppt_auto_highlight"] = True
    return payload


app.view_functions["health"] = highlight_health
