# PoC C — Secure Media Ingest Validation

## Hypothesis

ViMi Social can accept untrusted remote-media URLs without allowing the media-ingest path to reach non-public network destinations, silently follow an unsafe redirect, download unbounded response bodies, trust remote filenames, or leave unbounded helper processes running.

## Must prove

1. Only `http` and `https` URLs are accepted; URL credentials and non-default ports are rejected.
2. Hostnames are resolved before connection and every resolved address must satisfy a public-address policy.
3. The HTTP transport connects only to the validated/pinned address set while preserving the original hostname for HTTP/TLS semantics.
4. DNS results are not reused across redirect hops; every redirect target is parsed, resolved, and validated again.
5. Redirects to a non-public destination, unsupported scheme, redirect cycle, excessive redirect chain, or HTTPS-to-HTTP downgrade are rejected.
6. A declared `Content-Length` above the configured limit is rejected before the body is consumed.
7. Streaming bodies without a trustworthy size declaration are still stopped at the configured byte limit.
8. Compressed HTTP bodies are not transparently expanded in the ingest boundary; non-identity `Content-Encoding` is rejected.
9. Downloaded bytes must match a small explicit media-signature allowlist and an allowed declared content type.
10. Temporary files are removed on rejected or interrupted ingest paths, and accepted files use locally derived names rather than URL-provided filenames.
11. Media helper processes use an argument-vector API (`shell=False`), bounded wall time, bounded captured output, and a minimal environment.

## Network destination contract

The default address policy is fail-closed:

```text
URL
  ↓
parse + normalize
  ↓
resolve hostname
  ↓
all resolved addresses must be public/global
  ↓
pin validated address set into HTTP connector
  ↓
request exactly one hop (automatic redirects disabled)
```

Any redirect starts the same process again from URL parsing. A hostname that resolves to a mixture of public and non-public addresses is rejected rather than selecting only the public subset.

The production transport must not validate one address and then allow a separate resolver to choose a different connection address. The PoC therefore passes the validated address set directly into a custom connector resolver.

## Resource contract

The PoC enforces configurable limits for:

- maximum response bytes;
- maximum redirect hops;
- connect/read/total HTTP timeouts;
- helper-process wall time;
- helper-process captured output.

HTTP automatic decompression is disabled. The ingest layer requests `Accept-Encoding: identity` and rejects a non-identity response encoding.

## Media validation contract

The remote `Content-Type` header is not sufficient by itself. The PoC also inspects a bounded prefix and recognizes only a small explicit set of signatures used for architecture validation: JPEG, PNG, GIF, WebP, MP4-family, WebM/Matroska, MP3, Ogg, and WAV.

This signature check is intentionally basic. It proves that arbitrary HTML/text is not accepted solely because a server labels it as media. It is not a substitute for decoder sandboxing or complete format validation.

## Negative validation cases

- local/private/link-local/unspecified/reserved destination addresses;
- mixed public and non-public DNS answers;
- redirect from an allowed public URL to a non-public destination;
- redirect loop and redirect-count exhaustion;
- unsupported URL scheme, URL credentials, or non-default port;
- oversized `Content-Length`;
- chunked/streamed response that crosses the byte limit;
- declared length that does not match the received body;
- non-identity content encoding;
- declared media type with unrecognized bytes;
- helper process that exceeds its wall-time or output budget.

## PASS criteria

```text
non-public destinations are rejected before transport connection
validated addresses are pinned into the connector
all redirect hops are revalidated
no response can exceed the configured byte budget
rejected downloads leave no temporary artifact
accepted artifacts use locally derived names and recorded SHA-256
helper processes are bounded and do not inherit arbitrary environment secrets
```

A green CI suite is required. Code inspection alone is not sufficient for PASS.

## Non-goals

This PoC does not prove that FFmpeg or any specific codec parser is vulnerability-free, does not implement malware scanning, and does not replace production container/cgroup isolation. Architecture 1.0 must still place media parsing/transcoding in an isolated media-worker boundary with minimal credentials, restricted network access, ephemeral scratch storage, and platform-level CPU/memory limits.
