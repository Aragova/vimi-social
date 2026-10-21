# PoC C — Result Report

**Status:** PASS — CI VERIFIED; FINAL INDEPENDENT FOLLOW-UP REVIEW CLEAN

## Hypothesis

Untrusted remote media can be ingested through a fail-closed network and resource boundary that validates and pins destination addresses, revalidates redirects, bounds response size/time, validates basic media signatures, cleans rejected artifacts, and bounds helper-process execution.

## Verified environment

Final reviewed head before this status-only documentation commit: `1892bcc1be20b2ee9e8b9eb89f566b1532bb6484`.

GitHub Actions on that head completed successfully:

- PoC C run `38897101046` (run #24): PASS
- GitHub runner: Ubuntu 24.04.5 LTS
- Python: 3.12.15
- aiohttp: 3.14.5
- Ruff: 0.17.1 — PASS
- Pyright: 1.1.414 — PASS (`0 errors, 0 warnings, 0 informations`)
- pytest: 8.4.2 — PASS (`51 passed`)
- PoC A regression run #74: PASS
- PoC B regression run #51: PASS

The final focused Codex review on `1892bcc` completed with:

- `has_any_findings=false`
- `has_unresolved_findings=false`
- status `completed`

No additional correctness findings were raised against the final post-fix implementation and report.

## Automated verification

The suite machine-verifies these properties:

1. URL handling permits only supported HTTP/HTTPS forms and rejects unsupported schemes, credentials, and disallowed ports.
2. Destination validation rejects non-public/disallowed addresses, including explicit IPv4/IPv6 multicast rejection, and mixed safe/unsafe DNS answers fail closed.
3. DNS resolution is explicitly bounded before connection and the validated address set is carried into the pinned HTTP transport.
4. Automatic redirects are disabled and each redirect target is parsed, resolved, and validated again.
5. HTTP connect/read/total timeout values are finite and strictly positive; zero, negative, NaN, and infinite values are rejected.
6. aiohttp session/connector cleanup occurs when opening a request is cancelled.
7. Response byte limits are enforced from Content-Length when possible and again while streaming; non-identity Content-Encoding is rejected.
8. Basic media signatures and declared Content-Type policy must agree.
9. Rejected and cancelled ingest paths clean temporary state and temporary descriptor ownership is cancellation-safe.
10. Content-addressed final publication is settled before cancellation propagates, does not blindly overwrite an existing digest-named artifact, and becomes an irrevocable commit point once visible.
11. A cancelled fetch cannot remove a digest artifact after another concurrent fetch has adopted the same published path.
12. Accepted artifact names are derived from locally computed SHA-256 plus detected media extension rather than remote filenames.
13. Helper processes use argv-style execution, minimal environment, bounded wall time and captured output, and execute in a dedicated POSIX process group/session.
14. Helper wall-time configuration itself must be finite and positive; zero, negative, NaN, and infinite values are rejected before execution.
15. Wall-time failure terminates helper descendants before they can continue work.
16. Captured-output-limit failure terminates the whole helper process group, including a delayed descendant.
17. Caller cancellation terminates the helper process group and settles subprocess wait/stdout/stderr tasks.

## Findings discovered during implementation and independent review

### 1. Validation and transport must share the same destination decision

Policy resolution and network connection cannot be separate DNS decisions. The validated address set is passed directly into a static aiohttp resolver for the request.

### 2. Mixed DNS answers must fail closed

A hostname resolving to both allowed and disallowed addresses is rejected rather than filtering only the disallowed answers.

### 3. Public/global classification alone is insufficient

Independent review found multicast destinations that require explicit rejection in addition to ordinary global/public classification. IPv4 and IPv6 regression tests cover this case.

### 4. DNS resolution is part of the fetch deadline

The initial implementation bounded aiohttp but not the preceding hostname lookup. Resolution now has an explicit timeout derived from the fetch configuration.

### 5. Timeout configuration must not disable its own bounds

Independent review found that zero-valued aiohttp timeout fields can disable the corresponding timeout. `FetchTimeouts` rejects zero, negative, NaN, and infinite connect/read/total values, and CI verifies the validation.

### 6. Cancellation must own network cleanup

Cancellation during request open closes the aiohttp session/connector before propagation.

### 7. Response size needs declared and streamed enforcement

Content-Length provides early rejection but is not trusted as the only bound. Streamed bytes are counted independently and declared length is checked against the body actually received.

### 8. Automatic decompression changes resource accounting

The ingest boundary requests identity encoding, disables aiohttp auto-decompression, and rejects non-identity Content-Encoding.

### 9. Temporary-file operations require deterministic cancellation semantics

Independent review found cancellation races around offloaded file operations. Write/fsync operations are shielded and settled, descriptor ownership is single-owner, and cleanup does not double-close a descriptor.

### 10. Final artifact publication is an external side effect with a commit point

A later review found that rollback-style cancellation cleanup was unsafe under concurrent identical fetches: one fetch could publish a digest artifact, another fetch could adopt it, and the first could then remove the shared artifact while propagating cancellation.

The final contract is monotonic: once the content-addressed `final_path` becomes visible, publication is an irrevocable commit point. Cancellation still waits for the promotion operation to settle and temporary state is cleaned, but a visible final artifact is not removed by cancellation cleanup. CI contains a coordinated concurrent regression case proving that a successful adopter keeps a valid path even when the original publisher is cancelled.

### 11. Helper limits must apply to the complete process tree

The runner uses a separate POSIX session/process group and terminates the whole group on wall-time failure, output-limit failure, or caller cancellation. CI contains descendant-process regression coverage for both wall-time and captured-output-limit paths.

### 12. Helper timeout configuration must itself remain bounded

Independent review found that `ProcessLimits(timeout_seconds=float("inf"))` satisfied the previous positive-only validation and could remove the finite wall-time guarantee. `ProcessLimits.timeout_seconds` now requires a finite positive value, with regression coverage for zero, negative, NaN, and positive/negative infinity.

### 13. Test evidence must match report claims exactly

Independent review found an earlier report claim about output-limit descendant cleanup that lacked direct descendant-process evidence. A dedicated output-limit descendant regression test was added and passes in CI.

## Architecture changes required for ViMi Social Architecture 1.0

PoC C supports these contracts:

- remote URLs and uploaded media are untrusted input;
- only explicitly supported URL schemes/ports are allowed and URL credentials are rejected;
- every resolved address must satisfy the destination policy, including explicit multicast rejection;
- DNS resolution and HTTP connect/read/total timeout values must be finite, positive, and bounded;
- helper-process timeout values must also be finite and positive;
- the validated address set must be bound to the actual network connection;
- every redirect must pass the same validation process and automatic redirect following must remain disabled;
- response limits must be enforced before and during streaming and must not be bypassed by HTTP decompression;
- cancellation must close network resources and deterministically settle temporary-file work;
- content-addressed finalization must not blindly overwrite an existing digest artifact;
- once a content-addressed final artifact is published and visible to concurrent consumers, publication is an irrevocable commit point rather than a rollbackable side effect;
- media signature checks are only an ingest gate, not proof that a codec/container is safe to decode;
- media helpers must use argv-style execution, minimal environment, bounded runtime/output, and whole-process-group termination on timeout, limit failure, or cancellation;
- production media workers must add CPU/memory/filesystem/network isolation beyond what this PoC demonstrates.

## Limitations

This PoC does not claim complete codec/container validation, malware detection, decompression-bomb analysis for arbitrary downstream codecs, production-grade CPU/memory/cgroup sandboxing, filesystem namespaces, seccomp, or no-network execution for FFmpeg/ffprobe.

The media signature checks intentionally validate only basic file signatures/container markers and declared Content-Type compatibility. The helper process-group implementation is POSIX-oriented for the intended Linux media-worker environment.

A caller cancelled after final publication may receive `CancelledError` while the complete validated content-addressed artifact remains stored. This is deliberate: publication is treated as an irreversible commit point once another concurrent fetch could observe or adopt it.

## Final verdict

**PASS — machine verification is green and the final focused independent follow-up review is clean. PoC C is suitable as Architecture 1.0 evidence for the secure media-ingest boundary.**
