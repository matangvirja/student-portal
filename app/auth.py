"""Public pages and authentication (signup with role selection, login, logout)."""
import hmac
import re

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .models import Role, User
from .security import audit, safe_next

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLL_RE = re.compile(r"^[A-Za-z0-9/-]{3,32}$")


def home_for(user) -> str:
    return url_for("teacher.dashboard") if user.is_teacher else url_for("student.dashboard")


def _password_problem(password: str):
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain both letters and numbers."
    return None


@bp.get("/")
def landing():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return render_template("auth/landing.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))

    form = {"role": request.args.get("role", Role.STUDENT)}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("role", "name", "email", "department", "roll_number", "faculty_code")}
        form["email"] = form["email"].lower()
        form["roll_number"] = form["roll_number"].upper()
        password = request.form.get("password", "")

        error = None
        if form["role"] not in Role.ALL:
            error = "Choose whether you are a student or a faculty member."
        elif not form["name"] or not EMAIL_RE.match(form["email"]):
            error = "Enter your full name and a valid email address."
        elif _password_problem(password):
            error = _password_problem(password)
        elif form["role"] == Role.STUDENT and not ROLL_RE.match(form["roll_number"]):
            error = "Enter your enrolment / roll number (e.g. 24MCS017)."
        elif form["role"] == Role.TEACHER and not hmac.compare_digest(
                form["faculty_code"].encode(), current_app.config["TEACHER_INVITE_CODE"].encode()):
            error = "That faculty access code is not valid. Ask your department administrator."
        elif db.session.scalar(db.select(User.id).filter_by(email=form["email"])):
            error = "An account with that email already exists."
        elif form["role"] == Role.STUDENT and db.session.scalar(
                db.select(User.id).filter_by(roll_number=form["roll_number"])):
            error = "That roll number is already registered."

        if error:
            if form["role"] == Role.TEACHER and "access code" in error:
                audit("signup_rejected", f"bad faculty code for {form['email']}")
                db.session.commit()
            flash(error, "error")
            form.pop("faculty_code", None)
            return render_template("auth/signup.html", form=form), 400

        user = User(
            name=form["name"], email=form["email"], role=form["role"],
            department=form["department"] or None,
            roll_number=form["roll_number"] if form["role"] == Role.STUDENT else None,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        audit("signup", f"role={user.role}", user_id=user.id)
        db.session.commit()
        login_user(user)
        flash(f"Welcome to the portal, {user.first_name}!", "success")
        return redirect(home_for(user))

    return render_template("auth/signup.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).filter_by(email=email))
        if user is None or not user.check_password(password):
            audit("login_failed", email, user_id=user.id if user else None)
            db.session.commit()
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html", email=email), 401

        login_user(user, remember=bool(request.form.get("remember")))
        audit("login", f"role={user.role}", user_id=user.id)
        db.session.commit()
        return redirect(safe_next(request.args.get("next")) or home_for(user))

    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    audit("logout")
    db.session.commit()
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
