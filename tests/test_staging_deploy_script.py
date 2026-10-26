from pathlib import Path


def test_staging_deploy_recreates_rebuilt_runtime_services() -> None:
    script = Path("scripts/deploy_staging.sh").read_text(encoding="utf-8")

    assert (
        "compose up -d --wait --no-deps --force-recreate local-ai visual-ai"
        in script
    )
    assert (
        "compose up -d --no-deps --force-recreate "
        "bot worker media-worker destination-worker api"
        in script
    )
