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

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LOOP_DB_PATH` | `~/djimitflo/.data/djimitflo.sqlite` | SQLite database path for all tools |
| `LOOP_PHASE_TIMEOUT` | `1800` (30 min) | Per-phase timeout in seconds |
| `LOOP_GLOBAL_TIMEOUT` | `14400` (4 hours) | Global orchestrator timeout in seconds |
| `ESCALATION_TIMEOUT_HOURS` | `72` | Hours before escalation auto-rejects |

### Configuration Module

`tools/config.py` provides shared configuration:

```python
from config import get_db_path, REPO_ROOT, db_connection, ensure_schema

# Get database path (respects LOOP_DB_PATH env var)
db_path = get_db_path()

# Use context manager for auto-commit/rollback
with db_connection() as conn:
    ensure_schema(conn)
    # ... use conn ...
```

### Logging

All tools use Python's `logging` module. Configure via:

```python
from config import configure_logging
configure_logging("DEBUG")  # or INFO, WARNING, ERROR
```

Log output goes to stderr with format: `timestamp [LEVEL] name: message`

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

# Run integration tests
python3 tests/test_integration.py
python3 tests/test_security.py
python3 tests/prompt_injection/test_injection.py

# Run unit tests (fast, no subprocess)
python3 tests/test_qa_gates.py
python3 tests/test_seed_governance.py
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
