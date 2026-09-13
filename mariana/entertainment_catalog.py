"""Curated discovery data consumed by Home, shared RSS, and existing radio.

An entry names a programme or station, not every item owned by its publisher.
Validation is point-in-time evidence, never a worldwide availability promise.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shlex
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass

from .artwork import ArtworkCancelled, SafeArtworkFetcher
from .models import MediaRef
from .podcast_feeds import MAX_PODCAST_BYTES, episode_media, parse_podcast_feed

VALIDATED_AT = "2026-09-11"


@dataclass(frozen=True)
class CatalogueEntry:
    id: str
    title: str
    publisher: str
    kind: str
    homepage: str
    language: str
    region: str
    category: str
    summary: str
    endpoint: str | None = None
    station_id: str | None = None
    hosting_platform: str | None = None
    status: str = "conditional"
    health: str = "not-checked"
    evidence: str | None = None
    validated_at: str | None = None
    artwork_provenance: str = "Provider feed metadata only; no network artwork permission implied"
    restrictions: str = "Public editions only; availability may vary. No rebroadcast or archive permission."

    @property
    def native(self) -> bool:
        return self.status == "supported" and bool(self.endpoint or self.station_id)

    @property
    def actions(self) -> tuple[str, ...]:
        return ("details", "official-link", "play", "queue") if self.native else ("details", "official-link")

    def binding(self) -> tuple[str, str]:
        return self.id, hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


ENTRIES = (
    CatalogueEntry("groove-salad", "SomaFM Groove Salad", "SomaFM", "station",
                   "https://somafm.com/groovesalad/", "en", "US", "Music Radio",
                   "Ambient and downtempo. Existing Mariana station; live radio, not a finite download.",
                   station_id="somafm-groove-salad", status="supported", health="existing-station",
                   evidence="https://somafm.com/listen/", validated_at=VALIDATED_AT),
    CatalogueEntry("secret-agent", "SomaFM Secret Agent", "SomaFM", "station",
                   "https://somafm.com/secretagent/", "en", "US", "Music Radio",
                   "Lounge and cinematic selections. Existing Mariana station; live only.",
                   station_id="somafm-secret-agent", status="supported", health="existing-station",
                   evidence="https://somafm.com/listen/", validated_at=VALIDATED_AT),
    CatalogueEntry("wfmu", "WFMU", "WFMU", "station", "https://www.wfmu.org/audiostream.shtml",
                   "en", "US", "Music Radio", "Freeform independent radio. Live stream; no download or recording action.",
                   endpoint="https://stream0.wfmu.org/freeform-128k", station_id="wfmu",
                   status="supported", health="stream-prefix-verified",
                   evidence="https://www.wfmu.org/audiostream.shtml", validated_at=VALIDATED_AT),
    CatalogueEntry("live-on-kexp", "Live on KEXP", "KEXP", "programme",
                   "https://www.kexp.org/podcasts/live-on-kexp/", "en", "US", "Live Sessions",
                   "Official performance audio podcast, not extracted video. Select an episode explicitly.",
                   endpoint="https://www.omnycontent.com/d/playlist/bad5d079-8dcb-4630-8770-aa090049131d/18f3a48e-1c64-43e8-96e9-aa40002038ee/856f4314-821f-46ca-bc8e-aa40002038f2/podcast.rss",
                   hosting_platform="Omny Studio", status="supported", health="feed-enclosures-verified",
                   evidence="https://www.kexp.org/podcasts/live-on-kexp/", validated_at=VALIDATED_AT),
    CatalogueEntry("circle-round", "Circle Round", "WBUR", "programme",
                   "https://www.wbur.org/podcasts/circleround", "en", "US", "Family",
                   "Folktales from many cultures. Public feed; member-only editions are not included.",
                   endpoint="https://rss.wbur.org/circleround/podcast", status="supported",
                   health="feed-enclosures-verified", evidence="https://www.wbur.org/podcasts/circleround",
                   validated_at=VALIDATED_AT),
    CatalogueEntry("kulturfragen", "Kulturfragen", "Deutschlandfunk", "programme",
                   "https://www.deutschlandfunk.de/kulturfragen-100.html", "de", "DE", "World & Languages",
                   "German-language cultural conversations. Public podcast feed in publisher order.",
                   endpoint="https://www.deutschlandfunk.de/kulturfragen-102.xml", status="supported",
                   health="feed-enclosures-verified", evidence="https://www.deutschlandfunk.de/kulturfragen-100.html",
                   validated_at=VALIDATED_AT),
)
BY_ID = {entry.id: entry for entry in ENTRIES}
PODCAST_ALIASES = {entry.id.replace("-", "_"): entry.endpoint for entry in ENTRIES
                   if entry.native and entry.kind == "programme" and entry.endpoint}


def search_catalogue(query: str | list[str] = "") -> list[CatalogueEntry]:
    """Search this bundled index, not a provider's remote catalogue.

    Fields match case-insensitive substrings; words combine with AND. Programme
    records have no invented release date, so dated searches cannot match them.
    """
    if len(query if isinstance(query, str) else " ".join(query)) > 512:
        raise ValueError("Catalogue query must be 512 characters or fewer")
    fields = {"title", "creator", "programme", "provider", "language", "region", "category", "after", "before"}
    terms = shlex.split(query) if isinstance(query, str) else query
    for term in terms:
        if ":" in term and term.split(":", 1)[0].casefold() not in fields:
            raise ValueError("Unknown catalogue search field")
    result = []
    for entry in ENTRIES:
        values = {"title": entry.title, "creator": entry.publisher,
                  "programme": entry.title if entry.kind == "programme" else "",
                  "provider": entry.publisher, "language": entry.language,
                  "region": entry.region, "category": entry.category, "after": "", "before": ""}
        combined = " ".join((*values.values(), entry.summary, entry.id)).casefold()
        if all((value.casefold() in values[field.casefold()].casefold() and bool(values[field.casefold()]))
               if ":" in term else term.casefold() in combined
               for term in terms for field, _, value in [term.partition(":")]):
            result.append(entry)
    return result


def catalogue_details(identifier: str) -> dict:
    entry = BY_ID.get(identifier.removeprefix("catalogue:"))
    if entry is None:
        raise ValueError("Unknown catalogue entry")
    return {
        **asdict(entry), "actions": entry.actions,
        "command": f"pod {entry.id.replace('-', '_')}" if entry.kind == "programme" else f"radio play {entry.id}",
        "coverage": "Bundled programme/station index, not provider-wide search",
        "download": "Existing download-ml current for supported finite public episodes" if entry.kind == "programme" else "Not supported for live radio",
    }


class CatalogueReader:
    """On-demand feed reads on DiscoverySelection's existing worker.

    At most eight in-memory feeds, 120 episodes each, fresh for fifteen minutes.
    Expired transport URLs are not persisted or silently reused after a failed
    refresh. Home's bundled programme cards remain available offline.
    """

    def __init__(self, *, fetcher=None, now: Callable[[], float] = time.monotonic) -> None:
        self.fetcher = fetcher or SafeArtworkFetcher(
            accept="application/rss+xml,application/atom+xml,application/xml,text/xml",
            total_timeout=25,
            user_agent="Mariana-Podcasts/1",
        )
        self.now = now
        self.cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self.cancel = threading.Event()

    def episodes(self, entry: CatalogueEntry, cancelled: Callable[[], bool]) -> list[MediaRef]:
        if not entry.native or entry.kind != "programme" or not entry.endpoint:
            raise ValueError("This catalogue entry has no verified public episode feed")
        cached = self.cache.get(entry.endpoint)
        if cached and self.now() - cached[0] < 900:
            records = copy.deepcopy(cached[1])
            self.cache.move_to_end(entry.endpoint)
        else:
            if cancelled() or self.cancel.is_set():
                raise ArtworkCancelled("Podcast selection cancelled")
            cancel = _SelectionCancellation(self.cancel, cancelled)
            payload = self.fetcher.fetch(entry.endpoint, cancel=cancel, max_bytes=MAX_PODCAST_BYTES)
            if cancelled() or self.cancel.is_set():
                raise ArtworkCancelled("Podcast selection cancelled")
            records = parse_podcast_feed(payload.data, entry.endpoint)[:120]
            self.cache[entry.endpoint] = (self.now(), copy.deepcopy(records))
            self.cache.move_to_end(entry.endpoint)
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
        if cancelled() or self.cancel.is_set():
            raise ArtworkCancelled("Podcast selection cancelled")
        return [media for record in records if (media := episode_media(record)) is not None]

    def close(self) -> None:
        self.cancel.set()
        self.fetcher.close()
        self.cache.clear()


class _SelectionCancellation(threading.Event):
    def __init__(self, closed: threading.Event, stale: Callable[[], bool]) -> None:
        super().__init__()
        self.closed = closed
        self.stale = stale

    def is_set(self) -> bool:
        return self.closed.is_set() or self.stale() or super().is_set()
