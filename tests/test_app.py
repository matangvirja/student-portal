"""Functional and security tests. Run with:  python -m pytest -q

Grouped by requirement: authentication, role-based access control, course workflow,
grading, object-level authorization, and operational endpoints.
"""
from app.extensions import db
from app.models import AuditLog, Submission, User
from conftest import (PASSWORD, create_course, join_code, move_deadline, publish_assignment, signup_student,
                      signup_teacher, upload)


# ---------------------------------------------------------------- authentication

def test_landing_page(client):
    r = client.get("/")
    assert r.status_code == 200 and b"For faculty" in r.data and b"For students" in r.data


def test_student_signup_lands_in_student_hub(client):
    r = signup_student(client)
    assert r.status_code == 200
    assert b"Join a course" in r.data


def test_teacher_signup_lands_in_faculty_console(client):
    r = signup_teacher(client)
    assert b"Faculty Console" in r.data


def test_teacher_signup_requires_valid_faculty_code(app, client):
    r = signup_teacher(client, code="wrong-code")
    assert r.status_code == 400
    with app.app_context():
        assert db.session.query(User).count() == 0
        assert db.session.query(AuditLog).filter_by(action="signup_rejected").count() == 1


def test_student_signup_requires_roll_number(client):
    r = client.post("/signup", data={"role": "student", "name": "A", "email": "a@x.com", "password": PASSWORD})
    assert r.status_code == 400


def test_weak_password_rejected(client):
    r = client.post("/signup", data={"role": "student", "name": "A", "email": "a@x.com",
                                     "password": "password", "roll_number": "24MCS009"})
    assert r.status_code == 400


def test_duplicate_email_rejected(client):
    signup_student(client)
    client.post("/logout")
    assert signup_student(client, roll="24MCS099").status_code == 400


def test_login_routes_by_role_and_wrong_password(client):
    signup_teacher(client)
    client.post("/logout")
    r = client.post("/login", data={"email": "prof@example.com", "password": "nope-123"})
    assert r.status_code == 401
    r = client.post("/login", data={"email": "prof@example.com", "password": PASSWORD})
    assert r.headers["Location"].endswith("/teacher/")


def test_open_redirect_blocked(client):
    signup_student(client)
    client.post("/logout")
    r = client.post("/login?next=//evil.example.com", data={"email": "asha@example.com", "password": PASSWORD})
    assert r.headers["Location"].endswith("/student/")


def test_password_is_hashed(app, client):
    signup_student(client)
    with app.app_context():
        user = db.session.query(User).one()
        assert PASSWORD not in user.password_hash


# ---------------------------------------------------------------- role-based access control

def test_anonymous_is_sent_to_login(client):
    for path in ("/teacher/", "/student/", "/files/submissions/1"):
        r = client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_student_cannot_use_faculty_console(client):
    signup_student(client)
    assert client.get("/teacher/").status_code == 403
    assert client.post("/teacher/courses/new", data={"code": "X1", "title": "Hack"}).status_code == 403


def test_teacher_cannot_use_student_hub(client):
    signup_teacher(client)
    assert client.get("/student/").status_code == 403
    assert client.post("/student/join", data={"join_code": "ABCDEF"}).status_code == 403


# ---------------------------------------------------------------- course workflow

def test_join_course_with_code(app, classroom):
    r = classroom["student"].get(f"/student/courses/{classroom['course_id']}")
    assert r.status_code == 200 and b"Cloud Computing" in r.data


def test_bad_join_code(client):
    signup_student(client)
    r = client.post("/student/join", data={"join_code": "ZZZZZZ"}, follow_redirects=True)
    assert b"No course matches" in r.data


def test_regenerated_join_code_invalidates_old_one(app, classroom):
    old = join_code(app, classroom["course_id"])
    classroom["teacher"].post(f"/teacher/courses/{classroom['course_id']}/join-code")
    assert join_code(app, classroom["course_id"]) != old


def test_non_enrolled_student_cannot_see_course(app, classroom):
    other = app.test_client()
    signup_student(other, email="ravi@example.com", roll="24MCS050")
    assert other.get(f"/student/courses/{classroom['course_id']}").status_code == 404
    assert other.get(f"/student/assignments/{classroom['assignment_id']}").status_code == 404


def test_due_date_must_be_in_future(classroom):
    r = classroom["teacher"].post(f"/teacher/courses/{classroom['course_id']}/assignments",
                                  data={"title": "Old", "due_at": "2001-01-01T10:00", "max_marks": "10"},
                                  follow_redirects=True)
    assert b"must be in the future" in r.data


def test_material_shared_with_enrolled_student(classroom):
    upload(classroom["teacher"], f"/teacher/courses/{classroom['course_id']}/materials",
           content=b"lecture notes", filename="lecture1.pdf", extra={"title": "Lecture 1"})
    page = classroom["student"].get(f"/student/courses/{classroom['course_id']}")
    assert b"Lecture 1" in page.data
    r = classroom["student"].get("/files/materials/1")
    assert r.data == b"lecture notes"
    r.close()


# ---------------------------------------------------------------- submission & grading

def test_submit_grade_and_see_feedback(app, classroom):
    s, t, aid = classroom["student"], classroom["teacher"], classroom["assignment_id"]
    r = upload(s, f"/student/assignments/{aid}/submit")
    assert b"answer.pdf" in r.data

    t.post("/teacher/submissions/1/grade", data={"marks": "17.5", "feedback": "Well argued."})
    r = s.get(f"/student/assignments/{aid}")
    assert b"17.5" in r.data and b"Well argued." in r.data
    assert b"Graded work is locked" in r.data


