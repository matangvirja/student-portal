"""Domain model.

    User (role = teacher | student)
      ├─ teaches ──> Course ──< Assignment ──< Submission >── User (student)
      │                 ├────< Material
      └─ enrolls ─< Enrollment >─┘
    AuditLog records security-relevant actions (login, grading, exports...).

Metadata lives in RDS PostgreSQL; file bytes live in S3 under structured prefixes:
    courses/<course_id>/materials/...
    courses/<course_id>/assignments/<assignment_id>/brief/...
    courses/<course_id>/assignments/<assignment_id>/submissions/<student_id>/...
"""
import secrets

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint, select
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .timeutil import as_utc, utcnow


class Role:
    STUDENT = "student"
    TEACHER = "teacher"
    ALL = (STUDENT, TEACHER)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default=Role.STUDENT, index=True)
    department = db.Column(db.String(120))
    roll_number = db.Column(db.String(32), unique=True)  # students only
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    courses_taught = db.relationship("Course", back_populates="teacher", order_by="Course.code")
    enrollments = db.relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")

    @property
    def is_teacher(self) -> bool:
        return self.role == Role.TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == Role.STUDENT

    @property
    def first_name(self) -> str:
        parts = self.name.replace("Dr.", "").replace("Prof.", "").split()
        return parts[0] if parts else self.name

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.replace("Dr.", "").replace("Prof.", "").split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I confusion


def new_join_code(length: int = 6) -> str:
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(length))


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    semester = db.Column(db.String(40))
    description = db.Column(db.Text)
    join_code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    teacher = db.relationship("User", back_populates="courses_taught")
    enrollments = db.relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")
    assignments = db.relationship("Assignment", back_populates="course", cascade="all, delete-orphan",
                                  order_by="Assignment.due_at")
    materials = db.relationship("Material", back_populates="course", cascade="all, delete-orphan",
                                order_by="Material.uploaded_at.desc()")

    def has_student(self, user_id: int) -> bool:
        return db.session.scalar(
            select(Enrollment.id).filter_by(course_id=self.id, student_id=user_id)
        ) is not None

    @property
    def roster(self):
        return sorted((e.student for e in self.enrollments), key=lambda u: u.name.lower())


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_enrollment"),)

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    joined_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    course = db.relationship("Course", back_populates="enrollments")
    student = db.relationship("User", back_populates="enrollments")


class Material(db.Model):
    """Lecture notes, slides, reading lists uploaded by the teacher."""

    __tablename__ = "materials"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(512), unique=True, nullable=False)
    content_type = db.Column(db.String(255))
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    course = db.relationship("Course", back_populates="materials")


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    due_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    max_marks = db.Column(db.Integer, nullable=False, default=100)
    attachment_name = db.Column(db.String(255))
    attachment_key = db.Column(db.String(512))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    course = db.relationship("Course", back_populates="assignments")
    submissions = db.relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")

    @property
    def is_open(self) -> bool:
        return utcnow() <= as_utc(self.due_at)

    def submission_for(self, student_id: int):
        return db.session.scalar(select(Submission).filter_by(assignment_id=self.id, student_id=student_id))


class Submission(db.Model):
    """One row per (assignment, student). Re-submitting replaces the file until it is graded."""

    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_submission"),)

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(512), unique=True, nullable=False)
    content_type = db.Column(db.String(255))
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    submitted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    marks = db.Column(db.Float)
    feedback = db.Column(db.Text)
    graded_at = db.Column(db.DateTime(timezone=True))

    assignment = db.relationship("Assignment", back_populates="submissions")
    student = db.relationship("User")

    @property
    def is_late(self) -> bool:
        return as_utc(self.submitted_at) > as_utc(self.assignment.due_at)

    @property
    def is_graded(self) -> bool:
        return self.marks is not None

    @property
    def percent(self):
        if self.marks is None or not self.assignment.max_marks:
            return None
        return round(self.marks * 100 / self.assignment.max_marks, 1)


class AuditLog(db.Model):
    """Append-only trail of security-relevant actions (who did what, from where, when)."""

    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    detail = db.Column(db.String(500))
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)


def status_for(assignment: Assignment, submission):
    """(css_class, label) describing a student's status on an assignment."""
    if submission is None:
        return ("pending", "Pending") if assignment.is_open else ("overdue", "Overdue")
    if submission.is_graded:
        return ("graded", "Graded")
    if submission.is_late:
        return ("late", "Submitted late")
    return ("submitted", "Submitted")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
