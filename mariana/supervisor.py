"""Bounded retry, failover, output recovery, and cancellation."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import cast

from .models import MediaRef, MediaSource
from .output_devices import OutputDeviceInfo
from .playback import PlaybackController, PlaybackError
from .sources import FailureCode, MediaFailure, ResolverRegistry


class PlaybackSupervisor:
    NETWORK_DELAYS = (1.0, 2.0, 4.0)
    RADIO_DELAYS = (2.0, 5.0, 15.0, 30.0)

    def __init__(
        self,
        controller: PlaybackController,
        *,
        resolvers: ResolverRegistry | None = None,
        wait: Callable[[float], bool] | None = None,
        output_poll_interval: float = 0.75,
    ) -> None:
        self.controller = controller
        self.resolvers = resolvers or controller.resolvers
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._recovering = False
        self._requested: MediaRef | None = None
        self._output_poll_interval = max(0.1, float(output_poll_interval))
        self._output_monitor_stop = threading.Event()
        self._output_monitor: threading.Thread | None = None
        self.on_terminal_failure: Callable[[MediaRef, MediaFailure], None] | None = None
        self.metrics = {
            "retries": 0,
            "resolver_refreshes": 0,
            "endpoint_changes": 0,
            "output_recoveries": 0,
            "output_device_changes": 0,
            "cancellations": 0,
        }
        self._wait = wait or self._cancel.wait
        controller.on_failure = self._on_decoder_failure

    def _failure(self, error: BaseException, media: MediaRef) -> MediaFailure:
        if isinstance(error, MediaFailure):
            return error
        if isinstance(error, PlaybackError):
            return MediaFailure(
                FailureCode.DECODE,
                media.source,
                str(error),
                retryable=media.source != MediaSource.LOCAL,
                cause=error,
            )
        return self.resolvers.classify_failure(error, media)

    @staticmethod
    def _copy_with_uri(media: MediaRef, uri: str) -> MediaRef:
        return MediaRef(
            media.source,
            uri,
            title=media.title,
            artist=media.artist,
            album=media.album,
            duration=media.duration,
            stable_id=media.stable_id,
            resolver_data=dict(media.resolver_data),
            provenance=media.provenance,
            capabilities=media.capabilities,
        )

    def _candidates(self, media: MediaRef) -> list[MediaRef]:
        if media.source != MediaSource.RADIO:
            return [media]
        endpoints = list(dict.fromkeys(media.resolver_data.get("endpoints") or [media.original_uri]))
        return [self._copy_with_uri(media, endpoint) for endpoint in endpoints]

    def play(self, media: MediaRef, *, start_at: float = 0, probe: bool = True) -> MediaRef:
        with self._lock:
            self._cancel.clear()
            self._requested = media
        candidates = self._candidates(media)
        delays = self.RADIO_DELAYS if media.source == MediaSource.RADIO else self.NETWORK_DELAYS
        attempts = 1 if media.source == MediaSource.LOCAL else len(delays) + 1
        last_failure: MediaFailure | None = None
        for attempt in range(attempts):
            if self._cancel.is_set():
                self.metrics["cancellations"] += 1
                raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was cancelled")
            candidate = candidates[attempt % len(candidates)]
            if attempt and len(candidates) > 1:
                self.metrics["endpoint_changes"] += 1
            try:
                result = self.controller.play(candidate, start_at=start_at if attempt == 0 else 0, probe=probe)
                self._start_output_monitor()
                return result
            except Exception as error:
                last_failure = self._failure(error, candidate)
                if not last_failure.retryable or attempt + 1 >= attempts:
                    break
                self.metrics["retries"] += 1
                if media.source == MediaSource.YOUTUBE:
                    self.metrics["resolver_refreshes"] += 1
                delay = last_failure.retry_after or delays[min(attempt, len(delays) - 1)]
                if self._wait(delay):
                    self.metrics["cancellations"] += 1
                    raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was cancelled") from None
        assert last_failure is not None
        if self.on_terminal_failure:
            self.on_terminal_failure(media, last_failure)
        raise last_failure

    def _on_decoder_failure(self, media: MediaRef, failure: MediaFailure) -> None:
        with self._lock:
            if self._recovering or self._cancel.is_set() or self._requested is None:
                return
            self._recovering = True

        def recover() -> None:
            try:
                self.play(self._requested or media)
            except MediaFailure:
                pass
            finally:
                with self._lock:
                    self._recovering = False

        threading.Thread(target=recover, name="mariana-playback-recovery", daemon=True).start()

    def recover_output(self, device: OutputDeviceInfo | None = None) -> None:
        last_error: BaseException | None = None
        for _ in range(3):
            if self._cancel.is_set():
                raise MediaFailure(FailureCode.CANCELLED, MediaSource.LOCAL, "Output recovery was cancelled")
            try:
                if device is None:
                    self.controller.recover_output()
                else:
                    self.controller.recover_output(device)
                self.metrics["output_recoveries"] += 1
                return
            except Exception as error:
                last_error = error
                self._wait(0.25)
        raise MediaFailure(
            FailureCode.OUTPUT_DEVICE,
            self._requested.source if self._requested else MediaSource.LOCAL,
            "The audio output device could not be recovered",
            cause=last_error,
        )

    def _start_output_monitor(self) -> None:
        provider = getattr(self.controller, "default_output_device", None)
        if not callable(provider) or not hasattr(self.controller, "active_output_device"):
            return
        if self._output_monitor and self._output_monitor.is_alive():
            return
        self._output_monitor_stop.clear()

        def monitor() -> None:
            while not self._output_monitor_stop.wait(self._output_poll_interval):
                try:
                    self._sync_output_device()
                except MediaFailure as error:
                    if error.code == FailureCode.CANCELLED and self._output_monitor_stop.is_set():
                        continue
                    reporter = getattr(self.controller, "report_output_error", None)
                    if callable(reporter):
                        reporter(str(error))
                except Exception as error:
                    reporter = getattr(self.controller, "report_output_error", None)
                    if callable(reporter):
                        reporter(f"Audio output monitoring failed: {error}")

        self._output_monitor = threading.Thread(
            target=monitor,
            name="mariana-output-device-monitor",
            daemon=True,
        )
        self._output_monitor.start()

    def _sync_output_device(self) -> bool:
        provider = getattr(self.controller, "default_output_device", None)
        if not callable(provider) or not hasattr(self.controller, "active_output_device"):
            return False
        desired = cast(OutputDeviceInfo, provider())
        active = cast(OutputDeviceInfo | None, self.controller.active_output_device)
        stream_active = bool(getattr(self.controller, "output_stream_active", True))
        if active is not None and active.key == desired.key and stream_active:
            return False
        self.recover_output(desired)
        if active is None or active.key != desired.key:
            self.metrics["output_device_changes"] += 1
        return True

    def _stop_output_monitor(self) -> None:
        self._output_monitor_stop.set()
        monitor = self._output_monitor
        if monitor and monitor is not threading.current_thread():
            monitor.join(timeout=1)
        self._output_monitor = None

    def stop(self) -> None:
        self._cancel.set()
        self._stop_output_monitor()
        self.controller.stop()

    def close(self) -> None:
        self._cancel.set()
        self._stop_output_monitor()
        self.controller.close()
