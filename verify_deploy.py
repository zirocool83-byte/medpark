import patched_app as patched

base = patched.base
data = base.read_store()

assert data.get("meta", {}).get("initialized") is True
assert data.get("meta", {}).get("seed_version") == "2026-09-07-v2-auto"
assert len(data.get("users", [])) >= 10
assert len(data.get("actuals", {})) >= 84
assert len(data.get("entries", [])) >= 87

# 운영 중 사용자/실적이 추가될 수 있으므로 '정확히 N개'가 아니라 필수 기준 사용자와 기준값만 검증한다.
expected = {
    "mp001": ("김홍윤", "domestic_all", "member", True),
    "mp002": ("김태현", "admin", "admin", True),
    "mp003": ("박재흥", "dental_domestic", "member", False),
    "mp004": ("김경태", "overseas_all", "member", False),
    "mp005": ("박정현", "overseas_all", "member", False),
    "mp006": ("장윤선", "overseas_all", "member", False),
    "mp007": ("최령", "overseas_all", "member", False),
    "mp008": ("김예원", "overseas_all", "member", False),
    "mp009": ("이인경", "aesthetics_all", "member", False),
    "mp010": ("유동혁", "aesthetics_all", "member", False),
}
users = {u.get("user_id"): u for u in data.get("users", [])}
for uid, (name, permission, role, manage_all) in expected.items():
    assert uid in users, ("missing user", uid)
    u = users[uid]
    assert u.get("display_name") == name
    assert u.get("permission_type") == permission
    assert u.get("role") == role
    assert bool(u.get("manage_all")) == manage_all
    assert str(u.get("password_hash", "")).startswith("pbkdf2:sha256:")

assert patched.scope_pairs(users["mp001"]) == [
    ("덴탈", "국내"), ("메디컬", "국내"), ("에스테틱", "국내")
]
assert patched.scope_pairs(users["mp002"]) == base.ALL_PAIRS
assert patched.scope_pairs(users["mp003"]) == [("덴탈", "국내")]
assert patched.scope_pairs(users["mp004"]) == [
    ("덴탈", "해외"), ("메디컬", "해외"), ("에스테틱", "해외")
]
assert patched.scope_pairs(users["mp009"]) == [
    ("에스테틱", "국내"), ("에스테틱", "해외")
]

overseas_seed = next(e for e in data["entries"] if e.get("region") == "해외")
assert patched.can_edit_entry(users["mp001"], overseas_seed) is True
assert patched.can_edit_entry(users["mp003"], overseas_seed) is False

# 기준 데이터가 보존됐는지만 검증한다. 운영 중 추가된 실적/회차는 허용한다.
report = base.report_data(2026, 8)
grand = next(r for r in report["rows"] if r.get("is_grand"))
checks = {
    "ytd": (grand["ytd"], 9417886063),
    "aug_1": (grand["first"], 1643693152),
    "aug_2": (grand["second"], 1772844502.6230001),
    "aug_3_confirmed": (grand["third_confirmed"], 1176386384),
    "aug_3_forecast": (grand["third_forecast"], 1483709990),
    "sep_1": (grand["next_first"], 1784250384),
}
for key, (actual, expected_value) in checks.items():
    assert abs(float(actual) - float(expected_value)) < 0.01, (key, actual, expected_value)

print(
    "Deployment verification passed: baseline users/permissions and performance values are intact; "
    f"current counts users={len(data.get('users', []))}, actuals={len(data.get('actuals', {}))}, entries={len(data.get('entries', []))}."
)
