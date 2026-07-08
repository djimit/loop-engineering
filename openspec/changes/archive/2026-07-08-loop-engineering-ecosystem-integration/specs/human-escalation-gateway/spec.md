## ADDED Requirements

### Requirement: Phase summary generation
The gateway SHALL generate a structured summary of all completed phases including status, findings, and token usage.

#### Scenario: Summary after successful phases
- **WHEN** phases 1-5 complete successfully
- **THEN** the gateway presents a summary with per-phase status, key findings, and total tokens consumed

#### Scenario: Summary after partial failure
- **WHEN** phase 3 fails but the orchestrator escalated
- **THEN** the gateway presents a summary with the failure point, retry count, and circuit breaker state

### Requirement: Findings aggregation
The gateway SHALL aggregate all findings from OpenMythos QA, security gates, and policy violations into a single structured report.

#### Scenario: Aggregated findings
- **WHEN** multiple phases produce findings
- **THEN** the gateway presents a deduplicated, severity-sorted findings list

### Requirement: Approval interface
The gateway SHALL present the user with clear approve/reject/modify options.

#### Scenario: User approves
- **WHEN** the user selects "approve"
- **THEN** the gateway logs the decision and marks the change as approved in governance_events

#### Scenario: User rejects
- **WHEN** the user selects "reject"
- **THEN** the gateway logs the decision with reason and marks the change as rejected

#### Scenario: User requests modification
- **WHEN** the user selects "modify"
- **THEN** the gateway captures the modification request and routes back to the appropriate phase

### Requirement: Audit trail for human decisions
The gateway SHALL log all human decisions to governance_events with full context.

#### Scenario: Decision logged with evidence
- **WHEN** the user makes a decision at the escalation gateway
- **THEN** a governance_events record is created with action_type "human_decision", the decision, reasoning, and actor identity

### Requirement: Escalation timeout
The gateway SHALL enforce a configurable timeout for human response (default: 72 hours).

#### Scenario: Timeout triggers default action
- **WHEN** no human response is received within the timeout period
- **THEN** the gateway applies the configured default action (reject or escalate-to-admin)
