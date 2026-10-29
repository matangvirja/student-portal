import io
from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Assignment
from app.timeutil import utcnow

TEACHER_CODE = "TEST-FACULTY-CODE"
PASSWORD = "password123"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "S3_BUCKET": None,
        "ENABLE_LOAD_ENDPOINT": True,
        "TEACHER_INVITE_CODE": TEACHER_CODE,
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def signup_student(client, email="asha@example.com", roll="24MCS001", name="Asha Rao"):
    return client.post("/signup", data={"role": "student", "name": name, "email": email,
                                        "password": PASSWORD, "roll_number": roll}, follow_redirects=True)


def signup_teacher(client, email="prof@example.com", name="Dr. Meera Shah", code=TEACHER_CODE):
    return client.post("/signup", data={"role": "teacher", "name": name, "email": email,
                                        "password": PASSWORD, "faculty_code": code}, follow_redirects=True)


def create_course(client, code="CS612", title="Cloud Computing"):
    r = client.post("/teacher/courses/new", data={"code": code, "title": title, "semester": "Sem 1"})
    assert r.status_code == 302, r.data
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def join_code(app, course_id):
    from app.models import Course
    with app.app_context():
        return db.session.get(Course, course_id).join_code


def publish_assignment(client, course_id, title="A1", max_marks=20, due_local="2099-01-01T17:00"):
    r = client.post(f"/teacher/courses/{course_id}/assignments",
                    data={"title": title, "description": "Do it", "due_at": due_local, "max_marks": str(max_marks)},
                    content_type="multipart/form-data")
    assert r.status_code == 302, r.data
    return int(r.headers["Location"].rstrip("/").split("/")[-1])


def upload(client, url, content=b"my answer", filename="answer.pdf", field="file", extra=None):
    data = {field: (io.BytesIO(content), filename)}
    data.update(extra or {})
    return client.post(url, data=data, content_type="multipart/form-data", follow_redirects=True)


def move_deadline(app, assignment_id, days):
    with app.app_context():
        a = db.session.get(Assignment, assignment_id)
        a.due_at = utcnow() + timedelta(days=days)
        db.session.commit()


@pytest.fixture
def classroom(app):
    """A teacher with one course and one assignment, and an enrolled student."""
    teacher, student = app.test_client(), app.test_client()
    signup_teacher(teacher)
    course_id = create_course(teacher)
    assignment_id = publish_assignment(teacher, course_id)
    signup_student(student)
    student.post("/student/join", data={"join_code": join_code(app, course_id)})
    return {"teacher": teacher, "student": student, "course_id": course_id, "assignment_id": assignment_id}
