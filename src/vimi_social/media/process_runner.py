import asyncio
import math
import os
import signal
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from vimi_social.media.secure_ingest.errors import ProcessLimitError


@dataclass(frozen=True, slots=True)
class ProcessLimits:
    timeout_seconds: float = 10.0
    max_output_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive value")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class MediaToolRunner:
    def __init__(self, limits: ProcessLimits | None = None) -> None:
        self._limits = limits or ProcessLimits()

    async def run(self, argv: Sequence[str], *, cwd: Path) -> ProcessResult:
        if not argv or not argv[0]:
            raise ValueError("argv must contain an executable")
        if os.name != "posix":
            raise ProcessLimitError("helper process-group isolation requires a POSIX worker")
        cwd.mkdir(parents=True, exist_ok=True)
        env = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise ProcessLimitError("helper process could not be started") from exc
        if process.stdout is None or process.stderr is None:
            await _terminate_group(process)
            raise ProcessLimitError("helper process pipes were not created")

        total_output = 0

        async def read_limited(stream: asyncio.StreamReader) -> bytes:
            nonlocal total_output
            collected = bytearray()
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    return bytes(collected)
                total_output += len(chunk)
                if total_output > self._limits.max_output_bytes:
                    raise ProcessLimitError("helper process exceeded captured-output limit")
                collected.extend(chunk)

        wait_task = asyncio.create_task(process.wait())
        stdout_task = asyncio.create_task(read_limited(process.stdout))
        stderr_task = asyncio.create_task(read_limited(process.stderr))
        try:
            returncode, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(wait_task, stdout_task, stderr_task),
                timeout=self._limits.timeout_seconds,
            )
        except TimeoutError as exc:
            await _terminate_group(process)
            await _settle_tasks(wait_task, stdout_task, stderr_task)
            raise ProcessLimitError("helper process exceeded wall-time limit") from exc
        except ProcessLimitError:
            await _terminate_group(process)
            await _settle_tasks(wait_task, stdout_task, stderr_task)
            raise
        except asyncio.CancelledError:
            await _terminate_group(process)
            await _settle_tasks(wait_task, stdout_task, stderr_task)
            raise
        return ProcessResult(returncode=returncode, stdout=stdout, stderr=stderr)


async def _terminate_group(process: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError as exc:
        raise ProcessLimitError("helper process group did not terminate after kill") from exc


async def _settle_tasks(
    wait_task: asyncio.Task[int],
    stdout_task: asyncio.Task[bytes],
    stderr_task: asyncio.Task[bytes],
) -> None:
    for task in (wait_task, stdout_task, stderr_task):
        if not task.done():
            task.cancel()
    await asyncio.gather(wait_task, stdout_task, stderr_task, return_exceptions=True)
