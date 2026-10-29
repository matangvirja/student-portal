"""Faculty Console: courses, materials, assignments, grading, gradebook export, analytics.

Every route in this blueprint is guarded by require_teacher() (deny by default), and every
object lookup is scoped to the logged-in teacher's own courses (returns 404 otherwise, so
the existence of other teachers' data is not revealed).
"""
import csv
import io
import re
from datetime import timedelta
from statistics import mean

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from . import storage
from .extensions import db
from .models import Assignment, Course, Enrollment, Material, Submission, new_join_code
from .security import audit
from .timeutil import parse_local, utcnow
from .uploads import UploadError, build_key, read_upload

bp = Blueprint("teacher", __name__, url_prefix="/teacher")

COURSE_CODE_RE = re.compile(r"^[A-Z0-9-]{2,20}$")
COURSE_TABS = ("assignments", "materials", "students")
GRADE_BANDS = [("A", "85–100", 85, 101), ("B", "70–84", 70, 85), ("C", "55–69", 55, 70),
               ("D", "40–54", 40, 55), ("F", "below 40", 0, 40)]


def pct(n, d):
    return round(n * 100 / d) if d else 0


@bp.before_request
@login_required
def require_teacher():
    if not current_user.is_teacher:
        abort(403)


@bp.context_processor
def sidebar_courses():
    if current_user.is_authenticated and current_user.is_teacher:
        return {"my_courses": current_user.courses_taught}
    return {}


# ---------------------------------------------------------------- scoped lookups

def _course(course_id) -> Course:
    course = db.session.get(Course, course_id)
    if course is None or course.teacher_id != current_user.id:
        abort(404)
    return course


def _assignment(assignment_id) -> Assignment:
    a = db.session.get(Assignment, assignment_id)
    if a is None or a.course.teacher_id != current_user.id:
        abort(404)
    return a


def _submission(submission_id) -> Submission:
    s = db.session.get(Submission, submission_id)
    if s is None or s.assignment.course.teacher_id != current_user.id:
        abort(404)
    return s


def _unique_join_code() -> str:
    while True:
        code = new_join_code()
        if not db.session.scalar(select(Course.id).filter_by(join_code=code)):
            return code


def _count_submissions(course_ids, *conditions):
    q = (select(func.count(Submission.id)).select_from(Submission)
         .join(Assignment, Submission.assignment_id == Assignment.id)
         .where(Assignment.course_id.in_(course_ids), *conditions))
    return db.session.scalar(q) or 0


# ---------------------------------------------------------------- overview

@bp.get("/")
def dashboard():
    courses = current_user.courses_taught
    course_ids = [c.id for c in courses]
    now = utcnow()
    kpis = {"courses": len(courses), "students": 0, "to_grade": 0, "week": 0}
    upcoming, recent = [], []

    if course_ids:
        kpis["students"] = db.session.scalar(
            select(func.count(func.distinct(Enrollment.student_id))).where(Enrollment.course_id.in_(course_ids))
        )
        kpis["to_grade"] = _count_submissions(course_ids, Submission.marks.is_(None))
        kpis["week"] = _count_submissions(course_ids, Submission.submitted_at >= now - timedelta(days=7))

        upcoming_assignments = db.session.scalars(
            select(Assignment).where(Assignment.course_id.in_(course_ids), Assignment.due_at >= now)
            .order_by(Assignment.due_at).limit(6)
        ).all()
        upcoming = [{"a": a, "submitted": len(a.submissions), "enrolled": len(a.course.enrollments)}
                    for a in upcoming_assignments]

        recent = db.session.scalars(
            select(Submission).join(Assignment, Submission.assignment_id == Assignment.id)
            .where(Assignment.course_id.in_(course_ids))
            .order_by(Submission.submitted_at.desc()).limit(8)
        ).all()

    course_rows = [{"c": c, "students": len(c.enrollments), "assignments": len(c.assignments)} for c in courses]
    return render_template("teacher/dashboard.html", kpis=kpis, upcoming=upcoming, recent=recent,
                           course_rows=course_rows, now=now, pct=pct)


