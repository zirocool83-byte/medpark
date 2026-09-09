"""회차 기록 저장소.

실적 원장(entries/actuals)이 든 메인 저장소는 절대 건드리지 않는다.
회차 기록은 DATA_DIR 아래 별도 파일에 원자적으로 쓴다.

파일: narrative_rounds.json
{
  "rounds": {
    "2026-09:r1": {
      "updated_at": "...", "updated_by": {...},
      "numbers": {...}, "factors": {...}, "lists": {...},
      "narratives": {...}, "meta": {...},
      "history": [ {"at":..., "by":..., "note":...} ]
    }
  }
}
"""

import json
import os
import time
from pathlib import Path

HISTORY_LIMIT = 60
ROUND_LIMIT = 400


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class RoundStore:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "narrative_rounds.json"

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and isinstance(payload.get("rounds"), dict):
                return payload
        except Exception:
            pass
        return {"rounds": {}}

    def _write(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def get(self, key):
        return self._read().get("rounds", {}).get(key)

    def list_keys(self):
        return sorted(self._read().get("rounds", {}).keys())

    def summaries(self, limit=40):
        rounds = self._read().get("rounds", {})
        out = []
        for key in sorted(rounds.keys(), reverse=True)[:limit]:
            record = rounds[key] or {}
            out.append({
                "key": key,
                "updated_at": record.get("updated_at"),
                "updated_by": (record.get("updated_by") or {}).get("display_name"),
                "revisions": len(record.get("history") or []),
                "totals": (record.get("meta") or {}).get("totals"),
            })
        return out

    def save(self, key, patch, user, note=""):
        """부분 갱신. patch에 있는 항목만 덮어쓴다."""
        payload = self._read()
        rounds = payload.setdefault("rounds", {})
        record = rounds.get(key) or {}
        history = list(record.get("history") or [])

        before = {k: record.get(k) for k in ("numbers", "factors", "lists", "narratives")}
        for field in ("numbers", "factors", "lists", "narratives", "meta"):
            if field in patch:
                record[field] = patch[field]
        after = {k: record.get(k) for k in ("numbers", "factors", "lists", "narratives")}

        changed = [k for k in after if before.get(k) != after.get(k)]
        record["updated_at"] = _now()
        record["updated_by"] = {
            "user_id": (user or {}).get("user_id"),
            "display_name": (user or {}).get("display_name"),
        }
        if changed or note:
            history.append({
                "at": record["updated_at"],
                "by": record["updated_by"].get("display_name"),
                "changed": changed,
                "note": note or "",
            })
        record["history"] = history[-HISTORY_LIMIT:]

        rounds[key] = record
        if len(rounds) > ROUND_LIMIT:
            for stale in sorted(rounds.keys())[: len(rounds) - ROUND_LIMIT]:
                rounds.pop(stale, None)
        self._write(payload)
        return record


def scope_of(user, scopes):
    """사용자의 편집 범위를 (지역들, 사업분야들)로 돌려준다."""
    if not user:
        return {"regions": [], "businesses": [], "readonly": True, "label": "조회 전용"}
    if user.get("manage_all") or user.get("role") == "admin":
        return {
            "regions": ["국내", "해외"],
            "businesses": ["덴탈", "메디컬", "에스테틱"],
            "readonly": False,
            "label": "전체",
        }
    scope = (scopes or {}).get(user.get("permission_type"))
    if not scope:
        return {"regions": [], "businesses": [], "readonly": True, "label": "조회 전용"}
    regions = list(scope.get("regions") or [])
    businesses = list(scope.get("businesses") or [])
    return {
        "regions": regions,
        "businesses": businesses,
        "readonly": not (regions and businesses),
        "label": "/".join(regions) + " " + "·".join(businesses),
    }


def can_edit(scope, region, business):
    return bool(scope) and region in (scope.get("regions") or []) and business in (scope.get("businesses") or [])
