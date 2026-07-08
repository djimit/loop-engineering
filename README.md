# Loop Engineering

Agent-loop governance reference implementation for the Djimit ecosystem.

## Architecture

6-phase autonomous orchestrator with circuit breaker:

1. **Validate** — OpenMythos QA gates (critic, reviewer, SME, test_engineer, explorer)
2. **Seed** — Governance policy + capability token seeding into Djitimflo
3. **Execute** — Loop-engineering pattern execution
4. **Observe** — Telemetry import into Djitimflo (loop_runs, loop_events, loop_checkpoints)
5. **Secure** — Prompt-injection gate + security validation
6. **Escalate** — Human escalation gateway (only human interaction point)

## Usage

```bash
# Run full pipeline in L1 mode (report-only)
python3 tools/loop_orchestrator.py L1

# Run QA gates only
python3 tools/qa_gates.py auto
python3 tools/qa_gates.py dispatch

# Seed governance policies
python3 tools/seed_governance.py

# Import telemetry
python3 tools/import_telemetry.py

# Run all tests
python3 tests/test_integration.py
python3 tests/test_security.py
python3 tests/prompt_injection/test_injection.py
```

## Components

| File | Purpose |
|---|---|
| `tools/loop_orchestrator.py` | 6-phase state machine with circuit breaker |
| `tools/qa_gates.py` | 5-agent QA validation (auto + dispatch modes) |
| `tools/seed_governance.py` | Constraint → Djitimflo policy seeding |
| `tools/import_telemetry.py` | JSONL → Djitimflo telemetry import |
| `tools/security.py` | Path traversal, allowlist, git ref validation |
| `tools/escalation_gateway.py` | Human decision interface |
| `loop-constraints.md` | 8 binding governance constraints |

## Ecosystem Integration

```
OpenMythos (governance rules)
    ↓ QA gates validate plan
Loop Engineering (execution)
    ↓ telemetry
Djitimflo (observability + audit)
```