# ---------------------------------------------------------------- courses

@bp.route("/courses/new", methods=["GET", "POST"])
def course_new():
    form = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("code", "title", "semester", "description")}
        form["code"] = form["code"].upper().replace(" ", "")
        if not COURSE_CODE_RE.match(form["code"]):
            flash("Course code should be 2–20 letters, numbers or dashes, e.g. CS612.", "error")
        elif not form["title"]:
            flash("Give the course a title.", "error")
        else:
            course = Course(code=form["code"], title=form["title"][:160], semester=form["semester"][:40] or None,
                            description=form["description"] or None, teacher_id=current_user.id,
                            join_code=_unique_join_code())
            db.session.add(course)
            db.session.flush()
            audit("course_create", f"{course.code} (id {course.id})")
            db.session.commit()
            flash(f"{course.code} created. Share join code {course.join_code} with your students.", "success")
            return redirect(url_for(".course", course_id=course.id))
    return render_template("teacher/course_new.html", form=form)


@bp.get("/courses/<int:course_id>")
def course(course_id):
    course = _course(course_id)
    tab = request.args.get("tab", "assignments")
    if tab not in COURSE_TABS:
        tab = "assignments"
    enrolled = len(course.enrollments)
    ctx = {}

    if tab == "assignments":
        ctx["rows"] = [{
            "a": a,
            "submitted": len(a.submissions),
            "graded": sum(1 for s in a.submissions if s.is_graded),
            "late": sum(1 for s in a.submissions if s.is_late),
        } for a in course.assignments]

    elif tab == "students":
        subs = db.session.scalars(
            select(Submission).join(Assignment, Submission.assignment_id == Assignment.id)
            .where(Assignment.course_id == course.id)
        ).all()
        by_student = {}
        for s in subs:
            by_student.setdefault(s.student_id, []).append(s)
        roster = []
        for e in sorted(course.enrollments, key=lambda e: e.student.name.lower()):
            mine = by_student.get(e.student_id, [])
            graded = [s.percent for s in mine if s.is_graded]
            roster.append({"enrollment": e, "student": e.student, "submitted": len(mine),
                           "avg": round(mean(graded), 1) if graded else None})
        ctx["roster"] = roster

    return render_template("teacher/course.html", course=course, tab=tab, enrolled=enrolled,
                           now=utcnow(), pct=pct, **ctx)


@bp.post("/courses/<int:course_id>/join-code")
def regenerate_join_code(course_id):
    course = _course(course_id)
    course.join_code = _unique_join_code()
    audit("join_code_regenerate", course.code)
    db.session.commit()
    flash(f"New join code: {course.join_code}. The old code no longer works.", "info")
    return redirect(url_for(".course", course_id=course.id, tab=request.args.get("tab", "assignments")))


@bp.post("/courses/<int:course_id>/students/<int:student_id>/remove")
def remove_student(course_id, student_id):
    course = _course(course_id)
    enrollment = db.session.scalar(select(Enrollment).filter_by(course_id=course.id, student_id=student_id))
    if enrollment is None:
        abort(404)
    name = enrollment.student.name
    db.session.delete(enrollment)
    audit("student_remove", f"{course.code}: user {student_id}")
    db.session.commit()
    flash(f"Removed {name} from {course.code}. Their past submissions are kept.", "info")
    return redirect(url_for(".course", course_id=course.id, tab="students"))


# ---------------------------------------------------------------- materials

@bp.post("/courses/<int:course_id>/materials")
def material_upload(course_id):
    course = _course(course_id)
    file = request.files.get("file")
    try:
        filename, size = read_upload(file)
    except UploadError as e:
        flash(str(e), "error")
        return redirect(url_for(".course", course_id=course.id, tab="materials"))

    title = request.form.get("title", "").strip() or filename
    key = build_key(f"courses/{course.id}/materials", filename)
    storage.save(file.stream, key, file.mimetype)
    db.session.add(Material(course_id=course.id, title=title[:200], filename=filename, storage_key=key,
                            content_type=file.mimetype, size_bytes=size))
    audit("material_upload", f"{course.code}: {filename}")
    db.session.commit()
    flash(f"Shared “{title}” with {course.code}.", "success")
    return redirect(url_for(".course", course_id=course.id, tab="materials"))


