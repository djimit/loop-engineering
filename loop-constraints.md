# Loop Constraints

## Binding Constraints

These constraints are authoritatively enforced by the governance policy engine. All agent loops MUST comply.

### Constraint: No push without notification
- **id**: `no-push-without-notify`
- **risk_class**: medium
- **scopes**: [read, write]
- **description**: Agent MUST notify user before pushing any changes to remote. Push without prior notification is a policy violation.
- **enforcement**: warn_and_log

### Constraint: No auto-merge to main without human approval
- **id**: `no-auto-merge-main`
- **risk_class**: high
- **scopes**: [read, write, merge]
- **description**: Agent MUST NEVER auto-merge to main branch without explicit human approval via protected environment and required review.
- **enforcement**: block_and_escalate

### Constraint: Draft PR before merge
- **id**: `draft-pr-first`
- **risk_class**: medium
- **scopes**: [read, pr_create]
- **description**: Agent MUST always create a draft PR before attempting any merge operation.
- **enforcement**: block_and_log

### Constraint: No secrets in prompts or state
- **id**: `no-secrets-in-prompts`
- **risk_class**: critical
- **scopes**: [read]
- **description**: Agent MUST NEVER include secrets, API keys, or credentials in prompts, state files, or telemetry.
- **enforcement**: block_and_escalate

### Constraint: Read-only connectors by default
- **id**: `readonly-by-default`
- **risk_class**: low
- **scopes**: [read]
- **description**: All MCP connectors default to read-only scope. Write scopes require explicit capability token grant.
- **enforcement**: warn_and_log

### Constraint: Human review for sensitive changes
- **id**: `human-review-sensitive`
- **risk_class**: high
- **scopes**: [read, write, merge, publish]
- **description**: Changes touching auth, payments, PII, infrastructure, dependencies, or security configurations require mandatory human review.
- **enforcement**: block_and_escalate

### Constraint: Token budget enforcement
- **id**: `token-budget-cap`
- **risk_class**: medium
- **scopes**: [read, write]
- **description**: Agent MUST halt operations when token budget is exceeded. No exceptions without human approval.
- **enforcement**: block_and_log

### Constraint: Ephemeral tokens only
- **id**: `ephemeral-tokens`
- **risk_class**: high
- **scopes**: [read, write]
- **description**: All capability tokens MUST have a maximum lifetime of 24 hours. Long-lived tokens are prohibited.
- **enforcement**: block_and_log
