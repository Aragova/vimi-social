# ViMi Social architecture laboratory

This repository is the disposable executable architecture laboratory for **ViMi Social**. It is not the production application repository.

## Current architecture gate

```text
Architecture 0.10
        ↓
PoC A  PASS
PoC B  PASS
PoC C  PASS
PoC D  PASS
PoC E  PASS
        ↓
Red-Team v2  IN PROGRESS  ← CURRENT
        ↓
Architecture 1.0  BLOCKED until v2 findings close
        ↓
production ViMi Social repository
```

The canonical documentation index is [`docs/README.md`](docs/README.md).

## Document precedence

Until Architecture 1.0 is frozen:

1. validated executable PoC findings recorded in [`docs/architecture/POST_POC_DECISIONS.md`](docs/architecture/POST_POC_DECISIONS.md) take precedence where they tighten or clarify an older baseline contract;
2. open Red-Team v2 findings in [`docs/architecture/RED_TEAM_AUDIT_V2.md`](docs/architecture/RED_TEAM_AUDIT_V2.md) are release-gate constraints that Architecture 1.0 must resolve;
3. [`docs/architecture/ARCHITECTURE_BASELINE_0_10.md`](docs/architecture/ARCHITECTURE_BASELINE_0_10.md) is the current pre-1.0 baseline;
4. [`docs/architecture/RED_TEAM_AUDIT_V1.md`](docs/architecture/RED_TEAM_AUDIT_V1.md) explains the findings that produced Architecture 0.10;
5. [`docs/architecture/ARCHITECTURE_BASELINE_0_9.md`](docs/architecture/ARCHITECTURE_BASELINE_0_9.md) is historical context only.

## PoC status

| PoC | Scope | Status |
|---|---|---|
| A | Temporal durability / identity / workflow evolution | PASS |
| B | PostgreSQL tenant isolation / RLS | PASS |
| C | secure media ingest | PASS |
| D | async platform lifecycle / UNKNOWN reconciliation | PASS |
| E | usage concurrency / reservations / ledger | PASS |

All five isolated Architecture 0.10 PoCs remain PASS. **Red-Team v2 is now active** and attacks their composition. Its first adversarial pass found release-blocking cross-system/evidence gaps; Architecture 1.0 remains intentionally unfrozen until those findings are resolved and independently reviewed.

The production ViMi Social repository is still intentionally not created.
