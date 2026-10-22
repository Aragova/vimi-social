import subprocess
import sys


def test_source_task_service_imports_in_fresh_interpreter() -> None:
    """Protect the bot bootstrap order from source/Telegram package import cycles."""
    completed = subprocess.run(
        [sys.executable, "-c", "import vimi_social.source.service"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
