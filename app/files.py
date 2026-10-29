"""File downloads shared by both roles, with per-object authorization.

  material / assignment brief  -> the course's teacher, or a student enrolled in the course
  submission                   -> the student who submitted it, or the course's teacher
Anything else gets 404 (not 403), so file IDs can't be probed.
"""
from flask import Blueprint, abort
from flask_login import current_user, login_required

from . import storage
from .extensions import db
from .models import Assignment, Material, Submission

bp = Blueprint("files", __name__, url_prefix="/files")


@bp.before_request
@login_required
def require_login():
    pass


def _can_view_course(course) -> bool:
    if current_user.is_teacher:
        return course.teacher_id == current_user.id
    return course.has_student(current_user.id)


@bp.get("/materials/<int:material_id>")
def material(material_id):
    m = db.session.get(Material, material_id)
    if m is None or not _can_view_course(m.course):
        abort(404)
    return storage.download_response(m.storage_key, m.filename)


@bp.get("/assignments/<int:assignment_id>/brief")
def assignment_brief(assignment_id):
    a = db.session.get(Assignment, assignment_id)
    if a is None or not a.attachment_key or not _can_view_course(a.course):
        abort(404)
    return storage.download_response(a.attachment_key, a.attachment_name)


@bp.get("/submissions/<int:submission_id>")
def submission(submission_id):
    s = db.session.get(Submission, submission_id)
    if s is None:
        abort(404)
    is_owner = s.student_id == current_user.id
    is_course_teacher = current_user.is_teacher and s.assignment.course.teacher_id == current_user.id
    if not (is_owner or is_course_teacher):
        abort(404)
    return storage.download_response(s.storage_key, s.filename)
