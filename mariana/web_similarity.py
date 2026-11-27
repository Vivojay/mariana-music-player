"""Display-only similarity results for a browser viewing the native library."""
from .library import path_key
from .media_similarity import find_similar
from .presence import sanitize_presence_text


def browser_similarity(database, reference, mode, limit, *, library_paths, key_for_path):
    source = database.fetchone(
        "SELECT library_id FROM library_files WHERE path_key=? AND state='available'",
        (path_key(reference),),
    )
    if source is None:
        raise ValueError("Choose an indexed local recording to find similar tracks.")
    track, matches = find_similar(database, source["library_id"], mode, limit)
    numbered = {path_key(path): (number, path) for number, path in enumerate(library_paths(), 1)}
    rows = []
    for result in matches:
        occurrence = numbered.get(path_key(result.track.path))
        if occurrence:
            number, path = occurrence
            rows.append({
                "title": sanitize_presence_text(result.track.title, maximum=240) or "Local recording",
                "artist": sanitize_presence_text(result.track.metadata.get("artist"), maximum=160),
                "number": number, "key": key_for_path(path), "score": round(result.score, 4),
                "reasons": list(result.reasons),
            })
    return {"title": sanitize_presence_text(track.title, maximum=240) or "Local recording",
            "rows": rows, "mode": mode}