@bp.post("/materials/<int:material_id>/delete")
def material_delete(material_id):
    material = db.session.get(Material, material_id)
    if material is None or material.course.teacher_id != current_user.id:
        abort(404)
    course_id = material.course_id
    storage.delete(material.storage_key)
    db.session.delete(material)
    audit("material_delete", material.filename)
    db.session.commit()
    flash(f"Removed “{material.title}”.", "info")
    return redirect(url_for(".course", course_id=course_id, tab="materials"))


# ---------------------------------------------------------------- assignments & grading

@bp.post("/courses/<int:course_id>/assignments")
def assignment_create(course_id):
    course = _course(course_id)
    back = url_for(".course", course_id=course.id, tab="assignments")
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    try:
        due_at = parse_local(request.form.get("due_at", ""))
    except ValueError:
        flash("Enter a valid due date and time.", "error")
        return redirect(back)
    try:
        max_marks = int(request.form.get("max_marks", "100"))
    except ValueError:
        max_marks = 0

    if not title:
        flash("Give the assignment a title.", "error")
        return redirect(back)
    if not 1 <= max_marks <= 1000:
        flash("Maximum marks must be between 1 and 1000.", "error")
        return redirect(back)
    if due_at <= utcnow():
        flash("The due date must be in the future.", "error")
        return redirect(back)

    assignment = Assignment(course_id=course.id, title=title[:200], description=description or None,
                            due_at=due_at, max_marks=max_marks)
    db.session.add(assignment)
    db.session.flush()

    file = request.files.get("attachment")
    if file is not None and file.filename:
        try:
            filename, _size = read_upload(file)
        except UploadError as e:
            db.session.rollback()
            flash(f"Assignment not created: {e}", "error")
            return redirect(back)
        key = build_key(f"courses/{course.id}/assignments/{assignment.id}/brief", filename)
        storage.save(file.stream, key, file.mimetype)
        assignment.attachment_name, assignment.attachment_key = filename, key

    audit("assignment_create", f"{course.code}: {assignment.title}")
    db.session.commit()
    flash(f"Published “{assignment.title}” to {len(course.enrollments)} students.", "success")
    return redirect(url_for(".assignment", assignment_id=assignment.id))


@bp.get("/assignments/<int:assignment_id>")
def assignment(assignment_id):
    a = _assignment(assignment_id)
    show = request.args.get("show", "all")
    subs = {s.student_id: s for s in a.submissions}
    rows = [{"student": u, "sub": subs.get(u.id)} for u in a.course.roster]
    # Submissions from students who have since left the course are still shown.
    enrolled_ids = {u.id for u in a.course.roster}
    rows += [{"student": s.student, "sub": s, "left": True} for s in a.submissions if s.student_id not in enrolled_ids]

    if show == "ungraded":
        rows = [r for r in rows if r["sub"] and not r["sub"].is_graded]
    elif show == "missing":
        rows = [r for r in rows if r["sub"] is None]
    else:
        show = "all"

    graded = [s for s in a.submissions if s.is_graded]
    summary = {
        "enrolled": len(enrolled_ids),
        "submitted": len(a.submissions),
        "late": sum(1 for s in a.submissions if s.is_late),
        "graded": len(graded),
        "avg": round(mean(s.marks for s in graded), 1) if graded else None,
    }
    return render_template("teacher/assignment.html", a=a, rows=rows, summary=summary, show=show, pct=pct)