def test_resubmission_replaces_file_until_graded(app, classroom):
    s, t, aid = classroom["student"], classroom["teacher"], classroom["assignment_id"]
    upload(s, f"/student/assignments/{aid}/submit", content=b"v1", filename="v1.pdf")
    upload(s, f"/student/assignments/{aid}/submit", content=b"v2", filename="v2.pdf")
    with app.app_context():
        sub = db.session.query(Submission).one()
        assert sub.filename == "v2.pdf"
    t.post("/teacher/submissions/1/grade", data={"marks": "10"})
    r = upload(s, f"/student/assignments/{aid}/submit", content=b"v3", filename="v3.pdf")
    assert b"already been graded" in r.data


def test_late_submission_is_flagged(app, classroom):
    aid = classroom["assignment_id"]
    move_deadline(app, aid, days=-1)
    r = upload(classroom["student"], f"/student/assignments/{aid}/submit")
    assert b"marked late" in r.data
    with app.app_context():
        assert db.session.query(Submission).one().is_late


def test_marks_out_of_range_rejected(app, classroom):
    upload(classroom["student"], f"/student/assignments/{classroom['assignment_id']}/submit")
    for bad in ("25", "-1", "nan", "abc"):
        classroom["teacher"].post("/teacher/submissions/1/grade", data={"marks": bad})
    with app.app_context():
        assert db.session.query(Submission).one().marks is None


def test_grading_is_audit_logged(app, classroom):
    upload(classroom["student"], f"/student/assignments/{classroom['assignment_id']}/submit")
    classroom["teacher"].post("/teacher/submissions/1/grade", data={"marks": "12"})
    with app.app_context():
        entry = db.session.query(AuditLog).filter_by(action="grade").one()
        assert "12.0/20" in entry.detail


def test_disallowed_file_type_rejected(app, classroom):
    r = upload(classroom["student"], f"/student/assignments/{classroom['assignment_id']}/submit", filename="evil.exe")
    assert b"isn&#39;t allowed" in r.data
    with app.app_context():
        assert db.session.query(Submission).count() == 0


# ---------------------------------------------------------------- object-level authorization

def test_students_cannot_download_each_others_work(app, classroom):
    upload(classroom["student"], f"/student/assignments/{classroom['assignment_id']}/submit")
    peer = app.test_client()
    signup_student(peer, email="peer@example.com", roll="24MCS002")
    peer.post("/student/join", data={"join_code": join_code(app, classroom["course_id"])})
    assert peer.get("/files/submissions/1").status_code == 404


def test_other_teacher_cannot_touch_my_course(app, classroom):
    upload(classroom["student"], f"/student/assignments/{classroom['assignment_id']}/submit")
    other = app.test_client()
    signup_teacher(other, email="other@example.com")
    assert other.get(f"/teacher/courses/{classroom['course_id']}").status_code == 404
    assert other.post("/teacher/submissions/1/grade", data={"marks": "1"}).status_code == 404
    assert other.get("/files/submissions/1").status_code == 404
    assert other.get(f"/teacher/courses/{classroom['course_id']}/gradebook.csv").status_code == 404


# ---------------------------------------------------------------- reports

def test_gradebook_csv_and_formula_injection_guard(app):
    teacher, student = app.test_client(), app.test_client()
    signup_teacher(teacher)
    course_id = create_course(teacher)
    aid = publish_assignment(teacher, course_id, max_marks=10)
    signup_student(student, name="=HYPERLINK(evil)")
    student.post("/student/join", data={"join_code": join_code(app, course_id)})
    upload(student, f"/student/assignments/{aid}/submit")
    teacher.post("/teacher/submissions/1/grade", data={"marks": "8"})

    r = teacher.get(f"/teacher/courses/{course_id}/gradebook.csv")
    text = r.data.decode()
    assert r.mimetype == "text/csv"
    assert "'=HYPERLINK(evil)" in text
    assert ",8,8,10,80.0" in text


def test_analytics_and_dashboards_render(classroom):
    upload(classroom["student"], f"/student/assignments/{classroom['assignment_id']}/submit")
    assert classroom["teacher"].get("/teacher/").status_code == 200
    assert classroom["teacher"].get("/teacher/analytics").status_code == 200
    assert classroom["teacher"].get(f"/teacher/assignments/{classroom['assignment_id']}").status_code == 200
    for tab in ("assignments", "materials", "students"):
        assert classroom["teacher"].get(f"/teacher/courses/{classroom['course_id']}?tab={tab}").status_code == 200
    assert classroom["student"].get("/student/").status_code == 200
    assert classroom["student"].get("/student/grades").status_code == 200


# ---------------------------------------------------------------- operations

def test_health_endpoints(client):
    assert client.get("/health").get_json()["status"] == "ok"
    assert client.get("/health/db").status_code == 200


def test_load_and_server_endpoints(client):
    assert client.get("/load?ms=5").status_code == 200
    assert "hostname" in client.get("/api/server").get_json()


def test_security_headers_and_request_id(client):
    r = client.get("/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Request-ID"]


def test_seed_demo_command(app):
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert "Demo data created" in result.output, result.output
    with app.app_context():
        assert db.session.query(User).filter_by(role="teacher").count() == 2
        assert db.session.query(Submission).count() > 20
    again = app.test_cli_runner().invoke(args=["seed-demo"])
    assert "already exists" in again.output
