"""Smoke test for the Weekend 2 spec builder (Gate 1)."""
import os, tempfile, json
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "spec.db")
os.environ["SECRET_KEY"] = "test"

import app as application
app = application.app

def reg(c, email, pw="password1"):
    return c.post("/register", data={"email": email, "password": pw}, follow_redirects=True)

VALID = {
    "name": "Swing breakouts (Maya)",
    "spec": {
        "trader": {"name": "Maya", "style_summary": "Swing-trade leading growth stocks breaking out of bases.",
                   "edge_thesis": "Breakouts on volume reflect institutional accumulation.",
                   "markets": ["US equities"], "instruments": ["shares"],
                   "timeframes": {"context": ["weekly", "daily"], "trigger": ["daily"]},
                   "holding_style": "swing", "workflow": "Review nightly."},
        "terminology": {"confluence_label": "Confluence"},
        "context_inputs": [{"name": "Market trend", "what_it_tells_me": "green light vs stand down"}],
        "setups": [{"name": "Base breakout", "direction": "long", "thesis": "clears pivot on volume",
                    "trigger": "closes above pivot on 150%+ volume", "confluence": ["RS new high"],
                    "invalidation": "closes back below pivot", "red_flags": ["earnings <5d"], "management": "stop -7%"}],
        "conviction_rules": {"grading_scale": {"type": "ordinal", "tiers": ["A", "B", "C"], "range": "", "notes": ""},
                             "high_conviction": "uptrend + leader + clean base", "low_or_skip": "choppy market",
                             "hard_filters": ["No breakout with earnings inside 5 days"]},
        "risk": {"per_trade": "0.5-1%", "max_concurrent": "5", "notes": ""},
    },
}

cA = app.test_client(); reg(cA, "a@x.com")

# 1. invalid spec (no hard filters) -> 422
bad = json.loads(json.dumps(VALID)); bad["spec"]["conviction_rules"]["hard_filters"] = []
r = cA.post("/api/methodology", json=bad)
assert r.status_code == 422 and any("hard filter" in e for e in r.get_json()["errors"]), "bad spec not rejected"

# 2. invalid: setup missing invalidation -> 422
bad2 = json.loads(json.dumps(VALID)); bad2["spec"]["setups"][0]["invalidation"] = ""
r = cA.post("/api/methodology", json=bad2)
assert r.status_code == 422 and any("trigger and an invalidation" in e for e in r.get_json()["errors"]), "bad setup not rejected"

# 3. valid -> 201
r = cA.post("/api/methodology", json=VALID)
assert r.status_code == 201, f"valid save failed: {r.status_code} {r.data}"
spec_id = r.get_json()["id"]

# 4. list shows it
r = cA.get("/methodology")
assert b"Swing breakouts (Maya)" in r.data, "list missing spec"

# 5. edit page renders + embeds the spec for hydration
r = cA.get(f"/methodology/{spec_id}/edit")
assert r.status_code == 200 and b"Base breakout" in r.data, "edit page missing hydration data"

# 6. PUT edit
edit = json.loads(json.dumps(VALID)); edit["name"] = "Renamed method"
r = cA.put(f"/api/methodology/{spec_id}", json=edit)
assert r.status_code == 200 and r.get_json()["ok"], "edit failed"
assert b"Renamed method" in cA.get("/methodology").data, "rename not persisted"

# 7. isolation: user B cannot edit or view A's spec
cB = app.test_client(); reg(cB, "b@x.com")
assert cB.put(f"/api/methodology/{spec_id}", json=edit).status_code == 404, "ISOLATION BREACH: B edited A's spec"
assert cB.get(f"/methodology/{spec_id}/edit").status_code == 404, "ISOLATION BREACH: B viewed A's spec"
assert b"Renamed method" not in cB.get("/methodology").data, "ISOLATION BREACH: B sees A's spec in list"

# 8. second spec becomes active, first goes inactive
import db
a_id = db.get_user_by_email("a@x.com")["id"]
r = cA.post("/api/methodology", json=VALID); spec2 = r.get_json()["id"]
active = db.get_active_spec(a_id)
assert active and active["id"] == spec2, "newest spec should be active"
specs = {s["id"]: s["is_active"] for s in db.list_specs(a_id)}
assert specs[spec_id] == 0, "old spec should have gone inactive"
print("ALL SPEC-BUILDER TESTS PASSED  (active flips to newest, isolation holds, validation enforced)")
