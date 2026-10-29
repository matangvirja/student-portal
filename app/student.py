"""Student Hub: join courses, see deadlines, download materials, submit work, view grades.

Every route is guarded by require_student(); course and assignment lookups return 404 unless
the student is enrolled in that course.
"""
from statistics import mean

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from . import storage
from .extensions import db
from .models import Assignment, Course, Enrollment, Submission, status_for
from .security import audit
from .timeutil import as_utc, utcnow
from .uploads import UploadError, build_key, read_upload

bp = Blueprint("student", __name__, url_prefix="/student")


@bp.before_request
@login_required
def require_student():
    if not current_user.is_student:
        abort(403)


def _my_courses():
    return sorted((e.course for e in current_user.enrollments), key=lambda c: c.code)


def _course(course_id) -> Course:
    course = db.session.get(Course, course_id)
    if course is None or not course.has_student(current_user.id):
        abort(404)
    return course


def _assignment(assignment_id) -> Assignment:
    a = db.session.get(Assignment, assignment_id)
    if a is None or not a.course.has_student(current_user.id):
        abort(404)
    return a


def _my_submissions() -> dict:
    subs = db.session.scalars(select(Submission).filter_by(student_id=current_user.id)).all()
    return {s.assignment_id: s for s in subs}


@bp.get("/")
def dashboard():
    courses = _my_courses()
    subs = _my_submissions()
    items = []
    for course_index, c in enumerate(courses):
        for a in c.assignments:
            sub = subs.get(a.id)
            items.append({"a": a, "sub": sub, "status": status_for(a, sub), "color": course_index % 4})

    todo = sorted((i for i in items if i["sub"] is None and i["a"].is_open), key=lambda i: as_utc(i["a"].due_at))
    overdue = [i for i in items if i["sub"] is None and not i["a"].is_open]
    graded = sorted((i for i in items if i["sub"] and i["sub"].is_graded),
                    key=lambda i: as_utc(i["sub"].graded_at), reverse=True)
    due_this_week = sum(1 for i in todo if (as_utc(i["a"].due_at) - utcnow()).days < 7)
    submitted = sum(1 for i in items if i["sub"])
    pcts = [i["sub"].percent for i in graded]

    course_cards = [{"c": c, "color": n % 4,
                     "open": sum(1 for i in todo if i["a"].course_id == c.id)} for n, c in enumerate(courses)]
    return render_template(
        "student/dashboard.html", course_cards=course_cards, todo=todo, overdue=overdue,
        recent_grades=graded[:4], due_this_week=due_this_week,
        completion=round(submitted * 100 / len(items)) if items else 0,
        submitted=submitted, total=len(items),
        average=round(mean(pcts), 1) if pcts else None,
    )


@bp.post("/join")
def join():
    code = request.form.get("join_code", "").strip().upper().replace(" ", "")
    course = db.session.scalar(select(Course).filter_by(join_code=code)) if code else None
    if course is None:
        flash("No course matches that code. Check it with your instructor.", "error")
        return redirect(url_for(".dashboard"))
    if course.has_student(current_user.id):
        flash(f"You're already enrolled in {course.code}.", "info")
        return redirect(url_for(".course", course_id=course.id))

    db.session.add(Enrollment(course_id=course.id, student_id=current_user.id))
    audit("course_join", course.code)
    db.session.commit()
    flash(f"You've joined {course.code}: {course.title}.", "success")
    return redirect(url_for(".course", course_id=course.id))


@bp.get("/courses/<int:course_id>")
def course(course_id):
    course = _course(course_id)
    subs = _my_submissions()
    items = [{"a": a, "sub": subs.get(a.id), "status": status_for(a, subs.get(a.id))} for a in course.assignments]
    color = next((n % 4 for n, c in enumerate(_my_courses()) if c.id == course.id), 0)
    return render_template("student/course.html", course=course, items=items, color=color)


@bp.get("/assignments/<int:assignment_id>")
def assignment(assignment_id):
    a = _assignment(assignment_id)
    sub = a.submission_for(current_user.id)
    return render_template("student/assignment.html", a=a, sub=sub, status=status_for(a, sub))


@bp.post("/assignments/<int:assignment_id>/submit")
def submit(assignment_id):
    a = _assignment(assignment_id)
    back = url_for(".assignment", assignment_id=a.id)
    sub = a.submission_for(current_user.id)
    if sub is not None and sub.is_graded:
        flash("This work has already been graded, so it can't be replaced.", "error")
        return redirect(back)

    file = request.files.get("file")
    try:
        filename, size = read_upload(file)
    except UploadError as e:
        flash(str(e), "error")
        return redirect(back)

    key = build_key(f"courses/{a.course_id}/assignments/{a.id}/submissions/{current_user.id}", filename)
    storage.save(file.stream, key, file.mimetype)

    old_key = None
    if sub is None:
        sub = Submission(assignment_id=a.id, student_id=current_user.id)
        db.session.add(sub)
    else:
        old_key = sub.storage_key
    sub.filename, sub.storage_key, sub.content_type, sub.size_bytes = filename, key, file.mimetype, size
    sub.submitted_at = utcnow()
    audit("submission" if old_key is None else "resubmission", f"assignment {a.id}: {filename}")
    db.session.commit()

    if old_key:
        try:
            storage.delete(old_key)
        except Exception:  # an orphaned old object is harmless; never fail the student's upload
            current_app.logger.exception("Could not delete replaced submission object")

    if sub.is_late:
        flash("Submitted. It's after the deadline, so it's marked late.", "info")
    else:
        flash(f"Submitted {filename}. You can replace it until the deadline.", "success")
    return redirect(back)


@bp.get("/grades")
def grades():
    subs = _my_submissions()
    groups = []
    for n, c in enumerate(_my_courses()):
        rows = [{"a": a, "sub": subs.get(a.id), "status": status_for(a, subs.get(a.id))} for a in c.assignments]
        graded = [r["sub"] for r in rows if r["sub"] and r["sub"].is_graded]
        scored = sum(s.marks for s in graded)
        out_of = sum(s.assignment.max_marks for s in graded)
        groups.append({"c": c, "rows": rows, "color": n % 4, "scored": scored, "out_of": out_of,
                       "percent": round(scored * 100 / out_of, 1) if out_of else None})
    all_pcts = [g["percent"] for g in groups if g["percent"] is not None]
    return render_template("student/grades.html", groups=groups,
                           overall=round(mean(all_pcts), 1) if all_pcts else None)
