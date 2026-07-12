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

## Data Flow

1. Archived OpenSpec proposal, design, and specs enter deterministic QA validation.
2. `loop-constraints.md` and `capability_config.json` seed the shared SQLite governance records.
3. The orchestrator validates the selected capability token and budget, then records token usage with the run `correlation_id`.
4. JSONL telemetry becomes idempotent `loop_runs`, `loop_events`, and `loop_checkpoints`; every record carries a correlation ID.
5. Security gates and policy findings are checkpointed before one pending human escalation is created.
6. Approve, reject, or modify is recorded once as the final audited decision.

## Operations, Ownership, and Coupling

The loop-engineering maintainer owns this reference implementation and its SQLite contract. Downstream OpenMythos, Djitimflo, and MCP deployments remain independently owned; this repository writes only through the documented tables and does not import their application code. That narrow database boundary limits cross-system coupling and lets a consumer remove the integration by stopping the orchestrator without migrating product state.

Every autonomous phase propagates the same `correlation_id`. Per-phase and global timeout enforcement prevents a stalled dependency from blocking the final human gate. The polling telemetry watcher and final decision timeout require an invoking process; no scheduler or daemon is introduced in this reference implementation.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Djitimflo schema mismatch between expected and actual | Runtime and tests share the same idempotent `ensure_schema` definition |
| OpenMythos QA gates may reject valid plans | Critic/reviewer operate on plan documents, not code; plans can be iterated |
| Prompt-injection test false positives | Tests use deterministic pattern matching, not LLM evaluation |
| Orchestrator state machine gets stuck | Per-phase timeout (default 30 min) + global timeout (default 4 hours) |
| MCP server hardening breaks legitimate tool calls | Allowlist approach — only block known-dangerous paths, log all denials for review |
| Human escalation timeout causes stale approvals | Default 72h deadline; the next gateway evaluation records a system rejection |
