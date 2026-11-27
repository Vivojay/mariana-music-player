"""Compare two independently prepared, media-clock, word-level TTML transcriptions."""
from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .karaoke import MAX_BYTES, MAX_MS, SCHEMA, Score, _label

TT = "{http://www.w3.org/ns/ttml}"
META = "{http://www.w3.org/ns/ttml#metadata}"
PARAM = "{http://www.w3.org/ns/ttml#parameter}"
XML = "{http://www.w3.org/XML/1998/namespace}"
CLOCK = re.compile(r"(?:(\d+):)?(\d{1,2}):([0-5]\d(?:\.\d+)?)\Z")
OFFSET = re.compile(r"(\d+(?:\.\d+)?)(ms|s)\Z")


def _ms(text):
    if not isinstance(text, str) or len(text) > 32:
        raise ValueError("Every TTML word needs explicit start and end times.")
    try:
        if match := OFFSET.fullmatch(text):
            value = Decimal(match[1]) * (1000 if match[2] == "s" else 1)
        elif match := CLOCK.fullmatch(text):
            if int(match[2]) > 59:
                raise ValueError("Unsupported TTML clock expression.")
            value = (int(match[1] or 0) * 3600 + int(match[2]) * 60 + Decimal(match[3])) * 1000
        else:
            raise ValueError("Use TTML media-clock seconds, milliseconds or HH:MM:SS.sss.")
        value = int(value.to_integral_value(rounding=ROUND_HALF_UP))
    except InvalidOperation as error:
        raise ValueError("Invalid TTML timestamp.") from error
    if value < 0 or value > MAX_MS:
        raise ValueError("TTML timestamp is outside the supported day.")
    return value


def _times(node, parent_start, parent_end):
    start = parent_start + _ms(node.get("begin", "0s"))
    end = parent_end
    if "end" in node.attrib:
        end = parent_start + _ms(node.get("end"))
    if "dur" in node.attrib:
        end = min(end, start + _ms(node.get("dur")))
    if not parent_start <= start < end <= parent_end:
        raise ValueError("TTML child timing is outside its parent.")
    return start, end


def _document(path):
    if not path.is_file():
        raise ValueError("Choose two existing TTML documents.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Each TTML file must fit within 2 MiB.")
    try:
        text = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("TTML document types and entity declarations are unsupported.")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as error:
        raise ValueError("Cannot read UTF-8 TTML.") from error
    if root.tag != TT + "tt" or root.get(PARAM + "timeBase", "media") != "media":
        raise ValueError("Expected a media-clock TTML document.")
    return root, hashlib.sha256(raw).digest()


def _names(root):
    names = {}
    for agent in root.iter(META + "agent"):
        identity = agent.get(XML + "id")
        name_node = agent.find(META + "name")
        if identity and name_node is not None:
            names[identity] = "".join(name_node.itertext()).strip() or identity
    return names


def attributed_lyrics(path):
    """Read vocalist-labelled text even when timing has never been corroborated."""
    root, _ = _document(path)
    body = root.find(TT + "body")
    if body is None:
        raise ValueError("No TTML lyric body was found.")
    names = _names(root)
    lines = []

    def walk(node, inherited, paragraph=None, depth=0):
        if depth > 16:
            raise ValueError("Too many nested TTML elements.")
        agent = node.get(META + "agent", inherited).lstrip("#")
        if node.tag == TT + "p":
            paragraph = []
            lines.append(paragraph)

        def add(text):
            if paragraph is not None and text:
                name = _label(names.get(agent, agent) or "Voice", 80)
                if paragraph and paragraph[-1][0] == name:
                    paragraph[-1][1].append(text)
                else:
                    paragraph.append((name, [text]))

        add(node.text)
        for child in node:
            walk(child, agent, paragraph, depth + 1)
            add(child.tail)

    walk(body, "Voice")
    if len(lines) > 10000:
        raise ValueError("This recording exceeds the supported verse count.")
    verses = []
    for line in lines:
        for singer, fragments in line:
            text = " ".join("".join(fragments).split())
            if text:
                verses.append((singer, _label(text, 4096)))
    if not verses:
        raise ValueError("No vocalist-labelled text was found.")
    return verses


