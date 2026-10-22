# Scene analysis and variant planning slice

## Scope

This production slice continues from a rights-gated, securely ingested `MediaAsset` and adds the first durable downstream analysis/planning path:

```text
READY MediaAsset
-> SceneDetector
-> SceneRanker
-> destination capability/compliance preflight
-> VariantPlanner
-> persisted RenderRecipe
-> Telegram result summary
```

It deliberately stops before RenderService and external publication.

## SceneDetector

Scene detection is deterministic and runs inside the isolated media-worker boundary through the existing bounded `MediaToolRunner`. The first implementation uses `ffmpeg` scene-change detection and converts validated cut timestamps into ordered `SceneBoundary` records.

Operational limits include:

- bounded helper-process runtime/output inherited from `MediaToolRunner`;
- a minimum scene duration;
- a maximum scene count;
- attempt-scoped scratch space;
- durable attempt fencing before media-tool work.

A Temporal retry that observes another active analysis attempt does not start a second `ffmpeg` operation. The analysis becomes `FAILED_SAFE` with `ANALYSIS_ATTEMPT_AMBIGUOUS`.

## SceneRanker

The first SceneRanker is deterministic and versioned. It scores scenes using duration and position heuristics so the persistence/planning contracts can run end-to-end without pretending that heuristic output is an AI quality verdict.

Scene-level content classification in this slice is explicitly marked `ASSET_LEVEL_INHERITED`. It does not claim that frames were visually classified.

## Platform preflight

Capability and compliance are represented separately in a versioned destination profile and combined only into an explicit preflight result:

- `DIRECT_ALLOWED`
- `ADAPTATION_REQUIRED`
- `MANUAL_REVIEW_REQUIRED`
- `BLOCKED`

The first destination profile is X organic video. It is intentionally conservative:

- explicit adult content requires manual review and a sensitive-content label path;
- explicit consent/provenance evidence is not inferred from a generic rights confirmation;
- `UNKNOWN` / `POSSIBLY_SENSITIVE` content requires manual review;
- the current metadata/text-only `NO_ADULT_SIGNAL_DETECTED` result is **not** treated as proof of visual safety and therefore also requires review until a visual classifier exists.

A review-required decision may still produce a local draft recipe for preview/preparation, but it never authorizes publication.

## VariantPlanner / RenderRecipe

`VariantPlanner` produces deterministic, versioned plans:

- `PASSTHROUGH` for a technically unchanged draft/direct candidate;
- `CLIP_SEQUENCE` when a destination duration limit requires adaptation;
- no recipe for `BLOCKED`.

`CLIP_SEQUENCE` uses ranked scenes while respecting the destination duration limit and persists the selected segment lineage.

## Durable state

Migration `0008_scene_analysis_variant_planning` adds:

- `media_analysis`
- `media_scene`
- `variant_plan`
- `variant_plan_segment`

All tables use forced PostgreSQL RLS. `media_analysis` has a durable attempt token; scene/plan persistence requires current attempt ownership.

## What remains next

The next production slice should add:

1. frame/scene feature extraction and a real visual scene/content classifier;
2. RenderService that executes persisted RenderRecipes in the isolated media worker;
3. a concrete destination adapter with stable publication operation identity, `UNKNOWN`, and reconciliation;
4. Telegram preview/approval around the rendered variant;
5. staging deployment/manual exercise of the real Telegram -> X discovery -> rights -> ingest -> scenes -> plan path.
