"""methodology-analyzer — Weekend 1: auth shell + multi-tenant schema.

The methodology spec builder and the AI analyzer land in Weekend 2. This build
exists to prove: register/login/logout, per-user data isolation, and a clean
deploy to a public Render URL backed by SQLite on a persistent disk.
"""
import os

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

import db

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

login_manager = LoginManager(app)
login_manager.login_view = "login"

db.init_db()


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.email = row["email"]


@login_manager.user_loader
def load_user(user_id):
    row = db.get_user_by_id(int(user_id))
    return User(row) if row else None


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or "@" not in email:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif db.get_user_by_email(email):
            flash("An account with that email already exists.", "error")
        else:
            uid = db.create_user(email, generate_password_hash(password))
            login_user(User(db.get_user_by_id(uid)))
            return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        row = db.get_user_by_email(email)
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    # Scoped to the logged-in user — proves multi-tenant isolation.
    specs = db.list_specs(current_user.id)
    sessions = db.list_sessions(current_user.id)
    return render_template("dashboard.html", specs=specs, sessions=sessions)


@app.route("/healthz")
def healthz():
    """Render health check — verifies the DB is reachable."""
    db.get_user_by_id(0)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
