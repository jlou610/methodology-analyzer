"""methodology-analyzer — Weekend 1: auth shell + multi-tenant schema.

The methodology spec builder and the AI analyzer land in Weekend 2. This build
exists to prove: register/login/logout, per-user data isolation, and a clean
deploy to a public Render URL backed by SQLite on a persistent disk.
"""
import json
import logging
import os

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, abort,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

import anthropic

import db
from spec_schema import validate_spec
import analyzer

DAILY_LIMIT = 10  # analyses per user per day

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("methodology-analyzer")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

login_manager = LoginManager(app)
login_manager.login_view = "login"

db.init_db()


def analyzer_configured():
    """True when the analyzer can make API calls (key present)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# Fail loudly at startup if the analyzer can't work — far clearer than a cryptic
# SDK header error on the first analysis. Auth/dashboard still function without it.
if not analyzer_configured():
    logger.warning(
        "\n" + "=" * 70 +
        "\n  ANTHROPIC_API_KEY is NOT set. Auth and the dashboard will work, but"
        "\n  running an analysis will fail until you set it (e.g. in a local .env)."
        "\n" + "=" * 70)


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


# ── Methodology spec builder ─────────────────────────────────────────
@app.route("/methodology")
@login_required
def methodology_list():
    specs = db.list_specs(current_user.id)
    return render_template("methodology_list.html", specs=specs)


@app.route("/methodology/new")
@login_required
def methodology_new():
    # Empty form; the JS builds the spec object and POSTs it to /api/methodology.
    return render_template("methodology_form.html", spec=None, spec_id=None, name="")


@app.route("/methodology/<int:spec_id>/edit")
@login_required
def methodology_edit(spec_id):
    row = db.get_spec(current_user.id, spec_id)
    if not row:
        abort(404)
    return render_template(
        "methodology_form.html",
        spec=json.loads(row["spec_json"]),   # parsed; |tojson in template hydrates safely
        spec_id=spec_id,
        name=row["name"],
    )


@app.route("/api/methodology", methods=["POST"])
@app.route("/api/methodology/<int:spec_id>", methods=["PUT"])
@login_required
def api_methodology_save(spec_id=None):
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    spec = payload.get("spec") or {}

    errors = validate_spec(name, spec)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 422

    spec_json = json.dumps(spec, ensure_ascii=False)
    if spec_id is None:
        new_id = db.create_spec(current_user.id, name, spec_json, make_active=True)
        return jsonify({"ok": True, "id": new_id}), 201

    if not db.update_spec(current_user.id, spec_id, name, spec_json):
        abort(404)
    return jsonify({"ok": True, "id": spec_id})


@app.route("/methodology/<int:spec_id>/activate", methods=["POST"])
@login_required
def methodology_activate(spec_id):
    if not db.set_active_spec(current_user.id, spec_id):
        abort(404)
    return redirect(url_for("methodology_list"))


@app.route("/methodology/<int:spec_id>/delete", methods=["POST"])
@login_required
def methodology_delete(spec_id):
    db.delete_spec(current_user.id, spec_id)
    return redirect(url_for("methodology_list"))


# ── Analyzer ─────────────────────────────────────────────────────────
@app.route("/analyze", methods=["GET", "POST"])
@login_required
def analyze():
    active = db.get_active_spec(current_user.id)
    used = db.count_sessions_today(current_user.id)
    remaining = max(0, DAILY_LIMIT - used)

    if request.method == "POST":
        if not active:
            flash("Define and activate a methodology first.", "error")
            return redirect(url_for("methodology_list"))

        # Server-side rate limit (authoritative).
        if used >= DAILY_LIMIT:
            flash(f"You've used your {DAILY_LIMIT} analyses for today. "
                  f"Limit resets at midnight UTC.", "error")
            return render_template("analyze.html", spec=active, used=used,
                                   remaining=0, limit=DAILY_LIMIT)

        title = (request.form.get("title") or "").strip()
        observations = (request.form.get("observations") or "").strip()
        if not observations:
            flash("Describe the current situation before analyzing.", "error")
            return render_template("analyze.html", spec=active, used=used,
                                   remaining=remaining, limit=DAILY_LIMIT,
                                   title=title)

        # Guard the missing-key case before touching the SDK, so the user gets a
        # clean message instead of a TypeError out of the Anthropic client.
        if not analyzer_configured():
            logger.error("analysis attempted but ANTHROPIC_API_KEY is not set")
            flash("The analysis service isn't configured yet. Please try again later.", "error")
            return render_template("analyze.html", spec=active, used=used,
                                   remaining=remaining, limit=DAILY_LIMIT,
                                   title=title, observations=observations)

        spec = json.loads(active["spec_json"])
        analysis_input = {"title": title, "observations": observations}
        try:
            result = analyzer.run_analysis(spec, analysis_input)
        except anthropic.RateLimitError:
            flash("The analyzer is busy right now. Try again in a moment.", "error")
            return render_template("analyze.html", spec=active, used=used,
                                   remaining=remaining, limit=DAILY_LIMIT,
                                   title=title, observations=observations)
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            logger.error("analyzer API error: %s", e)
            flash("Unable to reach the analysis service. Please try again.", "error")
            return render_template("analyze.html", spec=active, used=used,
                                   remaining=remaining, limit=DAILY_LIMIT,
                                   title=title, observations=observations)
        except Exception:
            logger.exception("analysis failed unexpectedly")
            flash("Unable to reach the analysis service. Please try again.", "error")
            return render_template("analyze.html", spec=active, used=used,
                                   remaining=remaining, limit=DAILY_LIMIT,
                                   title=title, observations=observations)

        sid = db.create_analysis_session(
            current_user.id, active["id"], title or "Untitled",
            json.dumps(analysis_input, ensure_ascii=False),
            result["text"],
            json.dumps({"sections": result["sections"], "usage": result["usage"],
                        "model": result["model"]}, ensure_ascii=False),
        )
        return redirect(url_for("analysis_detail", session_id=sid))

    return render_template("analyze.html", spec=active, used=used,
                           remaining=remaining, limit=DAILY_LIMIT,
                           configured=analyzer_configured())


@app.route("/analysis/<int:session_id>")
@login_required
def analysis_detail(session_id):
    row = db.get_analysis_session(current_user.id, session_id)
    if not row:
        abort(404)
    parsed = json.loads(row["output_json"]) if row["output_json"] else {}
    analysis_input = json.loads(row["input_json"]) if row["input_json"] else {}
    # edge_thesis + grading scale come from the spec the analysis ran against.
    edge_thesis, grading_scale = "", {}
    if row["spec_id"]:
        spec_row = db.get_spec(current_user.id, row["spec_id"])
        if spec_row:
            spec = json.loads(spec_row["spec_json"])
            edge_thesis = (spec.get("trader") or {}).get("edge_thesis", "")
            grading_scale = (spec.get("conviction_rules") or {}).get("grading_scale", {})
    return render_template(
        "analysis_detail.html",
        row=row,
        sections=parsed.get("sections", {}),
        usage=parsed.get("usage", {}),
        model=parsed.get("model", ""),
        analysis_input=analysis_input,
        edge_thesis=edge_thesis,
        grading_scale=grading_scale,
        section_order=analyzer.SECTIONS,
        outcomes=OUTCOMES,
    )


OUTCOMES = ("correct", "incorrect", "partial", "no-trade")


@app.route("/analysis/<int:session_id>/outcome", methods=["POST"])
@login_required
def analysis_outcome(session_id):
    if not db.get_analysis_session(current_user.id, session_id):
        abort(404)
    outcome = (request.form.get("outcome") or "").strip()
    if outcome and outcome not in OUTCOMES:
        abort(400)
    what_happened = (request.form.get("what_happened") or "").strip()
    db.update_outcome(current_user.id, session_id, outcome, what_happened)
    flash("Outcome saved.", "success")
    return redirect(url_for("analysis_detail", session_id=session_id))


@app.route("/healthz")
def healthz():
    """Render health check — verifies the DB is reachable."""
    db.get_user_by_id(0)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
