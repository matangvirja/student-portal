"""`flask seed-demo` — fills the portal with a realistic demo semester for presentations.

Locally:   flask --app wsgi seed-demo
On AWS:    ./scripts/seed-demo.sh   (runs this command as a one-off ECS task)
"""
import io
import random
from datetime import timedelta

import click
from sqlalchemy import select

from . import storage
from .extensions import db
from .models import Assignment, Course, Enrollment, Material, Role, Submission, User, new_join_code
from .timeutil import utcnow
from .uploads import build_key

TEACHER = ("Dr. Meera Shah", "meera.shah@demo.portal", "Computer Engineering")
TEACHER_2 = ("Prof. Arvind Rao", "arvind.rao@demo.portal", "Information Technology")
STUDENTS = [
    ("Aarav Mehta", "24MCS001"), ("Diya Patel", "24MCS002"), ("Kabir Joshi", "24MCS003"),
    ("Ananya Iyer", "24MCS004"), ("Rohan Desai", "24MCS005"), ("Isha Trivedi", "24MCS006"),
    ("Vivaan Nair", "24MCS007"), ("Saanvi Kulkarni", "24MCS008"),
]
FEEDBACK = [
    "Clear structure and good use of diagrams. Cite your sources for the cost figures.",
    "Solid work. The failure-scenario section needs more depth.",
    "Good analysis, but the conclusion doesn't follow from your measurements.",
    "Excellent: well-argued trade-offs and a reproducible setup.",
    "Covers the basics; compare at least two alternatives next time.",
]


def _put_text(key: str, text: str) -> int:
    data = text.encode()
    storage.save(io.BytesIO(data), key, "text/plain")
    return len(data)


