"""Session-recipe adapter for the existing playback controller.

The composition root supplies exact resolution, queue updates, and a timeline
guard which disables ordinary auto-advance/prefetch while recipe replay owns
the existing player. There is no decoder, command executor, or URL loader here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .recipe_mix import RecipeMixSource, RecipeMixSpec
from .recipe_sources import PreparedRecipeSource
from .session_recipes import ReplayBlocked, ResolvedRecipeMedia


class ExistingPlaybackRecipeHost:
    """Typed adapter for finite replay and verified version-three mix restore.

    Overlap requires the controller's atomic pair boundary and recorded frozen
    gains. Legacy hosts and overlapping recipes without those gains stay refused.
    """

    capabilities = frozenset({"playback", "queue", "queue_tree", "queue_settings", "gain_settings", "crossfade_settings"})

    def __init__(
        self,
        playback: Any,
        *,
        resolve: Callable[[dict], ResolvedRecipeMedia],
        restore_queue: Callable[[dict, dict[str, object]], None],
        configure_queue: Callable[[dict], None],
        set_replay_active: Callable[[bool], None],
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._playback = playback
        self._resolve = resolve
        self._restore_queue = restore_queue
        self._configure_queue = configure_queue
        self._set_replay_active = set_replay_active
        self._cancelled = cancelled
        if callable(getattr(type(self.playback), 'prepare_recipe_mix', None)):
            self.capabilities = self.capabilities | {'overlap', 'program_gain'}

    @property
    def playback(self) -> Any:
        """Resolve the current controller after runtime reconfiguration."""
        return self._playback() if callable(self._playback) else self._playback

    def resolve(self, reference: dict) -> ResolvedRecipeMedia:
        return self._resolve(reference)

    @staticmethod
    def _check_supported(state: dict) -> None:
        if 'program_gain_db' not in state and (state["overlap"] is not None or state["settings"]["crossfade_ms"]):
            raise ReplayBlocked("unsupported_overlap")

    def _configure_settings(self, settings: dict) -> None:
        self.playback.configure_replaygain(**settings["replaygain"])
        self.playback.set_crossfade_seconds(settings["crossfade_ms"] / 1000)
        self._configure_queue({key: settings[key] for key in ("repeat", "consume", "autofill")})

    @staticmethod
    def _queue_media(resolved: dict[str, object]) -> dict[str, object]:
        return {key: value.media if isinstance(value, PreparedRecipeSource) else value
                for key, value in resolved.items()}

    def _play(self, source: object, *, position_ms: int, paused: bool = False) -> None:
        options: dict[str, Any] = {
            "start_at": position_ms / 1000, "probe": False, "origin": "recovery",
            "start_paused": paused,
        }
        if isinstance(source, PreparedRecipeSource):
            options["resolved"] = source.resolved
            source = source.media
        self.playback.play(source, **options)

    def _mix_source(self, source: Any, position_ms: int, gain_db: float) -> RecipeMixSource:
        if isinstance(source, PreparedRecipeSource):
            media, resolved = source.media, source.resolved
        else:
            media, resolved = source, self.playback.resolvers.resolve(source)
        return RecipeMixSource(media, resolved, position_ms / 1000, gain_db)

    def _restore_mix(self, state: dict, resolved: dict[str, object]) -> None:
        """Version-three source gains are frozen, including after promotion."""
        overlap = state['overlap']
        outgoing = self._mix_source(resolved[state['media']], state['position_ms'], state['program_gain_db'])
        incoming = self._mix_source(
            resolved[overlap['incoming']], overlap['incoming_position_ms'], overlap['incoming_gain_db'],
        ) if overlap is not None else None
        from .playback import SAMPLE_RATE

        spec = RecipeMixSpec(
            outgoing, incoming,
            round(overlap['duration_ms'] * SAMPLE_RATE / 1000) if overlap is not None else 0,
            round(overlap['progress_ms'] * SAMPLE_RATE / 1000) if overlap is not None else 0,
            not state['playing'],
        )
        prepared = self.playback.prepare_recipe_mix(spec, cancelled=self._cancelled)
        try:
            self.playback.commit_recipe_mix(prepared, cancelled=self._cancelled)
        finally:
            self.playback.discard_recipe_mix(prepared)

    def restore(self, state: dict, resolved: dict[str, object]) -> None:
        self._check_supported(state)
        self._set_replay_active(True)
        self.playback.clear_prefetch()
        self.playback.stop()
        self._configure_settings(state["settings"])
        self._restore_queue(state, self._queue_media(resolved))
        if state["media"] is not None:
            if 'program_gain_db' in state:
                self._restore_mix(state, resolved)
            else:
                self._play(resolved[state["media"]], position_ms=state["position_ms"], paused=not state["playing"])

    def apply(self, event: dict, state: dict, resolved: dict[str, object]) -> None:
        self._check_supported(state)
        kind, data = event["kind"], event["data"]
        if kind == "media_start":
            self.playback.clear_prefetch()
            if 'program_gain_db' in state:
                self._restore_mix(state, resolved)
            else:
                self._play(resolved[data["media"]], position_ms=data["position_ms"])
        elif kind == "pause":
            self.playback.pause(origin="recovery")
        elif kind == "resume":
            self.playback.resume(origin="recovery")
        elif kind == "seek":
            source = resolved.get(state["media"])
            if 'program_gain_db' in state:
                self._restore_mix(state, resolved)
            elif isinstance(source, PreparedRecipeSource):
                self.playback.seek(data["position_ms"] / 1000, origin="recovery", resolved=source.resolved)
            else:
                self.playback.seek(data["position_ms"] / 1000, origin="recovery")
        elif kind == "stop":
            self.playback.stop()
        elif kind in {"queue_set", "shuffle"}:
            # The committed order, including duplicate occurrences, is authority;
            # do not rerun a random generator or a recommendation algorithm.
            self._restore_queue(state, self._queue_media(resolved))
        elif kind == "queue_settings":
            self._configure_queue(data)
        elif kind == "gain_settings":
            self.playback.configure_replaygain(**{key: value for key, value in data.items() if key != 'program_gain_db'})
            if state.get('program_gain_db') is not None:
                self.playback.set_recipe_program_gain(state['program_gain_db'])
        elif kind == "crossfade_settings":
            self.playback.set_crossfade_seconds(data["crossfade_ms"] / 1000)
        elif kind == "transition":
            self._restore_mix(state, resolved)
        else:
            raise ReplayBlocked("unsupported_host_capability")

    def halt(self) -> None:
        # A missing/changed source must not leave a prebuffered substitute audible.
        try:
            self.playback.clear_prefetch()
            self.playback.stop()
        finally:
            self._set_replay_active(False)

    def is_buffering(self) -> bool:
        state = str(self.playback.snapshot().state)
        if state == "failed":
            raise ReplayBlocked("playback_failed")
        return state in {"resolving", "buffering", "seeking"}
