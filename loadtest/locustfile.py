"""Load test that pushes the ECS service past its CPU target so auto scaling kicks in.

    pip install locust
    locust -f loadtest/locustfile.py --host http://<your-alb-dns>
    # open http://localhost:8089, start with ~100 users, spawn rate 10

Headless, with a CSV of results for the experiment report (docs/experiments.md):
    locust -f loadtest/locustfile.py --host http://<alb> --headless -u 150 -r 10 -t 12m \
           --csv results/run1 --html results/run1.html

Optional: JOIN_CODE=<course code> makes the virtual students enrol in a course, so their
dashboards query real assignments (closer to production traffic).
"""
import os
import re
import uuid

from locust import HttpUser, between, task

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
JOIN_CODE = os.environ.get("JOIN_CODE", "")


def csrf_from(response) -> str:
    match = CSRF_RE.search(response.text)
    return match.group(1) if match else ""


class Student(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        uid = uuid.uuid4().hex[:10]
        page = self.client.get("/signup", name="/signup [GET]")
        self.client.post("/signup", name="/signup [POST]", data={
            "csrf_token": csrf_from(page), "role": "student", "name": "Load Tester",
            "email": f"load-{uid}@loadtest.local", "roll_number": f"LT{uid.upper()}",
            "password": "loadtest-pass-123",
        })
        if JOIN_CODE:
            home = self.client.get("/student/", name="/student/")
            self.client.post("/student/join", name="/student/join",
                             data={"csrf_token": csrf_from(home), "join_code": JOIN_CODE})

    @task(4)
    def cpu_heavy_request(self):
        # Simulates an expensive request (report generation, PDF rendering) to drive CPU up.
        self.client.get("/load?ms=150", name="/load")

    @task(3)
    def dashboard(self):
        self.client.get("/student/", name="/student/")

    @task(1)
    def grades(self):
        self.client.get("/student/grades", name="/student/grades")
