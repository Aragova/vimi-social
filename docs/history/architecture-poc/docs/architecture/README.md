# Architecture documentation

## Current status

The current full architecture baseline is **0.10**. It is deliberately not frozen as Architecture 1.0 yet.

PoCs A–D have passed and generated amendments that are recorded in [`POST_POC_DECISIONS.md`](POST_POC_DECISIONS.md). PoC E remains before the Red-Team v2 gate.

## Document precedence

```text
POST_POC_DECISIONS.md
        ↓ amends
ARCHITECTURE_BASELINE_0_10.md
        ↓ was created from
RED_TEAM_AUDIT_V1.md + ARCHITECTURE_BASELINE_0_9.md
```

If an executable PoC report proves a stricter contract than Baseline 0.10, the PoC result wins and must be carried into Architecture 1.0.

## Files

- `ARCHITECTURE_BASELINE_0_10.md` — comprehensive current pre-1.0 architecture.
- `POST_POC_DECISIONS.md` — validated amendments from PoCs A–D.
- `RED_TEAM_AUDIT_V1.md` — architecture review of Baseline 0.9.
- `ARCHITECTURE_BASELINE_0_9.md` — historical baseline retained for traceability.

## Next architecture gate

Architecture 1.0 requires all five PoCs, Red-Team v2, and reconciliation of all PoC findings into a single frozen architecture document.
