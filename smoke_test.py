"""Throwaway smoke test for the Weekend 1 auth shell + tenant isolation."""
import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ["SECRET_KEY"] = "test"

import app as application
app = application.app
app.config["WTF_CSRF_ENABLED"] = False

def client():
    return app.test_client()

# 1. health check
c = client()
assert c.get("/healthz").get_json()["status"] == "ok", "healthz failed"

# 2. unauthenticated dashboard -> redirect to login
r = c.get("/dashboard")
assert r.status_code == 302 and "/login" in r.headers["Location"], "no auth gate"

# 3. register user A
r = c.post("/register", data={"email": "a@x.com", "password": "password1"}, follow_redirects=True)
assert b"a@x.com" in r.data, "register A did not land on dashboard"

# 4. logout, register user B
client_a = c
c2 = client()
r = c2.post("/register", data={"email": "b@x.com", "password": "password2"}, follow_redirects=True)
assert b"b@x.com" in r.data, "register B failed"

# 5. duplicate email rejected
c3 = client()
r = c3.post("/register", data={"email": "a@x.com", "password": "password3"}, follow_redirects=True)
assert b"already exists" in r.data, "duplicate email not rejected"

# 6. wrong password rejected
c4 = client()
r = c4.post("/login", data={"email": "a@x.com", "password": "wrong"}, follow_redirects=True)
assert b"Incorrect email or password" in r.data, "bad password not rejected"

# 7. correct login works
c5 = client()
r = c5.post("/login", data={"email": "a@x.com", "password": "password1"}, follow_redirects=True)
assert b"a@x.com" in r.data, "valid login failed"

# 8. tenant isolation: insert a spec for A, confirm B can't see it
import db
with db.get_db() as conn:
    a_id = db.get_user_by_email("a@x.com")["id"]
    b_id = db.get_user_by_email("b@x.com")["id"]
    conn.execute("INSERT INTO methodology_specs (user_id, name, spec_json) VALUES (?,?,?)",
                 (a_id, "A secret method", "{}"))
assert len(db.list_specs(a_id)) == 1, "A should see own spec"
assert len(db.list_specs(b_id)) == 0, "ISOLATION BREACH: B sees A's spec"

# 9. short password rejected
c6 = client()
r = c6.post("/register", data={"email": "c@x.com", "password": "short"}, follow_redirects=True)
assert b"at least 8" in r.data, "short password not rejected"

print("ALL SMOKE TESTS PASSED")
