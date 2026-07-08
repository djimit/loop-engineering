## ADDED Requirements

### Requirement: Phase state machine
The orchestrator SHALL implement a state machine with phases: validate → seed → execute → observe → secure → escalate.

#### Scenario: Sequential phase execution
- **WHEN** the orchestrator starts
- **THEN** it executes phases in order and does not skip any phase

#### Scenario: Phase failure halts pipeline
- **WHEN** any phase fails its exit gate
- **THEN** the orchestrator does not proceed to the next phase

### Requirement: Circuit breaker per phase
The orchestrator SHALL implement a circuit breaker per phase with a maximum of 3 retries.

#### Scenario: Retry on transient failure
- **WHEN** a phase fails due to a transient error (e.g., network timeout)
- **THEN** the orchestrator retries up to 3 times before marking the phase as failed

#### Scenario: Circuit breaker trips after max retries
- **WHEN** a phase fails 3 consecutive times
- **THEN** the circuit breaker trips and the orchestrator escalates to the human gate

### Requirement: Token budget tracking
The orchestrator SHALL track cumulative token usage across all phases and halt if the total budget is exceeded.

#### Scenario: Budget cap enforced
- **WHEN** cumulative token usage exceeds the configured budget cap
- **THEN** the orchestrator halts execution and triggers the human escalation gateway

### Requirement: Auto-escalation decision
The orchestrator SHALL autonomously decide whether human escalation is needed based on phase outcomes, policy violations, and risk levels.

#### Scenario: Auto-escalation on high risk
- **WHEN** the explorer agent reports a critical risk finding
- **THEN** the orchestrator routes to the human escalation gateway with the finding attached

#### Scenario: No escalation on clean run
- **WHEN** all phases complete with no critical findings
- **THEN** the orchestrator proceeds to the human escalation gateway for final approval

### Requirement: Immutable audit logging
The orchestrator SHALL write append-only audit records for every decision and state transition.

#### Scenario: Decision logged
- **WHEN** the orchestrator makes a phase transition decision
- **THEN** an audit record is created with timestamp, decision, reasoning, and actor

### Requirement: Human interaction only at Phase 6
The orchestrator SHALL NOT prompt the user during phases 1-5 and SHALL only present the human escalation gateway at Phase 6.

#### Scenario: No user prompts during execution
- **WHEN** the orchestrator is in phases 1 through 5
- **THEN** no user interaction is requested

#### Scenario: Human gate at Phase 6
- **WHEN** the orchestrator reaches Phase 6
- **THEN** the human escalation gateway is presented with full context
