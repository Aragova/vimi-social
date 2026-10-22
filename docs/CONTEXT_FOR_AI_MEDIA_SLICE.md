# Context addendum — rights-gated media preparation

The current production slice extends Scout candidates into a durable media-preparation pipeline.

Key invariants for future changes:

- A public source post is not a reuse license.
- A candidate may carry an official connector media reference, but acquisition must not occur before a legitimate `RightsBasis` is present.
- `media_preparation.operation_key` is the stable logical identity for usage and workflow idempotency.
- Remote media is untrusted input. All HTTP destinations and redirects must pass the secure-ingest policy before bytes are processed.
- The media worker is an isolated activity worker and must not need X or Telegram credentials.
- `MediaProbe` output is deterministic technical metadata; the baseline content classifier is conservative metadata/text classification, not a visual-content verdict.
- `media_asset` must retain tenant/candidate/preparation lineage and remain protected by forced RLS.
- The local content-addressed media root is a single-node boundary only. Shared object-storage promotion is required before horizontal media-worker scaling.
