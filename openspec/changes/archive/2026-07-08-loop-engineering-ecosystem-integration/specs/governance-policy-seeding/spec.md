## ADDED Requirements

### Requirement: Parse loop-constraints.md to policy records
The system SHALL parse loop-constraints.md and extract structured policy records with id, name, description, risk_class, scopes, and enforcement rules.

#### Scenario: Successful parsing of constraints
- **WHEN** loop-constraints.md exists with valid constraint definitions
- **THEN** the system generates one governance_policy record per constraint with unique id and non-empty rules_json

#### Scenario: Constraint drift detection
- **WHEN** a workflow file contains actions that contradict a seeded policy
- **THEN** the system flags a drift event in governance_events with severity "high"

### Requirement: Idempotent policy seeding
The system SHALL ensure that seeding the same constraints multiple times does not create duplicate policy records.

#### Scenario: Re-seeding existing policies
- **WHEN** governance_policies already contains a record with the same id
- **THEN** the system updates the existing record instead of inserting a duplicate

### Requirement: Policy enforcement logging
The system SHALL log every policy insertion, update, and drift detection to the governance_events table.

#### Scenario: Policy creation logged
- **WHEN** a new governance_policy is inserted
- **THEN** a governance_events record is created with action_type "policy_created" and the policy id in metadata_json
