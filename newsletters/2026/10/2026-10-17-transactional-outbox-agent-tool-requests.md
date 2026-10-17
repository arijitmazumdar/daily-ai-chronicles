---
date: 2026-10-17
title: "Transactional Outbox for Agent Tool Requests: Close the Dual-Write Gap"
topic: Agents
status: Draft
summary: "An agent can save a workflow decision and crash before dispatching the corresponding tool request, leaving the system inconsistent. The transactional outbox records both changes in one database transaction, then a separate relay delivers the request with at-least-once semantics and idempotent processing."
primary_source: "https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html"
---

# Transactional Outbox for Agent Tool Requests: Close the Dual-Write Gap

> **Daily AI Engineering Learning \| 17 October 2026 \| Agents \| Estimated reading time: 9 minutes**
> **Central lesson:** When an agent must persist a decision and trigger a downstream tool, commit the decision and an outgoing request together. Deliver that request asynchronously; design for duplicate delivery.
## Why this matters
Yesterday's lesson covered an uncertain outcome: a tool may succeed even though its response is lost. Today's problem is one step earlier. Imagine a MuleSoft-to-Spring Boot migration agent that completes parity tests, saves **READY_FOR_STAGING**, and then crashes before asking the deployment service to publish the generated API. The database says the migration is ready, but the deployment request never leaves the process.
This is the **dual-write problem**: a workflow tries to update two independent systems (its database and a message broker or external tool) without a shared transaction. Reversing the order is no safer: publishing first can trigger deployment even if saving the workflow state subsequently fails.
The **transactional outbox** makes the *intent to publish* durable. It does **not** guarantee that the remote deployment succeeds, and it does not remove the need for idempotency at the target.
## Mental model: an office dispatch tray
A clerk approves a document and puts a dispatch slip in the office's outgoing tray **as part of the same recorded action**. A courier later collects slips and delivers them. If the courier is delayed, the slips remain; if the courier loses the acknowledgment, the same slip might be delivered twice.
- **Outbox:** database table of durable messages awaiting delivery.
- **Atomic transaction:** a database commit in which all included changes happen or none do.
- **Relay:** worker that reads outbox entries and sends them to a broker or tool gateway.
- **At-least-once delivery:** a request is retried until acknowledged, so duplicates are possible.
- **Idempotent consumer:** a receiver that recognizes repeated event IDs and avoids duplicate business effects.
- **Inbox:** optional receiver-side table of already processed event IDs.
- **CDC (change data capture):** publishing database changes by reading the database change log instead of polling rows.
- **Reconciliation:** checking workflow, outbox, broker, and target state to identify stuck or uncertain operations.
**Rule of thumb:** the outbox prevents lost *intent*; target idempotency prevents repeated *effects*.
## Core components and request flow
```mermaid
sequenceDiagram
    participant A as Migration Agent
    participant D as Workflow Database
    participant R as Outbox Relay
    participant Q as Queue or Event Bus
    participant T as Deployment Tool
    A->>D: BEGIN; save READY + insert outbox event; COMMIT
    Note over A,D: One local transaction
    R->>D: Read pending outbox events
    R->>Q: Publish event with stable event_id
    Q-->>R: Broker acknowledgment
    R->>D: Mark event sent
    Q->>T: Deliver staging request
    T->>T: Check event_id / idempotency key
    T-->>Q: Acknowledge after safe processing
    Note over R,T: Relay crash after publish may cause a duplicate
```
1. The agent proposes a next action, but deterministic orchestration checks permissions, approval, and the validated migration state.
2. In **one database transaction**, persist the state transition and insert an outbox record containing a stable event ID, workflow ID, event type, schema version, and minimal payload.
3. A relay reads pending entries. A successful broker acknowledgment is required before it marks an entry delivered.
4. The broker or worker passes the event to the tool gateway. The receiver deduplicates by event ID; for external writes it also supplies a stable idempotency key supported by the target.
5. Track deployment status separately. An outbox row marked *sent* means the message reached the broker, **not** that deployment succeeded.
6. A reconciliation job alerts on old unsent rows, exhausted retries, missing target receipts, and events stuck in unknown status.
**Important boundary:** The outbox transaction only covers tables in the same transactional database. It cannot atomically commit an external HTTP request, Git push, or message broker write.
## Concrete example: migration parity test to staging deployment
An agent converts MuleSoft flow `customer-lookup` into a Spring Boot controller and runs parity tests. When tests pass, the workflow database stores `mig-42 = READY_FOR_STAGING` and an outbox event:
```json
{
  "event_id": "mig-42:staging-request:v3",
  "event_type": "StagingDeploymentRequested",
  "schema_version": 1,
  "migration_id": "mig-42",
  "artifact": "customer-lookup:revision-3"
}
```
A relay publishes the event. The staging deployment worker handles it with the event ID as an idempotency key. If the relay publishes twice after a crash, the deployment worker must not create two deployments. The workflow advances to `DEPLOYED` only when it receives a verified deployment result—not when the outbox row is sent.
## Python: a runnable crash-and-retry demonstration
This standard-library simulation uses SQLite as one transactional database and a Python list as a pretend broker. It deliberately crashes **after** broker publication but **before** the outbox row is marked sent, demonstrating duplicate delivery and consumer deduplication.
```python
import json
import sqlite3

db = sqlite3.connect(":memory:", isolation_level=None)
db.executescript("""
CREATE TABLE migrations (
  id TEXT PRIMARY KEY, state TEXT NOT NULL, artifact TEXT NOT NULL
);
CREATE TABLE outbox (
  event_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
  sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE inbox (event_id TEXT PRIMARY KEY);
CREATE TABLE deployments (
  migration_id TEXT PRIMARY KEY, artifact TEXT NOT NULL
);
""")
broker = []  # demo only; use a durable broker in production

def record_ready(migration_id, artifact, event_id):
    payload = json.dumps({
        "event_id": event_id,
        "migration_id": migration_id,
        "artifact": artifact
    })
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("INSERT INTO migrations VALUES (?, ?, ?)",
                   (migration_id, "READY_FOR_STAGING", artifact))
        db.execute("INSERT INTO outbox(event_id, payload) VALUES (?, ?)",
                   (event_id, payload))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

def relay_once(crash_after_publish=False):
    pending = db.execute(
        "SELECT event_id, payload FROM outbox WHERE sent = 0"
    ).fetchall()
    for event_id, payload in pending:
        broker.append((event_id, json.loads(payload)))  # publish + ack
        if crash_after_publish:
            raise TimeoutError("relay crashed before recording broker ack")
        db.execute("UPDATE outbox SET sent = 1 WHERE event_id = ?",
                   (event_id,))

def consume(event_id, payload):
    db.execute("BEGIN IMMEDIATE")
    try:
        inserted = db.execute(
            "INSERT OR IGNORE INTO inbox(event_id) VALUES (?)",
            (event_id,)
        ).rowcount
        if inserted:
            db.execute(
                "INSERT INTO deployments VALUES (?, ?)",
                (payload["migration_id"], payload["artifact"])
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

record_ready("mig-42", "customer-lookup:revision-3",
             "mig-42:staging-request:v3")
try:
    relay_once(crash_after_publish=True)
except TimeoutError:
    pass
relay_once()  # same event is published again after restart
for event_id, payload in broker:
    consume(event_id, payload)

assert len(broker) == 2
assert db.execute("SELECT COUNT(*) FROM deployments").fetchone()[0] == 1
assert db.execute("SELECT sent FROM outbox").fetchone()[0] == 1
print("2 deliveries; 1 deployment effect; outbox sent")
```
**What this proves:** the workflow state and outbox event are created atomically; an interrupted relay can republish; an idempotent consumer can ignore duplicates. In this small demonstration, the inbox and deployment share one SQLite transaction. A real remote deployment API does **not** share that transaction. It needs its own durable deduplication contract or a lookup-and-reconcile mechanism.
## Production implementation guidance
**Start small:** for one migration orchestrator backed by PostgreSQL, use a dedicated `outbox_events` table and a polling relay. Record `event_id`, `tenant_id`, `workflow_id`, `event_type`, `schema_version`, `payload`, `created_at`, `attempts`, `next_attempt_at`, and `published_at`. Use a unique event ID and an index over pending events.
**Concurrency:** with PostgreSQL, claim a bounded batch using `FOR UPDATE SKIP LOCKED` inside a short transaction or a lease/claim field. Do not hold a database lock during slow network publication. If claiming and publishing are separate, use a lease timeout and ownership token to recover abandoned work; the consumer still needs deduplication.
**Retries:** retry transient failures with bounded exponential backoff and jitter. Move poison messages to a review/dead-letter process after a policy-defined limit. Preserve the original event ID on every retry; never create a new event just because publication timed out.
**Ordering:** where order matters, partition by migration or workflow ID and add a monotonic sequence number. Multiple relay workers can otherwise reorder events. An outbox alone does not guarantee total ordering.
**Polling versus CDC:** polling is easier to prototype and debug. At larger scale, PostgreSQL logical replication plus Debezium's outbox event router can publish inserts to Kafka without application polling. Debezium's standard outbox router expects insert-only events and uses an aggregate ID as the Kafka key. Keep the design simple until throughput or operational needs justify CDC.
**Security and observability:** avoid secrets and raw customer data in outbox payloads; prefer artifact references. Authorize the relay and downstream tool separately. Track pending-row age, retry count, publication latency, consumer dedup hits, dead letters, and end-to-end deployment completion. Propagate trace and workflow IDs.
**Java/Go notes:** In Spring Boot, save workflow state and the outbox entity in one `@Transactional` service method. In Go, use a single `sql.Tx` for both inserts; do not call an external service before `Commit`. In either language, use a separate worker or CDC connector for dispatch.
## Common mistakes and failure modes
- **Database update followed by direct HTTP call:** crash between the two loses the action. Write an outbox record in the same transaction instead.
- **Publish first, save later:** a remote action can happen without a durable workflow record.
- **Assuming exactly-once delivery:** a relay can crash after publishing but before marking sent. Expect duplicates and deduplicate at the receiver.
- **Marking sent before broker acknowledgment:** risks permanent message loss.
- **Confusing published with completed:** broker acceptance is not evidence of successful staging deployment.
- **Treating a queue as an authorization system:** validate the event and recheck permission, fencing, and policy at the execution boundary.
- **Ignoring stuck records:** monitor outbox age, retries, and consumer receipts; create an operational reconciliation process.
## Enterprise use cases
- **Migration automation:** after code parity approval, durably request staging deployment and publish audit events.
- **Insurance claims:** commit an approved claim transition and queue a downstream payment instruction without losing the intent.
- **API governance:** commit a validated API publication decision and enqueue portal/catalog updates.
- **Agentic coding assistant:** persist an approved pull-request action and queue repository operations, preserving a human approval record.
## Cloud mappings (only where they help)
- **AWS:** Amazon RDS or Aurora for workflow + outbox; a relay to Amazon SQS or EventBridge. AWS Prescriptive Guidance documents this pattern.
- **Azure:** Azure SQL plus Service Bus, or Cosmos DB transactional batch and change feed where records share a logical partition.
- **GCP:** Cloud SQL for PostgreSQL plus Pub/Sub; implement polling or CDC and retain idempotent consumers.
These services provide building blocks, not automatic end-to-end exactly-once business effects.
## 45–60 minute hands-on exercise
1. **10 min:** run the Python example and observe two broker deliveries but one deployment record.
2. **15 min:** add a `fail_before_commit` flag inside `record_ready`; verify that neither the workflow state nor the outbox event persists.
3. **15 min:** add an `attempts` column and a simple retry limit; print a warning for events that cannot be published.
4. **10–20 min:** draw a production version using PostgreSQL, a relay, a queue, and an idempotent staging API. Label which operations are atomic and which can be retried.
**Completion criterion:** explain exactly why the outbox prevents a lost deployment *request* but cannot by itself prevent duplicate external deployments.
## What to learn next
**Reconciliation workers and durable agent state machines:** how to detect that an event was published but no verified tool result arrived, and how to recover without inventing a successful outcome.
## Recommended reading
1. [AWS Prescriptive Guidance — Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) — primary explanation of the dual-write failure and the transactional solution.
2. [Debezium — Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html) — practical CDC-based event publication and event IDs.
3. [Microservices.io — Polling Publisher](https://microservices.io/patterns/data/polling-publisher.html) — simplest relay approach and its ordering tradeoffs.
4. [Microsoft Learn — Transactional outbox with Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/architecture/databases/guide/transactional-out-box-cosmos) — change-feed relay and partition-level atomicity.
5. [AWS sample — Transactional Outbox Pattern](https://github.com/aws-samples/transactional-outbox-pattern/blob/main/README.md) — implementation reference.
---
*Daily AI Engineering Learning • Foundation-first architecture, practical implementation, and controlled agent operations.*