# Demo D — Conditional / ABAC access gate for Bedrock - slide 15

> AWS *Advanced Development with Generative AI* · **Module 10**, slides 25, 26, 28

An interactive **attribute-based access control (ABAC) decision engine** that
gates `bedrock:InvokeModel`, mirroring the slide-25 conditional-access IAM policy.

The slide-28 decision engine takes four inputs and returns allow/deny:

- **User attributes** — role, department
- **Resource attributes** — the model and its risk tier (high-value vs. low-risk)
- **Environment** — MFA present, on corporate network, compliant device, source IP,
  business hours
- **Action** — `bedrock:InvokeModel`

The policy (from slide 25): **high-value** foundation models require MFA + corporate
network + compliant device + an allowed department (`AI-Researchers` /
`Senior-Engineers`) + a source IP inside the corporate CIDR (`203.0.113.0/24`).
**Low-risk** models have relaxed requirements. The Bedrock call only fires when the
decision is ALLOW; otherwise the model is never invoked.

## Run

```bash
cd ~/AdvDevGenAI/10_access_gate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

- **Simulate (default, no AWS):** on ALLOW, shows a canned confirmation; on DENY,
  shows that Bedrock is never called.
- **Live Bedrock:** turn *Simulate* off to make a real `Converse` call when access
  is granted.

Prerequisites for live mode: AWS credentials, Bedrock model access,
`bedrock:InvokeModel`. No AWS resources are created; nothing to tear down.

## How to drive the demo

1. Pick the **high-value** model with a user in `AI-Researchers`, MFA on, corporate
   network on, compliant device, source IP `203.0.113.17` → **ALLOW**.
2. Flip MFA off, or change the source IP to something outside `203.0.113.0/24`, or
   switch department to `Marketing` → **DENY**, with the failing condition named.
3. Switch to the **low-risk** model → relaxed rules allow it with just MFA or
   corporate network.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (user/resource/environment inputs, decision trace) |
| `access_control.py` | Model catalog, ABAC policy, decision engine |
| `bedrock_client.py` | `Converse` wrapper (called only on ALLOW) |

## Important caveat

This evaluates the policy **locally** to teach how an IAM condition (MFA,
`aws:SourceIp`, `PrincipalTag/Department`, etc.) would gate the call. It is **not**
real IAM enforcement — in production AWS IAM evaluates these conditions against the
actual request context. Use this to explain and prototype policy logic, not as a
security control.
