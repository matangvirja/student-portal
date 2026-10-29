# Architecture Decision Records

Each record states the context, the decision, the alternatives considered and the consequences.

---

## ADR-001 · Containers on ECS Fargate instead of EC2 Auto Scaling Groups or Elastic Beanstalk

**Context.** The web tier must scale horizontally and be redeployed many times a day by a pipeline.

**Decision.** Package the app as a Docker image and run it on ECS with the Fargate launch type.

**Alternatives.**
- *EC2 + Auto Scaling Group + AMI baking*: full control, but slow scale-out (instance boot ≈ 2–4 min), and the team must patch the OS.
- *Elastic Beanstalk*: quick to start, but hides the networking and scaling primitives this project is meant to demonstrate.
- *EKS (Kubernetes)*: powerful, but the control plane alone costs ≈ USD 73/month, and it adds operational complexity unjustified for one service.

**Consequences.** Tasks start in ≈ 30–60 s; no servers to patch; per-task billing. Trade-off: less control over the host and a higher price per vCPU than EC2 at sustained high utilisation.

---

## ADR-002 · Target-tracking auto scaling on two signals

**Context.** Load is bursty (deadline nights). Scaling should react quickly to bursts and avoid flapping.

**Decision.** Two target-tracking policies on the ECS service: average CPU = 50 % and `ALBRequestCountPerTarget` = 1000/min. Min 2 tasks, max 6. Scale-out cooldown 60 s, scale-in cooldown 120 s.

**Rationale.** CPU captures compute-heavy requests; requests-per-target captures I/O-bound surges where CPU stays low. Application Auto Scaling scales out if **either** policy asks for it and scales in only when **both** agree, which is a conservative combination. A 50 % CPU target leaves headroom for the ≈ 1 minute it takes a new task to become healthy.

**Alternatives.** Step scaling (more tuning, easy to get wrong); scheduled scaling (good for known deadlines and can be added on top); predictive scaling (needs history).

---

## ADR-003 · Stateless application tier

**Decision.** No state on the task's disk or in memory between requests:
- sessions: signed cookies with a **shared** `SECRET_KEY` from Secrets Manager;
- files: S3; metadata: RDS.

**Consequences.** Any task can serve any request, so the ALB needs no stickiness, tasks can be killed by scale-in or deployments at any time, and the circuit breaker can replace them freely. Trade-off: session revocation requires rotating the key (logs everyone out); a server-side session store (ElastiCache) would allow per-user revocation.

---

## ADR-004 · Tasks in public subnets with locked-down security groups (no NAT Gateway)

**Context.** Tasks need outbound access to ECR, S3 and Secrets Manager. A NAT Gateway costs ≈ USD 32/month plus data, which is significant for a student budget.

**Decision.** Run tasks in public subnets with public IPs; the security group accepts **only** traffic from the ALB security group on port 5000. The database stays in private subnets with no internet route.

**Production alternative.** Private subnets + NAT Gateway, or private subnets + VPC interface endpoints for ECR/Secrets Manager/CloudWatch and a gateway endpoint for S3 (removes internet egress entirely).

---

## ADR-005 · Presigned S3 URLs for downloads

**Decision.** Downloads redirect the browser to a 5-minute presigned `GET` URL after the app has checked authorization.

**Consequences.** Large files never pass through the app containers, so they consume no task CPU, memory or ALB bandwidth. The bucket stays private. Trade-off: a URL is shareable for 5 minutes once issued, which is acceptable for course work.

---

## ADR-006 · Relational database (PostgreSQL) instead of DynamoDB

**Context.** The data is highly relational (courses ↔ enrolments ↔ assignments ↔ submissions), and faculty need ad-hoc aggregation (gradebooks, analytics, at-risk detection).

**Decision.** RDS for PostgreSQL with uniqueness constraints in the schema.

**Trade-off.** RDS is a single-writer instance (Single-AZ here for cost; Multi-AZ is one parameter away). DynamoDB would scale writes further but would need the access patterns designed up front and would push joins into application code.

---

## ADR-007 · Schema creation with `db.create_all()` (no migrations yet)

**Decision.** Tables are created on start-up if missing. `create_all` is idempotent and safe when several tasks start together (errors are caught and logged).

**Limitation.** It does not alter existing tables. The next step is Alembic (Flask-Migrate) run as a **one-off ECS task** before the deploy stage, the same pattern used by `scripts/seed-demo.sh`, rather than on every container start, to avoid concurrent migrations.

---

## ADR-008 · Rolling deployments with circuit breaker instead of blue/green

**Decision.** ECS rolling update (`minimumHealthyPercent 100`, `maximumPercent 200`) with the deployment circuit breaker and automatic rollback.

**Alternative.** CodeDeploy blue/green with a test listener and traffic shifting (canary/linear). It allows instant rollback and pre-traffic tests, but needs a second target group, listener and CodeDeploy application. Listed as future work.

---

## ADR-009 · Faculty accounts gated by an access code

**Context.** Self-service signup must not let a student register as faculty.

**Decision.** Faculty signup requires a department access code stored in Secrets Manager and compared in constant time (`hmac.compare_digest`). Rejected attempts are audit-logged.

**Future work.** Replace with SSO (Amazon Cognito federated with the institute's identity provider) and role claims from a directory group.
