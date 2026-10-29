# Test Plan and Traceability

## 1. Automated tests (run in every pipeline execution)

`python -m pytest -q` (33 tests, ≈ 10 s). They run inside the Docker `test` stage, so a failure
stops CodeBuild and nothing is deployed.

| Requirement | Test(s) in `tests/test_app.py` |
|---|---|
| FR1 Student signup with roll number | `test_student_signup_lands_in_student_hub`, `test_student_signup_requires_roll_number` |
| FR2 Faculty signup gated by access code | `test_teacher_signup_lands_in_faculty_console`, `test_teacher_signup_requires_valid_faculty_code` |
| FR3 Password policy and hashing | `test_weak_password_rejected`, `test_password_is_hashed` |
| FR4 Role-based landing after login | `test_login_routes_by_role_and_wrong_password` |
| FR5 Course creation and join codes | `test_join_course_with_code`, `test_bad_join_code`, `test_regenerated_join_code_invalidates_old_one` |
| FR6 Materials shared with enrolled students | `test_material_shared_with_enrolled_student` |
| FR7 Submission, resubmission, lock after grading | `test_submit_grade_and_see_feedback`, `test_resubmission_replaces_file_until_graded` |
| FR8 Late submissions flagged | `test_late_submission_is_flagged` |
| FR9 Grading validation | `test_marks_out_of_range_rejected`, `test_due_date_must_be_in_future` |
| FR10 Gradebook export | `test_gradebook_csv_and_formula_injection_guard` |
| FR11 Dashboards and analytics | `test_analytics_and_dashboards_render` |
| SR1 Anonymous users redirected | `test_anonymous_is_sent_to_login` |
| SR2 Role isolation | `test_student_cannot_use_faculty_console`, `test_teacher_cannot_use_student_hub` |
| SR3 Object-level authorization (IDOR) | `test_students_cannot_download_each_others_work`, `test_other_teacher_cannot_touch_my_course`, `test_non_enrolled_student_cannot_see_course` |
| SR4 Open redirect | `test_open_redirect_blocked` |
| SR5 Upload allow-list | `test_disallowed_file_type_rejected` |
| SR6 Audit trail | `test_grading_is_audit_logged`, `test_teacher_signup_requires_valid_faculty_code` |
| SR7 Security headers / tracing | `test_security_headers_and_request_id` |
| OR1 Health checks | `test_health_endpoints` |
| OR2 Demo endpoints | `test_load_and_server_endpoints` |
| OR3 Demo data | `test_seed_demo_command` |

## 2. Infrastructure checks

| Check | Command | Expected |
|---|---|---|
| Template lint | `cfn-lint infra/*.yaml` | no errors |
| Stack outputs | `aws cloudformation describe-stacks --stack-name student-portal-infra` | `AppUrl`, `DashboardUrl` present |
| Targets healthy | EC2 → Target groups → Targets | 2 healthy targets in 2 AZs |
| DB reachability | `curl <AppUrl>/health/db` | `{"status":"ok"}` |

## 3. Manual acceptance tests (demo checklist)

| # | Scenario | Steps | Expected |
|---|---|---|---|
| A1 | Faculty journey | Sign in as `meera.shah@demo.portal` → open CS612 → publish assignment → grade a submission | Grade visible to the student with feedback |
| A2 | Student journey | Sign in as a demo student → join with code → submit file → view grades | Status changes Pending → Submitted → Graded |
| A3 | Role isolation | As a student, open `/teacher/` | 403 page |
| A4 | CI/CD | Change a heading, push | Pipeline green; new version live with no failed requests |
| A5 | Failed build | Break a test, push | Build stage fails; site unchanged |
| A6 | Load balancing | `./scripts/show-load-balancing.sh` | Responses from ≥ 2 task IDs and 2 AZs |
| A7 | Auto scaling | Run Locust (docs/experiments.md) | Desired count rises above 2, returns to 2 after load stops |
| A8 | Self-healing | Stop one task in the console | Replacement task starts; no 5xx at the ALB |
