import os
from datetime import date
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp

from models import Habit, HabitLog, User, db

load_dotenv()

# On Render, DATABASE_URL is set, so we are in production.
IS_PROD = "DATABASE_URL" in os.environ
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///local.db").replace("postgres://", "postgresql://", 1)
MAX_HABITS = 50

app = Flask(__name__, static_folder="statics")
if IS_PROD:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],
    SQLALCHEMY_DATABASE_URI=DB_URL,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PROD,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=IS_PROD,
    MAX_CONTENT_LENGTH=64 * 1024,
)

db.init_app(app)
Migrate(app, db)
CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["300 per hour"], storage_uri="memory://")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Log in to see your habits."

# Used so a login for an unknown email takes as long as one for a real email.
DUMMY_HASH = generate_password_hash("not-a-real-password")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    if IS_PROD:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


# ---------- Forms ----------
class RegisterForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(3, 30),
            Regexp(r"^\w+$", message="Use letters, numbers and underscores only."),
        ],
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(10, 128, message="Use at least 10 characters.")])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords don't match.")])


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


# ---------- Auth ----------
def is_safe_next(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/") and not target.startswith("//")


@app.route("/")
def index():
    return redirect(url_for("dashboard" if current_user.is_authenticated else "login"))


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        taken = User.query.filter(
            (User.email == email) | (db.func.lower(User.username) == username.lower())
        ).first()
        if taken:
            flash("That username or email is already in use.", "error")
        else:
            user = User(username=username, email=email)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Account created. Log in to start tracking.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user:
            ok = user.check_password(form.password.data)
        else:
            check_password_hash(DUMMY_HASH, form.password.data)
            ok = False
        if ok:
            login_user(user)
            nxt = request.args.get("next")
            return redirect(nxt if is_safe_next(nxt) else url_for("dashboard"))
        flash("Wrong email or password.", "error")
    return render_template("login.html", form=form)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You are logged out.", "success")
    return redirect(url_for("login"))


# ---------- Habits ----------
def get_own_habit(habit_id):
    # Always filter by the logged-in user so nobody can touch another user's data.
    return Habit.query.filter_by(id=habit_id, user_id=current_user.id).first_or_404()


@app.route("/dashboard")
@login_required
def dashboard():
    today = date.today()
    habits = Habit.query.filter_by(user_id=current_user.id).order_by(Habit.created_at).all()
    cards = []
    for h in habits:
        current, longest, week, done = h.stats(today)
        cards.append({"habit": h, "current": current, "longest": longest, "week": week, "done": done})
    done_count = sum(1 for c in cards if c["done"])
    return render_template("dashboard.html", cards=cards, today=today, done_count=done_count)


@app.route("/habits/add", methods=["POST"])
@login_required
def add_habit():
    name = request.form.get("name", "").strip()
    if not name or len(name) > 100:
        flash("Enter a habit name up to 100 characters.", "error")
    elif Habit.query.filter_by(user_id=current_user.id).count() >= MAX_HABITS:
        flash(f"You can track up to {MAX_HABITS} habits.", "error")
    else:
        db.session.add(Habit(name=name, user_id=current_user.id))
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/habit/<int:habit_id>/toggle", methods=["POST"])
@login_required
def toggle_habit(habit_id):
    habit = get_own_habit(habit_id)
    today = date.today()
    log = HabitLog.query.filter_by(habit_id=habit.id, log_date=today).first()
    if log:
        db.session.delete(log)
    else:
        db.session.add(HabitLog(habit_id=habit.id, log_date=today))
    db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/habit/<int:habit_id>/rename", methods=["POST"])
@login_required
def rename_habit(habit_id):
    habit = get_own_habit(habit_id)
    name = request.form.get("name", "").strip()
    if name and len(name) <= 100:
        habit.name = name
        db.session.commit()
    else:
        flash("Enter a habit name up to 100 characters.", "error")
    return redirect(url_for("dashboard"))


@app.route("/habit/<int:habit_id>/delete", methods=["POST"])
@login_required
def delete_habit(habit_id):
    habit = get_own_habit(habit_id)
    db.session.delete(habit)
    db.session.commit()
    flash("Habit deleted.", "success")
    return redirect(url_for("dashboard"))


# ---------- Errors ----------
@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


@app.errorhandler(429)
def too_many(e):
    return render_template("error.html", code=429, message="Too many attempts. Wait a minute and try again."), 429


@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    return render_template("error.html", code=500, message="Something went wrong on our side."), 500


if __name__ == "__main__":
    app.run(debug=not IS_PROD)