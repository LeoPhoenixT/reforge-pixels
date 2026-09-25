"""Drain child output while polling cancellation without blocking the caller."""

from __future__ import annotations

import queue
import subprocess
import threading
from collections import deque
from typing import Callable


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def drain_process(
    process: subprocess.Popen[str],
    cancelled: Callable[[], bool] | None = None,
    on_line: Callable[[str], None] | None = None,
    on_tick: Callable[[], None] | None = None,
) -> tuple[int, tuple[str, ...], bool]:
    """Return exit code, bounded output tail, and whether cancellation was requested."""
    output: queue.Queue[str | None] = queue.Queue(maxsize=100)
    stop_reading = threading.Event()
    stream = process.stdout if process.stdout is not None else process.stderr
    assert stream is not None

    def read() -> None:
        try:
            for line in stream:
                while not stop_reading.is_set():
                    try:
                        output.put(line.rstrip(), timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if stop_reading.is_set():
                    break
        finally:
            while not stop_reading.is_set():
                try:
                    output.put(None, timeout=0.1)
                    break
                except queue.Full:
                    continue

    reader = threading.Thread(target=read, name="subprocess-output-reader", daemon=True)
    reader.start()
    tail: deque[str] = deque(maxlen=50)
    ended = False
    was_cancelled = False
    try:
        while not ended or process.poll() is None:
            if cancelled and cancelled():
                was_cancelled = True
                stop_process(process)
            try:
                item = output.get(timeout=0.1)
            except queue.Empty:
                item = ""
            if item is None:
                ended = True
            elif item:
                tail.append(item[-200:])
                if on_line:
                    on_line(item)
            if on_tick and not was_cancelled:
                on_tick()
            if was_cancelled and ended:
                break
        process.wait()
        return process.returncode, tuple(tail), was_cancelled or bool(cancelled and cancelled())
    except BaseException:
        stop_process(process)
        raise
    finally:
        stop_reading.set()
        reader.join(timeout=2)
        stream.close()
