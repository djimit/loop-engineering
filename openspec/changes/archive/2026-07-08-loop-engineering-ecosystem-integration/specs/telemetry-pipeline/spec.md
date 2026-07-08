## ADDED Requirements

### Requirement: Telemetry import from JSONL
The system SHALL import .swarm/telemetry.jsonl entries into Djitimflo loop_runs records.

#### Scenario: Successful import
- **WHEN** .swarm/telemetry.jsonl contains valid telemetry entries
- **THEN** each entry is inserted as a loop_run record with loop_name, mode, status, and findings_json

#### Scenario: Duplicate detection
- **WHEN** a telemetry entry with the same id already exists in loop_runs
- **THEN** the system skips the duplicate and logs a warning

### Requirement: Per-phase event generation
The system SHALL generate loop_events records for each phase of a loop run.

#### Scenario: Phase events created
- **WHEN** a loop run progresses through phases (validate, seed, execute, observe, secure, escalate)
- **THEN** a loop_events record is created per phase transition with event_type "phase_start" or "phase_complete"

### Requirement: Checkpoint recording
The system SHALL record loop_checkpoints with state_json, gates_json, and findings_json at each phase boundary.

#### Scenario: Checkpoint after validation phase
- **WHEN** the validation phase completes
- **THEN** a loop_checkpoint record exists with label "validation_complete" and gates_json containing the QA verdict

### Requirement: Real-time watch mode
The system SHALL support a watch mode that continuously imports new telemetry entries.

#### Scenario: New entry detected
- **WHEN** a new entry is appended to .swarm/telemetry.jsonl during watch mode
- **THEN** the system imports it within 5 seconds

### Requirement: Correlation ID tracing
The system SHALL attach correlation IDs to all telemetry records for cross-system tracing.

#### Scenario: Correlation chain
- **WHEN** a loop run generates events and checkpoints
- **THEN** all records share the same correlation_id in their metadata field
