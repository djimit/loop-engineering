## Context

Three systems in the Djimit ecosystem currently operate in isolation:

1. **OpenMythos** (`~/OpenMythos/analysis/legal-ruleops-platform/`) — Strategic governance layer defining Rule Maturity Model (L1-L4), confidence scoring, source verification, and agent orchestration patterns (6 layers). Contains agent-architect, agent-critic, and agentic-bv-nederland-advisie documents. Has QA gates (critic, reviewer, sme, test_engineer, explorer) but no execution engine.

2. **Loop-engineering** (`~/loop-engineering/`) — Operational agent-loop governance with scheduling, state management, MCP server, worktrees, circuit breaker, verifier, budget tracking, and human gates. Contains loop-init, loop-audit, loop-cost, loop-context, loop-sync, loop-mcp-server, loop-worktree. Dogfoods via .swarm/telemetry.jsonl, LOOP.md, STATE.md.

3. **Djitimflo** (`~/djimitflo/.data/djimitflo.sqlite`) — Observability substrate with 120+ tables including governance_policies, capability_tokens, loop_runs, loop_events, loop_checkpoints, governance_events, governance_circuit_breaker, token_usage_log, approval_policies, policy_violations, sandbox_policies. Schema is defined but tables are empty.

The integration gap: OpenMythos defines WHAT should be governed, loop-engineering defines HOW to run loops, Djitimflo observes WHAT happened — but no system connects all three.

## Goals / Non-Goals

**Goals:**
- Connect OpenMythos governance rules → loop-engineering execution → Djitimflo observability in a single autonomous pipeline
- Seed empty Djitimflo governance tables from loop-engineering constraints
- Enable fully autonomous execution (phases 1-5) with human interaction only at the final escalation gateway
- Harden MCP server with loop-engineering's path traversal patterns
- Create shared prompt-injection test suite as CI gate

**Non-Goals:**
- Building a new product or customer-facing feature
- Replacing OpenMythos, loop-engineering, or Djitimflo — integration only
- Modifying existing OpenMythos agent prompts or Djitimflo schema
- Production deployment of the orchestrator (this is a reference implementation)

## Decisions

### Decision 1: Orchestration Model — State Machine with Circuit Breaker
**Choice:** Single orchestrator script implementing a 6-phase state machine with per-phase circuit breakers (max 3 retries).

**Alternatives considered:**
- *Event-driven (webhooks between systems)* → Rejected: adds infrastructure complexity, harder to debug, no clear failure mode
- *Pure agent-driven (OpenCode swarm coordinates)* → Rejected: too non-deterministic for governance pipeline, no guaranteed phase ordering
- *Cron-based scheduling* → Rejected: no phase dependency management, no circuit breaker

**Rationale:** State machine gives deterministic phase ordering, clear failure modes, and audit-friendly transitions. Circuit breaker prevents infinite retry loops.

### Decision 2: Djitimflo as System of Record
**Choice:** Djitimflo SQLite is the single source of truth for governance state, capability tokens, loop telemetry, and audit events.

**Alternatives considered:**
- *Separate JSON files per system* → Rejected: no cross-system querying, no relational integrity
- *New PostgreSQL database* → Rejected: overkill for reference implementation, adds operational burden

**Rationale:** Djitimflo already has the schema. Seeding it from loop-engineering constraints and OpenMythos governance rules gives immediate cross-system observability.

### Decision 3: MCP Server Hardening — Adopt loop-mcp-server Patterns
**Choice:** Copy assertSafeSegment, realpath validation, and state-file allowlist patterns from loop-mcp-server into the JuraRegel MCP server design.

**Alternatives considered:**
- *Build new MCP framework from scratch* → Rejected: loop-engineering already solved this correctly
- *Use existing MCP SDK security features only* → Rejected: SDK doesn't include path traversal protection by default

**Rationale:** loop-mcp-server's security patterns are proven and minimal. Adopting them avoids reinventing security controls.

### Decision 4: Prompt-Injection Testing — Negative Test Suite
**Choice:** Create a shared negative test suite with 4 core injection patterns (ignore instructions, secret extraction, unauthorized merge, test disabling) that runs as a CI gate in both loop-engineering and OpenMythos pipelines.

