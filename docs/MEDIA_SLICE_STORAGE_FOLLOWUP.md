# Storage follow-up

The current media slice uses a content-addressed local media root to establish secure-ingest correctness on a single media-worker host. Before horizontal media-worker scaling, promote finalized assets into shared object storage and persist a storage key rather than relying on a host-local path. Preserve the same SHA-256 lineage and tenant isolation when that follow-up is implemented.