@bp.post("/submissions/<int:submission_id>/grade")
def grade(submission_id):
    s = _submission(submission_id)
    back = url_for(".assignment", assignment_id=s.assignment_id, show=request.args.get("show", "all"))
    try:
        marks = float(request.form.get("marks", ""))
    except ValueError:
        flash("Enter marks as a number.", "error")
        return redirect(back)
    if not 0 <= marks <= s.assignment.max_marks:  # also rejects NaN / inf
        flash(f"Marks must be between 0 and {s.assignment.max_marks}.", "error")
        return redirect(back)

    previously = s.marks
    s.marks = round(marks, 2)
    s.feedback = request.form.get("feedback", "").strip()[:2000] or None
    s.graded_at = utcnow()
    audit("grade", f"submission {s.id}: {previously} -> {s.marks}/{s.assignment.max_marks}")
    db.session.commit()
    flash(f"Saved {s.marks:g}/{s.assignment.max_marks} for {s.student.name}.", "success")
    return redirect(back + f"#s{s.student_id}")


def _csv_safe(value):
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@bp.get("/courses/<int:course_id>/gradebook.csv")
def gradebook(course_id):
    course = _course(course_id)
    assignments = course.assignments
    subs = {(s.student_id, s.assignment_id): s for a in assignments for s in a.submissions}

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Roll number", "Name", "Email"]
                    + [f"{a.title} (/{a.max_marks})" for a in assignments]
                    + ["Total", "Out of (graded)", "Percentage"])
    for student in course.roster:
        cells, total, out_of = [], 0.0, 0
        for a in assignments:
            s = subs.get((student.id, a.id))
            if s is None:
                cells.append("Missing" if not a.is_open else "")
            elif not s.is_graded:
                cells.append("Ungraded")
            else:
                cells.append(f"{s.marks:g}")
                total += s.marks
                out_of += a.max_marks
        percentage = f"{total * 100 / out_of:.1f}" if out_of else ""
        writer.writerow([_csv_safe(student.roll_number), _csv_safe(student.name), _csv_safe(student.email)]
                        + cells + [f"{total:g}", out_of, percentage])

    audit("gradebook_export", course.code)
    db.session.commit()
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{course.code}-gradebook.csv"'})


# ---------------------------------------------------------------- analytics

@bp.get("/analytics")
def analytics():
    courses = current_user.courses_taught
    selected = request.args.get("course", type=int)
    # Default to the largest course.
    course = _course(selected) if selected else max(courses, key=lambda c: len(c.enrollments), default=None)
    if course is None:
        return render_template("teacher/analytics.html", course=None)

    roster = course.roster
    enrolled = len(roster)
    past_due = [a for a in course.assignments if not a.is_open]

    per_assignment, all_pcts = [], []
    for a in course.assignments:
        subs = a.submissions
        pcts = [s.percent for s in subs if s.is_graded]
        all_pcts += pcts
        per_assignment.append({
            "a": a,
            "submitted": len(subs),
            "submission_rate": pct(len(subs), enrolled),
            "on_time_rate": pct(sum(1 for s in subs if not s.is_late), len(subs)) if subs else None,
            "avg": round(mean(pcts), 1) if pcts else None,
            "graded": len(pcts),
        })

    distribution = [{"band": b, "range": r, "count": sum(1 for p in all_pcts if lo <= p < hi)}
                    for b, r, lo, hi in GRADE_BANDS]
    peak = max((d["count"] for d in distribution), default=0) or 1

    # Early-warning list: students who missed 2+ past deadlines or average below 40%.
    at_risk = []
    for student in roster:
        mine = {s.assignment_id: s for a in course.assignments for s in a.submissions if s.student_id == student.id}
        missed = sum(1 for a in past_due if a.id not in mine)
        graded = [s.percent for s in mine.values() if s.is_graded]
        avg = round(mean(graded), 1) if graded else None
        if missed >= 2 or (avg is not None and avg < 40):
            at_risk.append({"student": student, "missed": missed, "avg": avg})

    total_slots = enrolled * len(past_due)
    submitted_slots = sum(1 for a in past_due for s in a.submissions if s.student_id in {u.id for u in roster})
    kpis = {
        "enrolled": enrolled,
        "assignments": len(course.assignments),
        "avg": round(mean(all_pcts), 1) if all_pcts else None,
        "completion": pct(submitted_slots, total_slots) if total_slots else None,
    }
    return render_template("teacher/analytics.html", course=course, kpis=kpis, per_assignment=per_assignment,
                           distribution=distribution, peak=peak, at_risk=at_risk)