**Alternatives considered:**
- *LLM-based injection detection* → Rejected: non-deterministic, can be bypassed
- *Input sanitization only* → Rejected: doesn't test agent behavior under adversarial input

**Rationale:** Deterministic negative tests with known adversarial inputs provide verifiable, repeatable security assurance.

### Decision 5: Human Escalation — Concentrated at Phase 6
**Choice:** All human interaction is concentrated at the final escalation gateway (Phase 6). Phases 1-5 run fully autonomously.

**Alternatives considered:**
- *Human approval per phase* → Rejected: too interruptive, defeats autonomous operation
- *Human approval only for L3 actions* → Rejected: inconsistent with the "validate first, act later" governance model
- *No human interaction at all* → Rejected: violates governance requirement for human oversight

**Rationale:** Concentrating human interaction at the end respects the governance model (validate everything, then present a complete picture for decision) while enabling full autonomy during execution.

## Cross-System Coupling Analysis

The three systems are connected via explicit, unidirectional data flows. Coupling is intentional but bounded:

### Coupling Points

| From | To | Mechanism | Coupling Type | Blast Radius |
|---|---|---|---|---|
| OpenMythos | Orchestrator | File-based (proposal.md, design.md, specs/) | Low — read-only | QA gates fail → pipeline pauses, no data corruption |
| Orchestrator | Djitimflo | SQLite INSERT via seed_governance.py, import_telemetry.py | Medium — write | Bad seed data → governance_policies polluted (mitigated by idempotent UPSERT) |
| Orchestrator | loop-engineering | Local file system + subprocess calls | High — execution | Script failure → circuit breaker trips, escalation gateway triggers |
| Djitimflo | Escalation Gateway | SQLite SELECT | Low — read-only | DB unavailable → gateway shows cached summary |

### Coupling Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Djitimflo schema drift breaks seeding | Runtime schema detection in seed_governance.py; INSERT OR REPLACE handles column changes; schema version check before writes |
| OpenMythos agent unavailability | QA gates degrade gracefully — auto mode runs deterministic checks without agent dispatch; dispatch mode generates manifest for later execution |
| Orchestrator version mismatch with Djitimflo schema | Schema compatibility check at startup; clear error message if columns missing; migration script for additive changes |
| Telemetry volume overwhelns Djitimflo | Batch imports with configurable batch size; watch mode uses incremental reads; old telemetry archived after import |
| Cross-system circular dependency | Strictly unidirectional: OpenMythos → Orchestrator → Djitimflo. No feedback loops. Djitimflo never writes back to Orchestrator or OpenMythos. |

### Failure Isolation

Each phase is isolated:
- Phase 1 (validate) failure → no seeding, no execution, no data mutation
- Phase 2 (seed) failure → no execution, governance_policies unchanged (UPSERT is atomic per-record)
- Phase 3 (execute) failure → no telemetry import, no security gate execution
- Phase 4 (observe) failure → security gate still runs (independent of telemetry)
- Phase 5 (secure) failure → circuit breaker trips, escalation gateway presents failure context
- Phase 6 (escalate) → human decision with full context from all prior phases

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Djitimflo schema mismatch between expected and actual | Schema is read at runtime; migration script checks column existence before INSERT |
| OpenMythos QA gates may reject valid plans | Critic/reviewer operate on plan documents, not code; plans can be iterated |
| Prompt-injection test false positives | Tests use deterministic pattern matching, not LLM evaluation |
| Orchestrator state machine gets stuck | Per-phase timeout (default 30 min) + global timeout (default 4 hours) |
| MCP server hardening breaks legitimate tool calls | Allowlist approach — only block known-dangerous paths, log all denials for review |
| Human escalation timeout causes stale approvals | Default 72h timeout with configurable escalation-to-admin fallback |
| Bus factor — single point of failure in maintenance | CODEOWNERS with explicit ownership per component; security-critical paths require multiple reviewers |
| Cross-system coupling cascade failure | Unidirectional data flow; per-phase isolation; circuit breaker prevents cascade |