def _file(path, duration):
    root, digest = _document(path)
    body = root.find(TT + "body")
    if body is None or not {"dur", "end"}.intersection(body.attrib) or body.get("begin", "0s") not in {"0s", "0ms", "00:00:00.000", "00:00:00"}:
        raise ValueError("The TTML body must explicitly cover the complete recording beginning at zero.")
    _, total = _times(body, 0, MAX_MS)
    if abs(total - duration) > 250:
        raise ValueError("The TTML duration does not match this recording.")
    names = _names(root)
    lines = []
    words = []
    coverage = []
    rests = []
    def walk(node, parent_start, parent_end, singer, line=None, depth=0):
        if depth > 12:
            raise ValueError("Too many nested TTML elements.")
        if node.get("timeContainer", "par") != "par" or node.tag not in {TT + "body", TT + "div", TT + "p", TT + "span", TT + "br"}:
            raise ValueError("Unsupported TTML timing container or inline markup.")
        start, end = _times(node, parent_start, parent_end)
        agent = node.get(META + "agent", singer).lstrip("#")
        if " " in agent:
            raise ValueError("Multiple agent references on a single word are unsupported.")
        if node.tag == TT + "p":
            if line is not None:
                raise ValueError("TTML paragraphs cannot nest.")
            if "begin" not in node.attrib or not {"end", "dur"}.intersection(node.attrib):
                raise ValueError("Vocal phrases and instrumental sections need explicit timing.")
            line = []
            lines.append(line)
            if node.get(META + "role") == "x-instrumental":
                if "".join(node.itertext()).strip() or len(node):
                    raise ValueError("Instrumental sections must contain no lyric words.")
                rests.append((start, end))
                coverage.append((start, end))
                return
            phrase_start, phrase_end = start, end
        if node.text and node.text.strip():
            if (node.tag != TT + "span" or line is None or len(node) or "begin" not in node.attrib
                    or not {"end", "dur"}.intersection(node.attrib)):
                raise ValueError("Every sung word must have its own explicitly timed span.")
            word = node.text.strip()
            if re.search(r"\s", word):
                raise ValueError("Each TTML timed span must contain a single word.")
            record = (names.get(agent, agent) or "Voice", word, start, end)
            words.append(record)
            line.append(record)
        for child in node:
            if child.tail and child.tail.strip():
                raise ValueError("Untimed TTML text is unsupported.")
            walk(child, start, end, agent, line, depth + 1)
        if node.tag == TT + "p" and line:
            # Word spans identify sung audio; allow ordinary short breaths. An
            # arbitrarily long paragraph with one word cannot certify the outro.
            last_end = phrase_start
            for _, _, on, off in sorted(line, key=lambda row: row[2]):
                if on - last_end > 2000:
                    raise ValueError("A vocal phrase has a gap over 2 s. Split it and explicitly tag the instrumental.")
                last_end = max(last_end, off)
            if phrase_end - last_end > 2000:
                raise ValueError("A vocal phrase has an unexplained tail. Explicitly tag its instrumental section.")
            coverage.append((phrase_start, phrase_end))
    walk(body, 0, MAX_MS, "Voice")
    cursor = 0
    for start, end in sorted(coverage):
        if start > cursor:
            raise ValueError("Unknown time in the recording. Mark instrumental sections using ttm:role=x-instrumental.")
        cursor = max(cursor, end)
    if cursor != total:
        raise ValueError("Unknown outro. Explicitly mark instrumental time through the recording end.")
    if rests:
        # Merge simultaneous voice windows before comparing them to rest markers.
        busy = sorted((on, off) for _, _, on, off in words)
        index = 0
        for start, end in sorted(rests):
            while index < len(busy) and busy[index][1] <= start:
                index += 1
            if index < len(busy) and busy[index][0] < end:
                raise ValueError("An instrumental declaration overlaps a sung word.")
    if not words or sum(map(len, lines)) != len(words):
        raise ValueError("No word-timed verses were found.")
    return total, lines, digest


def _key(text):
    return unicodedata.normalize("NFKC", text).casefold()


def compare(first, second, digest, duration):
    """A 100 ms boundary disagreement costs ten points; expose the weaker word."""
    if not duration:
        raise ValueError("Wait for the local recording duration before comparing.")
    first_total, lines, one = _file(first, duration)
    second_total, others, two = _file(second, duration)
    if one == two:
        raise ValueError("Choose two independently prepared scores. These files are identical.")
    if first_total != second_total:
        raise ValueError("The two documents must cover the same timeline.")
    # Group by singer to allow a different interleaving of simultaneous duet lines.
    by_voice = {}
    for line in others:
        for singer, text, on, off in line:
            by_voice.setdefault(_key(singer), []).append((_key(text), on, off))
    for rows in by_voice.values():
        rows.sort(key=lambda row: row[1])
    counts = {}
    scored = []
    observed_difference = False
    for line in sorted((line for line in lines if line), key=lambda line: min(word[2] for word in line)):
        rendered = []
        for singer, text, on, off in line:
            key = _key(singer)
            index = counts.get(key, 0)
            rows = by_voice.get(key, [])
            if index >= len(rows) or rows[index][0] != _key(text):
                raise ValueError("Whole-recording corroboration failed: words or singer assignments differ.")
            counts[key] = index + 1
            distance = max(abs(on - rows[index][1]), abs(off - rows[index][2]))
            observed_difference |= distance > 0
            rendered.append((singer, {"text": text, "start_ms": on, "end_ms": off, "confidence": max(0, 1 - distance / 1000)}))
        scored.append((min(w["start_ms"] for _, w in rendered), max(w["end_ms"] for _, w in rendered), rendered))
    if any(counts.get(key, 0) != len(items) for key, items in by_voice.items()):
        raise ValueError("One TTML file has uncorroborated words.")
    if not observed_difference:
        raise ValueError("The timing sources have identical word boundaries. Independence cannot be established.")
    # Keep concurrent lines from different singers together in a shared segment.
    groups = []
    for start, end, line in sorted(scored, key=lambda row: row[0]):
        if groups and start < groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], end)
            groups[-1][2].extend(line)
        else:
            groups.append([start, end, list(line)])
    segments = []
    cursor = 0
    for start, end, line in groups:
        if start > cursor:
            segments.append(dict(start_ms=cursor, end_ms=start, voices=[]))
        voices = {}
        for singer, word in line:
            voices.setdefault(singer, []).append(word)
        segments.append(dict(start_ms=start, end_ms=end, voices=[
            dict(singer=singer, words=sorted(words, key=lambda row: row["start_ms"])) for singer, words in voices.items()
        ]))
        cursor = end
    if cursor < first_total:
        segments.append(dict(start_ms=cursor, end_ms=first_total, voices=[]))
    score = min(word["confidence"] for _, _, line in scored for _, word in line)
    return Score(dict(schema=SCHEMA, duration_ms=first_total, media_sha256=digest,
                      source="Timing agreement between two user-selected TTML transcriptions", confidence=score,
                      segments=segments))