def register_cli(app):
    @app.cli.command("seed-demo")
    @click.option("--password", default="Demo@2026", show_default=True, help="Password for every demo account")
    def seed_demo(password):
        """Create demo faculty, students, courses, assignments, submissions and grades."""
        if db.session.scalar(select(User.id).filter_by(email=TEACHER[1])):
            click.echo("Demo data already exists; nothing to do.")
            return

        rng = random.Random(2026)
        now = utcnow()

        def make_user(name, email, role, dept, roll=None):
            u = User(name=name, email=email, role=role, department=dept, roll_number=roll)
            u.set_password(password)
            db.session.add(u)
            return u

        meera = make_user(*TEACHER[:2], Role.TEACHER, TEACHER[2])
        arvind = make_user(*TEACHER_2[:2], Role.TEACHER, TEACHER_2[2])
        students = [make_user(n, f"{n.split()[0].lower()}.{roll.lower()}@demo.portal", Role.STUDENT,
                              "M.Tech CSE", roll) for n, roll in STUDENTS]
        db.session.flush()

        cloud = Course(code="CS612", title="Cloud Computing", semester="Sem 1 · 2026-27", teacher_id=meera.id,
                       join_code=new_join_code(),
                       description="Virtualisation, IaaS/PaaS/SaaS, elasticity, distributed storage, "
                                   "cloud-native design and DevOps on AWS.")
        security = Course(code="CS604", title="Advanced Information Security", semester="Sem 1 · 2026-27",
                          teacher_id=meera.id, join_code=new_join_code(),
                          description="Threat modelling, applied cryptography, IAM and secure software design.")
        dist = Course(code="IT621", title="Distributed Systems", semester="Sem 1 · 2026-27", teacher_id=arvind.id,
                      join_code=new_join_code(),
                      description="Consistency models, consensus, replication and fault tolerance.")
        db.session.add_all([cloud, security, dist])
        db.session.flush()

        for s in students:
            db.session.add(Enrollment(course_id=cloud.id, student_id=s.id, joined_at=now - timedelta(days=40)))
        for s in students[:5]:
            db.session.add(Enrollment(course_id=security.id, student_id=s.id, joined_at=now - timedelta(days=38)))
        for s in students[2:7]:
            db.session.add(Enrollment(course_id=dist.id, student_id=s.id, joined_at=now - timedelta(days=35)))

        for course, title in [(cloud, "Lecture 01 - Cloud service and deployment models"),
                              (cloud, "Lecture 02 - Elasticity and auto scaling"),
                              (cloud, "Lab manual - Deploying containers on ECS Fargate"),
                              (security, "Lecture 01 - STRIDE threat modelling"),
                              (dist, "Lecture 01 - Time, clocks and ordering of events")]:
            fname = title.split(" - ")[0].lower().replace(" ", "-") + ".txt"
            key = build_key(f"courses/{course.id}/materials", fname)
            size = _put_text(key, f"{course.code} {title}\n\n(Demo material.)\n")
            db.session.add(Material(course_id=course.id, title=title, filename=fname, storage_key=key,
                                    content_type="text/plain", size_bytes=size,
                                    uploaded_at=now - timedelta(days=rng.randint(5, 35))))

        plan = [  # course, title, days from now (negative = past), max marks, graded fraction
            (cloud, "A1: IaaS vs PaaS case study", -24, 20, 1.0),
            (cloud, "Quiz 1: Virtualisation and containers", -16, 10, 1.0),
            (cloud, "A2: Highly available 3-tier architecture on AWS", -9, 30, 0.6),
            (cloud, "A3: Auto scaling experiment report", 6, 50, 0),
            (cloud, "Mini project proposal", 15, 10, 0),
            (security, "Threat model of a student portal (STRIDE)", -5, 25, 0.8),
            (security, "Lab: TLS configuration audit", 3, 15, 0),
            (dist, "Lamport clocks implementation", -12, 40, 1.0),
            (dist, "Raft leader election simulation", 9, 50, 0),
        ]
        # Per-student profile so the analytics look like a real class: most students are
        # reliable, one is struggling (shows up in "students who may need support").
        # (ability, chance of missing, chance of submitting late)
        profile = {s.id: (rng.uniform(0.62, 0.95), 0.06, 0.08) for s in students}
        profile[students[4].id] = (0.74, 0.05, 0.6)   # Rohan: good work, often late
        profile[students[5].id] = (0.33, 0.55, 0.5)   # Isha: low scores, misses deadlines

        for course, title, days, max_marks, graded_fraction in plan:
            due = (now + timedelta(days=days)).replace(hour=17, minute=59, second=0, microsecond=0)
            a = Assignment(course_id=course.id, title=title, due_at=due, max_marks=max_marks,
                           created_at=due - timedelta(days=14),
                           description="Submit a single PDF or ZIP. Follow the report template shared in "
                                       "the course materials. Plagiarism is checked.")
            db.session.add(a)
            db.session.flush()
            roster = [e.student for e in course.enrollments]
            if days > 0:
                # Open assignment: a couple of early submissions (not from the first demo student,
                # so their dashboard has pending work to show).
                for s in roster[-2:]:
                    _add_submission(a, s, now - timedelta(hours=rng.randint(3, 40)), rng)
                continue
            for s in roster:
                ability, miss_chance, late_chance = profile[s.id]
                if rng.random() < miss_chance:
                    continue  # missing
                if rng.random() < late_chance:
                    submitted = due + timedelta(hours=rng.randint(2, 30))  # late
                else:
                    submitted = due - timedelta(hours=rng.randint(1, 72))
                sub = _add_submission(a, s, submitted, rng)
                if rng.random() < graded_fraction:
                    score = min(max(ability + rng.uniform(-0.1, 0.08), 0.15), 1.0)
                    sub.marks = round(max_marks * score * 2) / 2
                    sub.feedback = rng.choice(FEEDBACK)
                    sub.graded_at = due + timedelta(days=rng.randint(2, 5))

        db.session.commit()
        click.echo("Demo data created. Every account's password: " + password)
        click.echo(f"  Faculty : {TEACHER[1]}  (courses CS612, CS604)")
        click.echo(f"  Faculty : {TEACHER_2[1]}  (course IT621)")
        click.echo(f"  Student : {students[0].email}")
        click.echo(f"  Join codes: CS612={cloud.join_code}  CS604={security.join_code}  IT621={dist.join_code}")


def _add_submission(assignment, student, submitted_at, rng):
    fname = f"{student.roll_number}_{assignment.title.split(':')[0].replace(' ', '_')}.txt"
    key = build_key(f"courses/{assignment.course_id}/assignments/{assignment.id}/submissions/{student.id}", fname)
    size = _put_text(key, f"Submission by {student.name} ({student.roll_number}) for {assignment.title}\n")
    sub = Submission(assignment_id=assignment.id, student_id=student.id, filename=fname, storage_key=key,
                     content_type="text/plain", size_bytes=size, submitted_at=submitted_at)
    db.session.add(sub)
    return sub
