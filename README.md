# Loop Engineering

Verified reference implementation for autonomous agent-loop governance in the
Djimit ecosystem.

## Runtime contract

The orchestrator runs five phases without user input and stops at one final
human decision gate:

1. **Validate** — deterministic OpenMythos plan checks
2. **Seed** — idempotent policies and expiring capability tokens
3. **Execute** — capability and budget authorization for the governed run
4. **Observe** — idempotent JSONL telemetry import and phase checkpoints
5. **Secure** — prompt-injection, path, and token-scope gates
6. **Escalate** — persist `awaiting_human` with approve/reject/modify options

Failures, budget overruns, and timeouts skip unsafe remaining work and still
reach the final human gate. No phase performs a merge or publish operation.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LOOP_DB_PATH` | `~/djimitflo/.data/djimitflo.sqlite` | SQLite database |
| `LOOP_PHASE_TIMEOUT` | `1800` | Maximum phase duration in seconds |
| `LOOP_GLOBAL_TIMEOUT` | `14400` | Maximum autonomous run duration |
| `ESCALATION_TIMEOUT_HOURS` | `72` | Pending lifetime; next gateway evaluation rejects expiry |

Mode budgets and scopes live in `tools/capability_config.json`:

- L1: read, 10,000 tokens
- L2: read + draft PR creation, 50,000 tokens
- L3: read + PR/merge/publish scopes, 200,000 tokens

This reference pipeline itself uses only the `read` scope. Higher-risk scopes
are seeded for downstream integrations but are never exercised here.

## Usage

```bash
# Run phases 1-5 and create the final pending decision
python3 tools/loop_orchestrator.py L1

# Inspect the latest final gate
python3 tools/escalation_gateway.py

# Record the final human decision
python3 tools/escalation_gateway.py RUN_ID --decision approve --reason "reviewed"

# Continuously import appended telemetry without duplicates
python3 tools/import_telemetry.py --watch

# Run the complete local verification suite
python3 tests/run_qa_tests.py
```

The gateway also accepts `reject` and `modify`. A decision is immutable; a
second decision for the same run is rejected.

## Components

| File | Purpose |
|---|---|
| `tools/loop_orchestrator.py` | autonomous state machine, budgets, retries |
| `tools/qa_gates.py` | deterministic plan validation and dispatch manifests |
| `tools/seed_governance.py` | policy and capability-token seeding |
| `tools/import_telemetry.py` | idempotent JSONL import and polling watch mode |
| `tools/security.py` | path, allowlist, and git-ref validation |
| `tools/escalation_gateway.py` | final decision summary, timeout, and audit trail |
| `loop-constraints.md` | binding governance constraints |

The implementation uses only the Python standard library.
