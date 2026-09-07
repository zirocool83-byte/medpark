import app as base


def scope_pairs(user):
    if not user:
        return []
    p = user.get("permission_type", "")
    if p == "admin":
        return base.ALL_PAIRS
    if p == "domestic_all":
        return [(b, "국내") for b in base.BUSINESSES]
    if p == "dental_domestic":
        return [("덴탈", "국내")]
    if p == "overseas_all":
        return [(b, "해외") for b in base.BUSINESSES]
    if p == "aesthetics_all":
        return [("에스테틱", "국내"), ("에스테틱", "해외")]
    custom = []
    for item in user.get("scopes", []):
        if isinstance(item, list) and len(item) == 2 and tuple(item) in base.ALL_PAIRS:
            custom.append(tuple(item))
    return custom


def can_edit_entry(user, entry):
    if not user:
        return False
    if user.get("role") == "admin" or user.get("manage_all"):
        return True
    return (
        entry.get("user_id") == user.get("user_id")
        and (entry.get("business"), entry.get("region")) in scope_pairs(user)
    )


base.scope_pairs = scope_pairs
base.can_edit_entry = can_edit_entry
app = base.app
