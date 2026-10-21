# AGENTS.md

## Purpose

This repository is a disposable architecture laboratory for ViMi Social. It is **not** the production ViMi Social repository and must not depend on the existing ViMi Telegram production project.

## Required workflow

1. Read this file before changing code.
2. Define the hypothesis and PASS/FAIL criteria before implementation.
3. Prefer tests first for architecture claims.
4. Do not weaken tests only to make a PoC pass.
5. Record unexpected findings in the PoC report.
6. Keep each PoC isolated from the others unless shared test infrastructure is explicitly justified.

## Architecture rules

- No runtime imports from the legacy `telegram-forwarder-bot` project.
- No production credentials or real user data.
- No plaintext secrets in source, logs, fixtures, CI variables, or reports.
- External side effects must have an idempotency and unknown-outcome strategy.
- Tenant isolation tests must use production-like database roles where applicable.
- AI components must not receive unrestricted shell, database, or secret access.
- Media tests must treat URLs and uploaded media as untrusted input.
- A PoC proves one architecture hypothesis; it should not grow into the production application.

## Code quality

- Python must be typed where practical.
- Keep modules cohesive and small; file length is a guardrail, not a target.
- Prefer explicit domain types over unstructured dictionaries for important state.
- Avoid broad `except Exception` as normal control flow.
- Use deterministic tests and explicit failure injection.

## Validation

A PoC may be marked PASS only when its automated acceptance tests pass in CI and the report explains what was actually demonstrated.
