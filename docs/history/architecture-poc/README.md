# ViMi Social documentation index

This repository is the **disposable architecture laboratory** for ViMi Social. It is not the production ViMi Social repository.

The purpose of this documentation pack is to keep the product concept, architecture history, executable PoC evidence, and the path to Architecture 1.0 in one place on GitHub.

## Canonical document order

Until Architecture 1.0 is frozen, use this order:

1. **Validated post-PoC architecture decisions** — executable amendments proved by PoCs A–E.
2. **Open Red-Team v2 findings** — release-gate constraints that the final architecture must resolve.
3. **Architecture Baseline 0.10** — current full pre-1.0 baseline.
4. **Red-Team Audit v1** — historical review that drove the 0.10 changes.
5. **Architecture Baseline 0.9** — historical predecessor only.

Architecture 1.0 will replace this chain only after Red-Team v2 closes its release-blocking findings.

## Product and architecture

- [Product concept](product/PRODUCT_CONCEPT.md)
- [Architecture documentation guide](architecture/README.md)
- [Architecture Baseline 0.10](architecture/ARCHITECTURE_BASELINE_0_10.md)
- [Post-PoC architecture decisions](architecture/POST_POC_DECISIONS.md)
- [Red-Team Audit v2 — current gate](architecture/RED_TEAM_AUDIT_V2.md)
- [Red-Team Audit v1](architecture/RED_TEAM_AUDIT_V1.md)
- [Architecture Baseline 0.9](architecture/ARCHITECTURE_BASELINE_0_9.md)
- [Roadmap and architecture gate](ROADMAP.md)

## Executable architecture evidence

| PoC | Topic | Status | Evidence |
|---|---|---|---|
| A | Temporal durability, identity, UNKNOWN reconciliation, worker evolution | PASS | [`poc_a_temporal/REPORT.md`](../poc_a_temporal/REPORT.md) |
| B | PostgreSQL RLS and tenant isolation | PASS | [`poc_b_tenant_isolation/REPORT.md`](../poc_b_tenant_isolation/REPORT.md) |
| C | Secure remote media ingest | PASS | [`poc_c_secure_media_ingest/REPORT.md`](../poc_c_secure_media_ingest/REPORT.md) |
| D | Async platform lifecycle and safe retry | PASS | [`poc_d_async_platform_lifecycle/REPORT.md`](../poc_d_async_platform_lifecycle/REPORT.md) |
| E | Usage concurrency, reservations, append-only ledger | PASS | [`poc_e_usage_concurrency/REPORT.md`](../poc_e_usage_concurrency/REPORT.md) |

## Current gate

**Red-Team v2 is IN PROGRESS.** The first pass attacks composition boundaries rather than repeating isolated PoC tests and has identified open Critical/High findings requiring architecture changes and targeted composition evidence. Architecture 1.0 is blocked until the v2 release criteria are met.
