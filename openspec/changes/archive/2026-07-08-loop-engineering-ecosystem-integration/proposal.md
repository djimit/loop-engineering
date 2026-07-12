## Why

Loop-engineering is een bewezen reference implementation voor agent-loop governance (scheduling, state, skills, MCP, sub-agents, worktrees, verifier, budget, human gates), maar leeft momenteel als geïsoleerd project. OpenMythos definieert de strategische governance (Rule Maturity Model, confidence scoring, bronverificatie) en Djimitflo biedt het observability-substraat (loop_runs, governance_events, capability_tokens, approval_policies), maar de drie systemen zijn niet gekoppeld. Het gevolg: OpenMythos heeft geen execution engine, Djimitflo heeft geen governance inhoud, en loop-engineering heeft geen formele koppeling met het ecosysteem. Deze change integreert de drie systemen tot één georkestreerde pijplijn waarbij OpenMythos het plan valideert, loop-engineering het uitvoert, en Djimitflo alles observeert en auditeert — volledig autonoom met menselijke interactie alleen aan het einde.

## What Changes

- **Seed Djimitflo governance_policies vanuit loop-constraints.md** — Markdown constraints worden machine-readable JSON policy records met risk_class, scopes, en enforcement rules.
- **Map loop-engineering L1/L2/L3 modes naar Djimitflo capability_tokens** — Elke loop mode wordt een capability token met gedefinieerde scopes (read, pr_create, merge, publish) en budget caps.
- **Publiceer gedeelde security-primitives** — Path traversal beveiliging, state-file allowlisting en git-ref validatie zijn herbruikbaar aan MCP-grenzen; daadwerkelijke serverintegratie blijft buiten deze reference repo.
- **Koppel loop-engineering telemetry aan Djimitflo loop_runs** — De `.swarm/telemetry.jsonl` wordt gestructureerd als loop_runs/loop_events/loop_checkpoints records voor cross-system observability.
- **Voeg prompt-injection test suite toe als gezamenlijke CI gate** — Negatieve tests op attacker-controlled content (issues, PR comments, CI logs) worden gedeeld tussen loop-engineering workflows en OpenMythos rule extraction pipeline.
- **Creëer orchestratie-laag voor autonome uitvoering** — Een nieuwe `loop-orchestrator` tool die het volledige plan afhandelt: OpenMythos validatie → loop-engineering execution → Djimitflo observability → human gate aan het einde.
- **Human escalation gateway** — Menselijke interactie wordt geconcentreerd aan het einde van het plan via een gestructureerde escalation interface, niet verspreid over de pipeline.

## Capabilities

### New Capabilities
- `governance-policy-seeding`: Converteert loop-constraints.md naar machine-readable Djitimflo governance_policies met enforcement rules
- `capability-token-mapping`: Mappt loop-engineering L1/L2/L3 modes naar Djitimflo capability_tokens met scopes en budget caps
- `mcp-server-hardening`: Levert geteste security-primitives voor downstream MCP-integraties
- `telemetry-pipeline`: Koppelt loop-engineering telemetry aan Djitimflo loop_runs/loop_events/loop_checkpoints
- `prompt-injection-gate`: Gezamenlijke CI gate met negatieve testcases op attacker-controlled content
- `autonomous-orchestrator`: End-to-end orchestratie tool die OpenMythos → loop-engineering → Djitimflo aaneenschakelt
- `human-escalation-gateway`: Gestructureerde escalation interface geconcentreerd aan einde van pipeline

### Modified Capabilities
- Geen bestaande specs worden gewijzigd — dit zijn allemaal nieuwe capabilities binnen het ecosysteem.

## Impact

- **Djitimflo database**: governance_policies, capability_tokens, loop_runs, loop_events, loop_checkpoints, governance_events tabellen worden gevuld
- **Loop-engineering repo**: Nieuwe orchestratie tooling, MCP server hardening, telemetry export
- **OpenMythos**: Plan validatie via bestaande QA gates (critic, reviewer, sme, test_engineer, explorer)
- **CI/CD**: Nieuwe gedeelde prompt-injection test pipeline
- **MCP servers**: downstream servers kunnen de geteste security-primitives adopteren
- **Security**: Prompt-injection resilience, path traversal bescherming, token-segregatie via capability_tokens
- **Human interaction**: Geconcentreerd aan einde via escalation gateway, niet verspreid over pipeline

## Mitigations

- SQLite-schema-afwijkingen worden afgevangen door dezelfde `ensure_schema`-bron in runtime en tests te gebruiken.
- Iedere fase heeft een timeout, maximaal drie pogingen en een circuit breaker; falen leidt naar de eindgate.
- Capability-scopes, vervaldatum en budget worden vóór governed execution gecontroleerd en iedere consumptie wordt gecorreleerd gelogd.
- Telemetry-import gebruikt stabiele bronoffset-ID's zodat herstarten of opnieuw importeren geen duplicaten maakt.
- De gateway accepteert één immutable eindbesluit en wijst een verlopen verzoek bij de volgende evaluatie automatisch af.
