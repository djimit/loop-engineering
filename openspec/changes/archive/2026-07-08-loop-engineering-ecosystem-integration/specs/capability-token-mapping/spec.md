## ADDED Requirements

### Requirement: L1 mode capability token
The system SHALL create a capability token for L1 mode with scopes [read], risk_class "low", and budget cap of 10,000 tokens.

#### Scenario: L1 token creation
- **WHEN** the orchestrator initializes L1 mode
- **THEN** a capability_token record exists with scopes_json ["read"], risk_class "low", and metadata containing max_budget 10000

### Requirement: L2 mode capability token
The system SHALL create a capability token for L2 mode with scopes [read, pr_create], risk_class "medium", and budget cap of 50,000 tokens.

#### Scenario: L2 token creation
- **WHEN** the orchestrator initializes L2 mode
- **THEN** a capability_token record exists with scopes_json ["read", "pr_create"], risk_class "medium", and metadata containing max_budget 50000

### Requirement: L3 mode capability token
The system SHALL create a capability token for L3 mode with scopes [read, pr_create, merge, publish], risk_class "high", and budget cap of 200,000 tokens.

#### Scenario: L3 token creation
- **WHEN** the orchestrator initializes L3 mode
- **THEN** a capability_token record exists with scopes_json ["read", "pr_create", "merge", "publish"], risk_class "high", and metadata containing max_budget 200000

### Requirement: Token expiry enforcement
The system SHALL enforce a maximum token lifetime of 24 hours for L3 tokens.

#### Scenario: L3 token expires after 24 hours
- **WHEN** an L3 capability_token has been active for more than 24 hours
- **THEN** the system marks the token as expired and denies further actions

### Requirement: Token usage logging
The system SHALL log all token usage to the token_usage_log table with correlation to the capability_token id.

#### Scenario: Token consumption tracked
- **WHEN** an action is performed using a capability token
- **THEN** a token_usage_log entry is created with the token id, action type, and tokens consumed
