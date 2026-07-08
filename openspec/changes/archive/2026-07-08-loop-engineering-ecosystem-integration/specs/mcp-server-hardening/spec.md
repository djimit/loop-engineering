## ADDED Requirements

### Requirement: Path traversal prevention
The MCP server SHALL reject any resource path containing "..", forward slash, backslash, or null bytes.

#### Scenario: Blocked path traversal attempt
- **WHEN** a tool call requests a resource path containing ".."
- **THEN** the server returns an error and logs the attempt to governance_events

#### Scenario: Blocked absolute path
- **WHEN** a tool call requests an absolute path starting with "/"
- **THEN** the server returns an error and the request is denied

### Requirement: State file access restriction
The MCP server SHALL only allow reads to known state files listed in an allowlist.

#### Scenario: Allowed state file read
- **WHEN** a tool call requests STATE.md or LOOP.md
- **THEN** the server returns the file content

#### Scenario: Disallowed file read
- **WHEN** a tool call requests auth.json or .env
- **THEN** **THEN** the server returns an access denied error

### Requirement: Realpath validation
The MCP server SHALL validate that resolved resource paths remain within the expected directory using realpath.

#### Scenario: Path escapes base directory
- **WHEN** a symlink or relative path resolves outside the allowed base directory
- **THEN** the server denies access and logs a security event

### Requirement: Capability token validation per tool call
The MCP server SHALL validate the caller's capability token scopes before executing any tool.

#### Scenario: Insufficient scope
- **WHEN** a tool call requires "write" scope but the token only has "read"
- **THEN** the server returns a permission denied error

### Requirement: MCP call audit logging
The MCP server SHALL log every tool call to governance_events with actor identity, tool name, and outcome.

#### Scenario: Successful tool call logged
- **WHEN** a tool call completes successfully
- **THEN** a governance_events record is created with action_type "mcp_tool_call", tool_name, and outcome "success"
