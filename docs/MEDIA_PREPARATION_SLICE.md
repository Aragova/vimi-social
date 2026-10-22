# Media preparation vertical slice

This slice adds the first production path from a selected Scout candidate to a rights-gated, securely ingested, technically probed media asset.

## Flow

1. A Telegram user selects a persisted Scout candidate.
2. ViMi creates one durable `media_preparation` record for that candidate.
3. Acquisition remains blocked until a legitimate rights basis is confirmed.
4. Rights confirmation reserves `video_second_processed` usage under the stable media-preparation operation key.
5. Temporal dispatches acquisition and probing to the isolated media task queue.
6. The media worker validates the remote destination, pins the approved DNS result, manually revalidates redirects, streams with strict limits, verifies the media signature, and promotes the file by SHA-256 digest.
7. `ffprobe` runs through a bounded helper-process runner.
8. A conservative metadata/text baseline classifier records adult/sensitive signals without pretending to be a full visual classifier.
9. The resulting `media_asset` preserves lineage back to the candidate and source task.
10. The main worker returns the preparation result to Telegram through the existing idempotent outgoing-message state machine.

## Security boundary

The media worker is intentionally separate from the main worker. It does not construct X or Telegram clients. Deployment should provide only the database, Temporal, media-root/storage configuration, and the `ffprobe` executable required by this activity worker.

The secure ingest boundary accepts only HTTP/HTTPS URLs, rejects credentials and non-default ports, rejects any non-public DNS answer, pins the validated addresses for the connection, disables automatic redirects and decompression, revalidates every redirect hop, rejects HTTPS-to-HTTP downgrade, bounds response bytes and time, verifies media signatures against declared content type, and uses cancellation-safe content-addressed promotion.

## Deliberate limit of this slice

The baseline classifier uses source metadata and text signals. `NO_ADULT_SIGNAL_DETECTED` means only that these baseline checks did not find an adult signal; it is not a visual-content safety verdict. Frame/scene-level visual classification belongs with the later SceneDetector / SceneRanker pipeline.

The current content-addressed media root is suitable for the first single-node vertical slice. Promotion into shared object storage is still required before horizontally scaling media workers across hosts.
