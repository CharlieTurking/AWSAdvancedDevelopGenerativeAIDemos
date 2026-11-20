"""
Conditional / attribute-based access control for Bedrock
(Module 10, slides 25, 26, 28).

Models the slide-28 ABAC decision engine. Inputs:
  - User attributes        : role, department
  - Resource attributes    : the model and its risk tier (high / low value)
  - Environment            : MFA present, on corporate network, compliant device,
                             source IP, business hours
  - Action                 : bedrock:InvokeModel

The policy mirrors the slide-25 conditional-access example: high-value foundation
models require MFA + corporate network + compliant device + an allowed department
+ a source IP inside the corporate CIDR; lower-risk models have relaxed rules.

IMPORTANT: this is a *local teaching model* of how an IAM policy condition would
gate the call. It is not real IAM enforcement — in production these conditions are
evaluated by AWS IAM against the request context.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

# Model catalog with risk tiers (slide 26 RBAC: not everyone gets every model).
MODELS = {
    "anthropic.claude-sonnet (high-value)": "high",
    "anthropic.claude-haiku (standard)": "low",
    "amazon.titan-text-lite (low-risk)": "low",
}

# Departments allowed to touch high-value models (slide 25 PrincipalTag/Department).
HIGH_VALUE_DEPARTMENTS = {"AI-Researchers", "Senior-Engineers"}

# Corporate network CIDR from the slide-25 example.
CORPORATE_CIDR = ipaddress.ip_network("203.0.113.0/24")


@dataclass
class Principal:
    role: str
    department: str


@dataclass
class Environment:
    mfa_present: bool
    on_corporate_network: bool
    compliant_device: bool
    source_ip: str
    business_hours: bool


@dataclass
class Decision:
    allow: bool
    reasons: list[str]        # all checks evaluated, pass/fail
    blocking: list[str]       # the checks that caused a deny


def _ip_in_corp(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in CORPORATE_CIDR
    except ValueError:
        return False


def evaluate(principal: Principal, model_label: str, env: Environment) -> Decision:
    """ABAC decision for action bedrock:InvokeModel on the given model."""
    tier = MODELS.get(model_label, "high")
    reasons: list[str] = []
    blocking: list[str] = []

    def check(name: str, ok: bool, required: bool = True):
        reasons.append(f"{'✅' if ok else '❌'} {name}")
        if required and not ok:
            blocking.append(name)

    if tier == "high":
        reasons.append("Resource tier: HIGH-VALUE (strict conditions apply)")
        check("MFA present", env.mfa_present)
        check("On corporate network", env.on_corporate_network)
        check("Compliant device", env.compliant_device)
        check(
            f"Department in {sorted(HIGH_VALUE_DEPARTMENTS)}",
            principal.department in HIGH_VALUE_DEPARTMENTS,
        )
        check(
            f"Source IP in {CORPORATE_CIDR}",
            _ip_in_corp(env.source_ip),
        )
    else:
        reasons.append("Resource tier: LOW-RISK (relaxed conditions)")
        # Relaxed: just require authentication context (MFA OR corp network).
        check(
            "Authenticated context (MFA or corporate network)",
            env.mfa_present or env.on_corporate_network,
        )

    return Decision(allow=not blocking, reasons=reasons, blocking=blocking)
