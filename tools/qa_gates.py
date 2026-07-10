#!/usr/bin/env python3
"""OpenMythos QA Gates — 5-agent validation pipeline.

Dispatches critic, reviewer, sme, test_engineer, and explorer roles
to validate the integration plan before execution.

Each role produces a structured verdict: APPROVE / CONCERNS / REJECT
with findings, confidence score, and assessed criteria.

Can run in two modes:
  mode="auto"    — deterministic checks (no LLM needed, fast)
  mode="dispatch" — generates agent dispatch manifest for OpenCode subagents
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
# Check active location first, fall back to archive
_active = REPO_ROOT / "openspec" / "changes" / "loop-engineering-ecosystem-integration"
_archived = (
    REPO_ROOT
    / "openspec"
    / "changes"
    / "archive"
    / "2026-07-08-loop-engineering-ecosystem-integration"
)
PLAN_DIR = _active if (_active / "proposal.md").exists() else _archived
DISPATCH_DIR = REPO_ROOT / ".swarm" / "qa-dispatches"


# ── QA Gate Roles ──────────────────────────────────────────────────────

QA_ROLES = {
    "critic": {
        "name": "Plan Critic",
        "focus": "Risks, feasibility gaps, scope creep, hidden assumptions",
        "criteria": [
            "scope_clarity",
            "risk_identification",
            "feasibility",
            "assumption_validity",
            "rollback_readiness",
        ],
    },
    "reviewer": {
        "name": "Technical Reviewer",
        "focus": "Code quality, architecture soundness, integration correctness",
        "criteria": [
            "architecture_soundness",
            "integration_correctness",
            "security_posture",
            "test_coverage",
            "maintainability",
        ],
    },
    "sme": {
        "name": "Subject Matter Expert",
        "focus": "Domain correctness for agent-loop governance ecosystem",
        "criteria": [
            "domain_alignment",
            "ecosystem_fit",
            "governance_completeness",
            "operational_readiness",
            "compliance_coverage",
        ],
    },
    "test_engineer": {
        "name": "Test Engineer",
        "focus": "Test coverage, edge cases, failure modes, verification strategy",
        "criteria": [
            "unit_test_coverage",
            "integration_test_coverage",
            "edge_case_coverage",
            "failure_mode_testing",
            "verification_strategy",
        ],
    },
    "explorer": {
        "name": "Risk Explorer",
        "focus": "Unknown unknowns, second-order effects, coupling risks",
        "criteria": [
            "unknown_unknowns",
            "second_order_effects",
            "coupling_risks",
            "cascade_failures",
            "escalation_gaps",
        ],
    },
}


# ── Auto Mode: Deterministic Checks ────────────────────────────────────


def check_scope_clarity(proposal: str, design: str) -> dict:
    """Does the proposal clearly define scope boundaries?"""
    findings = []
    score = 10

    if "## Impact" not in proposal:
        findings.append("Proposal missing Impact section")
        score -= 2
    if "## What Changes" not in proposal:
        findings.append("Proposal missing What Changes section")
        score -= 2
    if "Non-Goals" not in design:
        design_missing = "Design missing Non-Goals section (scope boundary unclear)"
        findings.append(design_missing)
        score -= 3

    return {"criterion": "scope_clarity", "score": max(0, score), "findings": findings}


def check_risk_identification(proposal: str, design: str) -> dict:
    """Are risks explicitly identified and mitigated?"""
    findings = []
    score = 10

    if "Risks" not in design and "risks" not in design.lower():
        findings.append("Design has no explicit Risks section")
        score -= 3
    if "trade-off" not in design.lower() and "tradeoff" not in design.lower():
        findings.append("Design does not discuss trade-offs")
        score -= 2
    if "Mitigation" not in proposal and "mitigation" not in proposal.lower():
        findings.append("Proposal lacks mitigation strategies")
        score -= 2

    return {
        "criterion": "risk_identification",
        "score": max(0, score),
        "findings": findings,
    }


def check_feasibility(proposal: str, design: str) -> dict:
    """Is the plan feasible given current infrastructure?"""
    findings = []
    score = 10

    # Check if referenced paths exist
    if "Djitimflo" in proposal:
        db_path = os.environ.get(
            "LOOP_DB_PATH", os.path.expanduser("~/djimitflo/.data/djimitflo.sqlite")
        )
        if not os.path.exists(db_path):
            findings.append(f"Djitimflo database not found at {db_path}")
            score -= 3

    if "OpenMythos" in proposal:
        om_path = os.path.expanduser("~/OpenMythos/analysis/legal-ruleops-platform/")
        if not os.path.exists(om_path):
            findings.append(f"OpenMythos path not found: {om_path}")
            score -= 3

    # Check for realistic scope (not too many capabilities at once)
    cap_count = proposal.count("`capability-")
    if cap_count > 10:
        findings.append(f"High capability count ({cap_count}) — consider phasing")
        score -= 2

    return {"criterion": "feasibility", "score": max(0, score), "findings": findings}


def check_security_posture(design: str, specs_dir: Path) -> dict:
    """Are security controls adequate?"""
    findings = []
    score = 10

    if "prompt-injection" not in design.lower():
        findings.append("Design does not address prompt-injection risks")
        score -= 3
    if "path traversal" not in design.lower():
        findings.append("Design does not mention path traversal protection")
        score -= 2
    if "circuit breaker" not in design.lower():
        findings.append("Design does not mention circuit breaker pattern")
        score -= 2

    # Check if security spec exists
    security_spec = specs_dir / "prompt-injection-gate" / "spec.md"
    if not security_spec.exists():
        findings.append("Missing prompt-injection-gate spec")
        score -= 3

    return {
        "criterion": "security_posture",
        "score": max(0, score),
        "findings": findings,
    }


def check_architecture_soundness(design: str) -> dict:
    """Is the architecture sound?"""
    findings = []
    score = 10

    if "state machine" not in design.lower() and "state_machine" not in design.lower():
        findings.append("Design does not describe state machine pattern")
        score -= 2
    if "circuit breaker" not in design.lower():
        findings.append("No circuit breaker pattern described")
        score -= 2
    if "phase" not in design.lower():
        findings.append("Design does not describe phases")
        score -= 3
    if "data flow" not in design.lower() and "Data Flow" not in design:
        findings.append("Design missing data flow description")
        score -= 2

    return {
        "criterion": "architecture_soundness",
        "score": max(0, score),
        "findings": findings,
    }


def check_test_coverage(specs_dir: Path) -> dict:
    """Are there adequate test specifications?"""
    findings = []
    score = 10

    spec_files = list(specs_dir.glob("*/spec.md"))
    if len(spec_files) < 5:
        findings.append(f"Only {len(spec_files)} specs — expected at least 5")
        score -= 3

    # Check for negative test cases
    injection_spec = specs_dir / "prompt-injection-gate" / "spec.md"
    if injection_spec.exists():
        content = injection_spec.read_text()
        if "Scenario:" not in content:
            findings.append("Injection spec has no scenarios")
            score -= 2
        scenario_count = content.count("#### Scenario:")
        if scenario_count < 3:
            findings.append(f"Only {scenario_count} injection scenarios — expected 4+")
            score -= 2

    return {"criterion": "test_coverage", "score": max(0, score), "findings": findings}


def check_ecosystem_fit(proposal: str, design: str) -> dict:
    """Does the plan fit the existing Djimit ecosystem?"""
    findings = []
    score = 10

    # Check ecosystem references
    if "OpenMythos" not in proposal:
        findings.append("Proposal does not reference OpenMythos")
        score -= 2
    if "Djitimflo" not in proposal:
        findings.append("Proposal does not reference Djitimflo")
        score -= 2
    if "loop-engineering" not in proposal:
        findings.append("Proposal does not reference loop-engineering")
        score -= 1

    # Check for integration points
    if "governance_policies" not in design.lower():
        findings.append("Design does not describe governance_policies integration")
        score -= 2
    if "capability_tokens" not in design.lower():
        findings.append("Design does not describe capability_tokens integration")
        score -= 2

    return {"criterion": "ecosystem_fit", "score": max(0, score), "findings": findings}


def check_governance_completeness(specs_dir: Path) -> dict:
    """Are governance controls complete?"""
    findings = []
    score = 10

    required_gates = [
        "governance-policy-seeding",
        "capability-token-mapping",
        "human-escalation-gateway",
    ]
    for gate in required_gates:
        if not (specs_dir / gate / "spec.md").exists():
            findings.append(f"Missing required governance spec: {gate}")
            score -= 3

    return {
        "criterion": "governance_completeness",
        "score": max(0, score),
        "findings": findings,
    }


def check_unknown_unknowns(design: str, proposal: str) -> dict:
    """Identify potential unknown unknowns and second-order effects."""
    findings = []
    score = 10

    # Check for bus factor risk
    if "maintainer" not in design.lower() and "CODEOWNERS" not in design:
        findings.append("No maintainer/bus factor consideration")
        score -= 2

    # Check for token scope explosion
    token_scopes = proposal.count("scopes_json")
    if token_scopes > 5:
        findings.append(
            f"High token scope count ({token_scopes}) — risk of scope creep"
        )
        score -= 2

    # Check for cross-system coupling
    if "coupling" not in design.lower():
        findings.append("Design does not discuss cross-system coupling risks")
        score -= 2

    # Check for escalation path clarity
    if "escalation" not in design.lower():
        findings.append("Design does not describe escalation paths")
        score -= 3

    return {
        "criterion": "unknown_unknowns",
        "score": max(0, score),
        "findings": findings,
    }


def check_integration_correctness(design: str) -> dict:
    """Are the integration points correct?"""
    findings = []
    score = 10

    # Check for correct database path references
    if "djimitflo.sqlite" in design.lower():
        if "~/" not in design and "expanduser" not in design:
            findings.append("Database path may not handle ~ expansion")
            score -= 1

    # Check for correlation ID propagation
    if "correlation_id" not in design.lower():
        findings.append("No correlation ID propagation described")
        score -= 2

    # Check for timeout handling
    if "timeout" not in design.lower():
        findings.append("No timeout handling described")
        score -= 2

    return {
        "criterion": "integration_correctness",
        "score": max(0, score),
        "findings": findings,
    }


def run_auto_checks(proposal: str, design: str, specs_dir: Path) -> list[dict]:
    """Run all deterministic QA checks. Returns list of role verdicts."""
    checks = {
        "critic": [
            check_scope_clarity(proposal, design),
            check_risk_identification(proposal, design),
            check_feasibility(proposal, design),
        ],
        "reviewer": [
            check_architecture_soundness(design),
            check_integration_correctness(design),
            check_security_posture(design, specs_dir),
            check_test_coverage(specs_dir),
        ],
        "sme": [
            check_ecosystem_fit(proposal, design),
            check_governance_completeness(specs_dir),
            check_feasibility(proposal, design),
        ],
        "test_engineer": [
            check_test_coverage(specs_dir),
            check_security_posture(design, specs_dir),
        ],
        "explorer": [
            check_unknown_unknowns(design, proposal),
            check_risk_identification(proposal, design),
        ],
    }

    verdicts = []
    for role, role_checks in checks.items():
        total_score = sum(c["score"] for c in role_checks)
        max_score = len(role_checks) * 10
        all_findings = []
        for c in role_checks:
            all_findings.extend(c["findings"])

        normalized = total_score / max_score if max_score > 0 else 0

        if normalized >= 0.8:
            verdict = "APPROVE"
        elif normalized >= 0.5:
            verdict = "CONCERNS"
        else:
            verdict = "REJECT"

        assessed = [c["criterion"] for c in role_checks]
        unmet = [c["criterion"] for c in role_checks if c["score"] < 7]

        verdicts.append(
            {
                "agent": role,
                "verdict": verdict,
                "confidence": round(normalized, 2),
                "findings": all_findings,
                "criteriaAssessed": assessed,
                "criteriaUnmet": unmet,
                "durationMs": 0,
            }
        )

    return verdicts


# ── Dispatch Mode: Generate Agent Manifests ─────────────────────────────


def generate_dispatch_manifest(proposal: str, design: str, specs_dir: Path) -> dict:
    """Generate a dispatch manifest for OpenCode subagent execution."""
    manifest = {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "mode": "dispatch",
        "context": {
            "proposal_excerpt": proposal[:2000],
            "design_excerpt": design[:2000],
            "specs_count": len(list(specs_dir.glob("*/spec.md"))),
        },
        "dispatches": [],
    }

    for role, config in QA_ROLES.items():
        dispatch = {
            "role": role,
            "name": config["name"],
            "focus": config["focus"],
            "prompt_template": (
                f"You are the {config['name']}. "
                f"Your focus: {config['focus']}.\n\n"
                f"Assess the following integration plan against these criteria: "
                f"{', '.join(config['criteria'])}.\n\n"
                f"PROPOSAL:\n{proposal[:3000]}\n\n"
                f"DESIGN:\n{design[:3000]}\n\n"
                f'Return JSON: {{"verdict": "APPROVE|CONCERNS|REJECT", '
                f'"confidence": 0.0-1.0, "findings": [...], '
                f'"criteriaAssessed": [...], "criteriaUnmet": [...]}}'
            ),
        }
        manifest["dispatches"].append(dispatch)

    return manifest


# ── Main Entry Point ───────────────────────────────────────────────────


def run_qa_gates(mode: str = "auto") -> dict:
    """Run QA gates and return combined verdict."""
    proposal_file = PLAN_DIR / "proposal.md"
    design_file = PLAN_DIR / "design.md"
    specs_dir = PLAN_DIR / "specs"

    if not proposal_file.exists():
        return {"verdict": "REJECT", "reason": "proposal.md not found", "gates": []}
    if not design_file.exists():
        return {"verdict": "REJECT", "reason": "design.md not found", "gates": []}

    proposal = proposal_file.read_text()
    design = design_file.read_text()

    if mode == "dispatch":
        manifest = generate_dispatch_manifest(proposal, design, specs_dir)
        DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = DISPATCH_DIR / f"qa-manifest-{manifest['run_id']}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        return {
            "verdict": "DISPATCH",
            "manifest": str(manifest_path),
            "roles": len(manifest["dispatches"]),
        }

    # Auto mode: deterministic checks
    verdicts = run_auto_checks(proposal, design, specs_dir)

    # Aggregate
    approves = sum(1 for v in verdicts if v["verdict"] == "APPROVE")
    concerns = sum(1 for v in verdicts if v["verdict"] == "CONCERNS")
    rejects = sum(1 for v in verdicts if v["verdict"] == "REJECT")

    if rejects > 0:
        overall = "REJECT"
    elif concerns > 2:
        overall = "CONCERNS"
    elif approves >= 3:
        overall = "APPROVE"
    else:
        overall = "CONCERNS"

    all_findings = []
    for v in verdicts:
        all_findings.extend(v["findings"])

    avg_confidence = (
        sum(v["confidence"] for v in verdicts) / len(verdicts) if verdicts else 0
    )

    return {
        "verdict": overall,
        "confidence": round(avg_confidence, 2),
        "gates": verdicts,
        "summary": {
            "approve": approves,
            "concerns": concerns,
            "reject": rejects,
            "total": len(verdicts),
        },
        "findings": all_findings,
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    result = run_qa_gates(mode)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["verdict"] in ("APPROVE", "DISPATCH") else 1


if __name__ == "__main__":
    sys.exit(main())
