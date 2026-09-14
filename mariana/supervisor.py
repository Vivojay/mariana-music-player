"""Bounded retry, failover, output recovery, and cancellation."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypedDict, cast

from .models import MediaRef, MediaSource
from .output_devices import OutputDeviceInfo
from .playback import PlaybackController, PlaybackError
from .playback_diagnostics import operation, record
from .sources import FailureCode, MediaFailure, ResolverRegistry


class _MediaRequest(TypedDict, total=False):
    request_generation: int


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
        allow_source_recovery: Callable[[], bool] | None = None,
    ) -> None:
        self.controller = controller
        self.resolvers = resolvers or controller.resolvers
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._recovering = False
        self._requested: MediaRef | None = None
        self._request_epoch = 0
        self._closed = False
        self._allow_source_recovery = allow_source_recovery
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

    @operation("supervised_play")
    def play(
        self,
        media: MediaRef,
        *,
        start_at: float = 0,
        probe: bool = True,
        origin: str = "system",
        _expected_epoch: int | None = None,
        _expected_controller_generation: int | None = None,
    ) -> MediaRef:
        if origin == "recovery" and not self._source_recovery_allowed():
            raise MediaFailure(FailureCode.CANCELLED, media.source, "Automatic source recovery is suspended")
        with self._lock:
            if self._closed or (_expected_epoch is not None and _expected_epoch != self._request_epoch):
                raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was replaced")
            if _expected_controller_generation is not None:
                reserve_current = getattr(self.controller, "reserve_media_request_if_current", None)
                generation = (
                    cast(Callable[[int], int | None], reserve_current)(_expected_controller_generation)
                    if callable(reserve_current) else None
                )
                if generation is None:
                    raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was replaced")
            else:
                reserve = getattr(self.controller, "reserve_media_request", None)
                generation = cast(Callable[[], int], reserve)() if callable(reserve) else None
            self._cancel.clear()
            self._requested = media
            self._request_epoch += 1
            epoch = self._request_epoch

        def current() -> bool:
            with self._lock:
                if self._cancel.is_set() or epoch != self._request_epoch:
                    return False
                check = getattr(self.controller, "media_request_is_current", None)
                return generation is None or (callable(check) and check(generation) is True)

        def require_current() -> None:
            if not current():
                raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was replaced")

        request: _MediaRequest = {"request_generation": generation} if generation is not None else {}
        candidates = self._candidates(media)
        delays = self.RADIO_DELAYS if media.source == MediaSource.RADIO else self.NETWORK_DELAYS
        attempts = 1 if media.source == MediaSource.LOCAL else len(delays) + 1
        last_failure: MediaFailure | None = None
        for attempt in range(attempts):
            if not current() or (origin == "recovery" and not self._source_recovery_allowed()):
                self.metrics["cancellations"] += 1
                raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was cancelled")
            candidate = candidates[attempt % len(candidates)]
            if attempt and len(candidates) > 1:
                self.metrics["endpoint_changes"] += 1
                record(4, "retry.endpoint_changed")
            try:
                if origin == "recovery" and self._allow_source_recovery is not None:
                    # Resolve outside controller state: a late response from an
                    # older owner must not prepare/replace a recipe's decoder.
                    resolved = self.resolvers.resolve(candidate, force=True)
                    if not self._source_recovery_allowed() or not current():
                        raise MediaFailure(FailureCode.CANCELLED, media.source, "Automatic source recovery is suspended")
                    result = self.controller.play(
                        candidate, start_at=start_at if attempt == 0 else 0,
                        probe=probe, origin=origin, resolved=resolved, **request,
                    )
                else:
                    result = self.controller.play(
                        candidate,
                        start_at=start_at if attempt == 0 else 0,
                        probe=probe,
                        origin=origin,
                        **request,
                    )
                require_current()
                self._start_output_monitor()
                return result
            except Exception as error:
                require_current()
                last_failure = self._failure(error, candidate)
                record(2, f"attempt.failed.{last_failure.code.value}", attempt=attempt + 1)
                if not last_failure.retryable or attempt + 1 >= attempts:
                    break
                self.metrics["retries"] += 1
                if media.source == MediaSource.YOUTUBE:
                    self.metrics["resolver_refreshes"] += 1
                delay = last_failure.retry_after or delays[min(attempt, len(delays) - 1)]
                record(2, "retry.scheduled", attempt=attempt + 2, delay_seconds=delay)
                if self._wait(delay):
                    self.metrics["cancellations"] += 1
                    record(3, "retry.cancelled")
                    raise MediaFailure(FailureCode.CANCELLED, media.source, "Playback was cancelled") from None
        assert last_failure is not None
        with self._lock:
            require_current()
            if self.on_terminal_failure:
                self.on_terminal_failure(media, last_failure)
        raise last_failure

    def _source_recovery_allowed(self) -> bool:
        if self._allow_source_recovery is None:
            return True
        try:
            return self._allow_source_recovery() is True
        except Exception:
            return False

    def _on_decoder_failure(self, media: MediaRef, failure: MediaFailure) -> None:
        record(2, f"decoder.failed.{failure.code.value}")
        with self._lock:
            if (self._recovering or self._cancel.is_set() or self._requested is None
                    or not self._source_recovery_allowed()):
                return
            self._recovering = True
            requested = self._requested
            epoch = self._request_epoch

        def recover() -> None:
            try:
                self.play(
                    requested, origin="recovery", _expected_epoch=epoch,
                    _expected_controller_generation=failure.request_generation,
                )
            except MediaFailure:
                pass
            finally:
                with self._lock:
                    self._recovering = False

        try:
            threading.Thread(target=recover, name="mariana-playback-recovery", daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._recovering = False
            record(2, "source_recovery.start_failed")

    @operation("supervised_output_recovery")
    def recover_output(
        self, device: OutputDeviceInfo | None = None, *, cancelled: Callable[[], bool] | None = None,
    ) -> None:
        last_error: BaseException | None = None
        for attempt in range(3):
            if self._cancel.is_set() or (cancelled is not None and cancelled()):
                raise MediaFailure(FailureCode.CANCELLED, MediaSource.LOCAL, "Output recovery was cancelled")
            try:
                # Endpoint identity and its route can change during a handoff.
                # Only the first attempt may use the caller's selection.
                if device is None or attempt:
                    self.controller.recover_output()
                else:
                    self.controller.recover_output(device)
                if self._cancel.is_set() or (cancelled is not None and cancelled()):
                    raise MediaFailure(FailureCode.CANCELLED, MediaSource.LOCAL, "Output recovery was cancelled")
                self.metrics["output_recoveries"] += 1
                return
            except Exception as error:
                if isinstance(error, MediaFailure) and error.code == FailureCode.CANCELLED:
                    raise
                last_error = error
                if attempt < 2:
                    delay = (0.25, 0.75)[attempt]
                    record(2, "output_recovery.retry", delay_seconds=delay)
                    if self._wait(delay):
                        raise MediaFailure(
                            FailureCode.CANCELLED, MediaSource.LOCAL, "Output recovery was cancelled"
                        ) from None
        raise MediaFailure(
            FailureCode.OUTPUT_DEVICE,
            self._requested.source if self._requested else MediaSource.LOCAL,
            "The audio output device could not be recovered",
            cause=last_error,
        )

    def _start_output_monitor(self) -> None:
        with self._lock:
            if not self._cancel.is_set():
                self._launch_output_monitor()

    def _launch_output_monitor(self) -> None:
        provider = getattr(self.controller, "default_output_device", None)
        if not callable(provider) or not hasattr(self.controller, "active_output_device"):
            return
        if self._output_monitor and self._output_monitor.is_alive():
            return
        # A timed-out join can leave the old thread inside a native device
        # query. Never clear its stop token when a later playback starts.
        stop = threading.Event()
        self._output_monitor_stop = stop

        def monitor() -> None:
            while not stop.wait(self._output_poll_interval):
                try:
                    self._sync_output_device(cancelled=stop.is_set)
                except MediaFailure as error:
                    if stop.is_set():
                        continue
                    reporter = getattr(self.controller, "report_output_error", None)
                    if callable(reporter):
                        reporter(str(error))
                except Exception:
                    if stop.is_set():
                        continue
                    reporter = getattr(self.controller, "report_output_error", None)
                    if callable(reporter):
                        reporter("Audio output is unavailable; retrying automatically")

        thread = threading.Thread(
            target=monitor,
            name="mariana-output-device-monitor",
            daemon=True,
        )
        self._output_monitor = thread
        try:
            thread.start()
        except RuntimeError:
            # Monitoring is optional recovery infrastructure, not a reason to
            # reject playback that has already opened its output successfully.
            stop.set()
            self._output_monitor = None
            record(2, "output_monitor.start_failed")
            return

    def _sync_output_device(self, *, cancelled: Callable[[], bool] | None = None) -> bool:
        provider = getattr(self.controller, "default_output_device", None)
        if not callable(provider) or not hasattr(self.controller, "active_output_device"):
            return False
        desired = cast(OutputDeviceInfo, provider())
        if cancelled is not None and cancelled():
            return False
        active = cast(OutputDeviceInfo | None, self.controller.active_output_device)
        stream_active = bool(getattr(self.controller, "output_stream_active", True))
        if active is not None and active.key == desired.key and stream_active:
            return False
        self.recover_output(desired, cancelled=cancelled)
        if active is None or active.key != desired.key:
            self.metrics["output_device_changes"] += 1
        return True

    def _detach_output_monitor(self) -> threading.Thread | None:
        with self._lock:
            self._output_monitor_stop.set()
            monitor = self._output_monitor
            self._output_monitor = None
            return monitor

    @staticmethod
    def _join_output_monitor(monitor: threading.Thread | None) -> None:
        if monitor and monitor is not threading.current_thread():
            monitor.join(timeout=1)

    def _stop_output_monitor(self) -> None:
        self._join_output_monitor(self._detach_output_monitor())

    def stop(self) -> None:
        with self._lock:
            self._request_epoch += 1
            self._cancel.set()
            monitor = self._detach_output_monitor()
            reserve = getattr(self.controller, "reserve_media_request", None)
            stop_reserved = getattr(self.controller, "stop_reserved_media_request", None)
            generation = (
                cast(Callable[[], int], reserve)()
                if callable(reserve) and callable(stop_reserved) else None
            )
        try:
            if generation is not None:
                cast(Callable[[int], bool], stop_reserved)(generation)
            else:
                self.controller.stop()
        finally:
            self._join_output_monitor(monitor)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._request_epoch += 1
            self._cancel.set()
            monitor = self._detach_output_monitor()
        try:
            self.controller.close()
        finally:
            self._join_output_monitor(monitor)
