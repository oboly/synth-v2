"""Small lifecycle emitter for read-only research CLI runners."""
from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable
from typing import Any


class RunnerLifecycle:
    def __init__(self, *, runner: str, heartbeat_seconds: float = 15.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.runner = runner
        self.heartbeat_seconds = heartbeat_seconds
        self.clock = clock
        self.started_at = clock()
        self._terminal_emitted = False
        self._phase: str | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._previous_handlers: dict[int, Any] = {}
        self.interruption_signal: str | None = None

    def emit(self, event: str, **fields: Any) -> None:
        payload = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        print(f"{event} runner={self.runner} elapsed_seconds={self.clock() - self.started_at:.3f}" + (f" {payload}" if payload else ""), flush=True)

    def start(self, **fields: Any) -> None:
        self.emit("STARTED", **fields)

    def _heartbeat_loop(self, phase: str) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_seconds):
            self.emit("HEARTBEAT", phase=phase)

    def phase_started(self, phase: str, **fields: Any) -> None:
        self.stop_heartbeat()
        self._phase = phase
        self.emit(f"{phase}_STARTED", **fields)
        if self.heartbeat_seconds > 0:
            self._heartbeat_stop.clear()
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(phase,), daemon=True)
            self._heartbeat_thread.start()

    def phase_finished(self, phase: str, **fields: Any) -> None:
        self.stop_heartbeat()
        self.emit(f"{phase}_FINISHED", **fields)
        self._phase = None

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.heartbeat_seconds * 2))
        self._heartbeat_thread = None

    @property
    def heartbeat_running(self) -> bool:
        return self._heartbeat_thread is not None and self._heartbeat_thread.is_alive()

    @property
    def current_phase(self) -> str | None:
        return self._phase

    def _signal_handler(self, signum: int, _frame: Any) -> None:
        self.interruption_signal = signal.Signals(signum).name
        raise KeyboardInterrupt(self.interruption_signal)

    def install_signal_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._signal_handler)

    def restore_signal_handlers(self) -> None:
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)
        self._previous_handlers.clear()

    def terminal(self, event: str, **fields: Any) -> None:
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        self.stop_heartbeat()
        self.emit(event, **fields)

    def close(self) -> None:
        self.stop_heartbeat()
        self.restore_signal_handlers()
