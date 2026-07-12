## 1. Governance Policy Seeding

- [x] 1.1 Parse loop-constraints.md and extract structured constraint definitions (id, name, description, risk_class, scopes)
- [x] 1.2 Create Python script `tools/seed_governance.py` that reads constraints and inserts into Djitimflo governance_policies table
- [x] 1.3 Implement idempotent INSERT OR REPLACE logic for policy seeding (no duplicates on re-run)
- [x] 1.4 Add constraint drift detection: compare workflow YAML actions against seeded policies, flag mismatches
- [x] 1.5 Log all seeding operations to governance_events table with action_type "policy_seeded"

## 2. Capability Token Mapping

- [x] 2.1 Define L1/L2/L3 token configurations (scopes, risk_class, budget caps) in a JSON config file
- [x] 2.2 Extend `tools/seed_governance.py` to insert capability_tokens records for each loop mode
- [x] 2.3 Implement token expiry logic: all tokens expire within 24 hours
- [x] 2.4 Add token usage tracking: every action logs to token_usage_log with correlation to capability_token

## 3. Shared Security Boundary

- [x] 3.1 Copy assertSafeSegment function from loop-mcp-server into shared security module
- [x] 3.2 Implement realpath validation: resolved paths must remain within allowed base directory
- [x] 3.3 Create state-file allowlist: only STATE.md, LOOP.md, telemetry files are readable
- [x] 3.4 Add capability-token scope validation before governed execution
- [x] 3.5 Add audit logging for governed orchestration actions and outcomes

## 4. Telemetry Pipeline

- [x] 4.1 Create Python script `tools/import_telemetry.py` that reads .swarm/telemetry.jsonl and inserts into loop_runs
- [x] 4.2 Implement per-phase event generation: phase transitions create loop_events records
- [x] 4.3 Implement checkpoint recording: phase boundaries create loop_checkpoints with state, gates, findings
- [x] 4.4 Add incremental polling watch mode without duplicate imports
- [x] 4.5 Add correlation ID generation and propagation across all telemetry records

## 5. Prompt-Injection Gate

- [x] 5.1 Create test suite `tests/prompt_injection/` with 4 negative test cases (ignore instructions, secret extraction, unauthorized merge, test disabling)
- [x] 5.2 Implement deterministic pattern matching for injection detection (no LLM evaluation)
- [x] 5.3 Add CI workflow `.github/workflows/prompt-injection-gate.yml` that runs test suite on every PR
- [x] 5.4 Implement circuit breaker trigger: failed injection test → governance_circuit_breaker trip → pipeline halt
- [x] 5.5 Add injection attempt logging to governance_events with pattern matched and source

## 6. Autonomous Orchestrator

- [x] 6.1 Create `tools/loop_orchestrator.py` with phase state machine (validate → seed → execute → observe → secure → escalate)
- [x] 6.2 Implement per-phase circuit breaker with max 3 retries and exponential backoff
- [x] 6.3 Implement cumulative token budget tracking across all phases
- [x] 6.4 Implement auto-escalation decision logic based on phase outcomes and risk levels
- [x] 6.5 Implement append-only audit logging for every orchestrator decision and state transition
- [x] 6.6 Add per-phase timeout (default 30 min) and global timeout (default 4 hours)
- [x] 6.7 Ensure no user prompts during phases 1-5 (human interaction only at Phase 6)

## 7. Human Escalation Gateway

- [x] 7.1 Create `tools/escalation_gateway.py` that generates structured phase summary
- [x] 7.2 Implement findings aggregation: deduplicate and severity-sort from all phases
- [x] 7.3 Implement non-interactive approval CLI with approve/reject/modify options
- [x] 7.4 Add audit trail logging for human decisions to governance_events
- [x] 7.5 Add configurable escalation timeout (default 72 hours, reject on evaluation)

## 8. Integration & Testing

- [x] 8.1 Create end-to-end integration test that runs the full orchestrator pipeline
- [x] 8.2 Verify autonomous execution: phases 1-5 complete without user interaction
- [x] 8.3 Verify all Djitimflo tables are populated (governance_policies, capability_tokens, loop_runs, loop_events, governance_events)
- [x] 8.4 Verify OpenMythos QA gates function correctly (mock critic/reviewer verdicts)
- [x] 8.5 Verify prompt-injection gate correctly fails on adversarial input
- [x] 8.6 Verify circuit breaker trips after max retries and triggers escalation
- [x] 8.7 Verify telemetry idempotency, token budget enforcement, final decisions, and timeout rejection
