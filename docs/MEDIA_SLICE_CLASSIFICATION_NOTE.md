# Classification note

`NO_ADULT_SIGNAL_DETECTED` is intentionally narrower than `SAFE`. The first media slice only evaluates source metadata and text signals. Visual/frame classification must be added later and should be able to upgrade the classification without erasing source provenance or prior classifier evidence.
