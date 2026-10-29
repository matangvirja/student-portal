# Experimental Evaluation

Three experiments measure the properties the architecture claims: elasticity, availability during
deployments, and fault tolerance. Fill in the result tables from your own runs. The commands and
CloudWatch queries below collect every number.

**Environment (record yours):** region `ap-south-1`; task size 0.25 vCPU / 0.5 GB; gunicorn 2 workers × 4 threads;
RDS `db.t4g.micro`; Locust run from `<your machine / an EC2 instance in the same region>`.

---

## E1 · Elasticity under increasing load

**Hypothesis.** With a 50 % CPU target, the service scales out within ≈ 3–5 minutes of sustained load
and keeps p90 latency below 1 s once new tasks are healthy; it scales back to 2 tasks after the load stops.

**Method.**
1. Baseline: 2 tasks, no traffic for 10 minutes.
2. Run load in three steps (each 6 min) and save results:
   ```bash
   for u in 50 100 150; do
     locust -f loadtest/locustfile.py --host "$URL" --headless -u $u -r 10 -t 6m --csv results/e1-u$u
   done
   ```
3. Stop the load and observe for 20 minutes.
4. Export the scaling timeline:
   ```bash
   aws application-autoscaling describe-scaling-activities --service-namespace ecs \
     --query "ScalingActivities[].[StartTime,StatusCode,Description]" --output table
   ```

**Metrics.** CloudWatch dashboard `student-portal-dashboard`: Service CPU %, RunningTaskCount, RequestCount,
TargetResponseTime p90. Locust CSV: requests/s, failure %, p50/p95.

**Results.**

| Phase | Users | Req/s | Avg CPU % | Running tasks | p50 (ms) | p95 (ms) | Errors % |
|---|---|---|---|---|---|---|---|
| Baseline | 0 | | | 2 | | | |
| Step 1 | 50 | | | | | | |
| Step 2 | 100 | | | | | | |
| Step 3 | 150 | | | | | | |
| Cool-down (+20 min) | 0 | | | | | | |

| Event | Time from load start |
|---|---|
| CPU crosses 50 % | |
| First scale-out activity | |
| New task healthy in target group | |
| Max tasks reached | |
| Scale-in back to 2 (after load stop) | |

**Discussion prompts.** Why is scale-in slower than scale-out (cooldowns, alarm evaluation periods)? What
limited throughput at max tasks: task CPU, RDS CPU, or the load generator itself?

---

## E2 · Availability during a deployment

**Hypothesis.** A rolling deployment with `minimumHealthyPercent = 100` serves traffic with 0 % errors.

**Method.** Run constant light load (`-u 30 -t 15m`), push a commit, and let the pipeline deploy.

```bash
# ALB 5xx during the deploy window
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name HTTPCode_Target_5XX_Count \
  --dimensions Name=LoadBalancer,Value=<LoadBalancerFullName> --statistics Sum --period 60 \
  --start-time <start> --end-time <end>
```

| Metric | Value |
|---|---|
| Pipeline duration (push → deploy complete) | |
| Requests during deploy window | |
| Failed requests (Locust) | |
| ALB target 5xx | |

---

## E3 · Fault tolerance (task failure)

**Method.** Under light load, stop one running task in the ECS console (or
`aws ecs stop-task --cluster student-portal-cluster --task <id>`), and record the time until the
replacement passes health checks.

| Metric | Value |
|---|---|
| Time to replacement task RUNNING | |
| Time to replacement HEALTHY in target group | |
| Failed requests during the event | |

---

## Useful CloudWatch Logs Insights queries

Log group `/ecs/student-portal` (each line is JSON):

```sql
-- Latency percentiles per endpoint
fields path, duration_ms
| filter event = "http_request"
| stats count() as requests, pct(duration_ms, 50) as p50, pct(duration_ms, 95) as p95 by path
| sort requests desc

-- Server errors with request IDs
fields @timestamp, request_id, method, path, status
| filter event = "http_request" and status >= 500

-- Requests per task (shows load balancing)
fields @logStream
| filter event = "http_request"
| stats count() by @logStream

-- Audit trail: grade changes
fields @timestamp, user_id, msg
| filter event = "audit" and action = "grade"
```
