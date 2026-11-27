"""Present indexed recordings in the TUI using the CLI's authoritative play numbers."""
import os
from pathlib import Path


def library_rows(database, names, paths, *, include_folder=True):
    # Select just the tags the view displays. One read avoids probing audio or querying per row.
    tagged = database.fetchall("""
        WITH labels AS (
            SELECT canonical_path, CASE WHEN json_valid(metadata_json) THEN metadata_json END AS tags
            FROM library_files WHERE state = 'available'
        )
        SELECT canonical_path, json_extract(tags, '$.title'), json_extract(tags, '$.artist'),
               json_extract(tags, '$.album') FROM labels
    """)
    tags_by_path = {os.path.normcase(path): (title, artist, album) for path, title, artist, album in tagged}
    rows = []
    for number, (name, path) in enumerate(zip(names, paths), 1):
        title, artist, album = tags_by_path.get(os.path.normcase(path), (None, None, None))
        title = title if isinstance(title, str) and title.strip() else name
        detail = " · ".join(tag for tag in (artist, album) if isinstance(tag, str) and tag.strip())
        if not detail:
            file = Path(path)
            detail = " · ".join(filter(None, (file.suffix.lstrip(".").upper(), file.parent.name if include_folder else "")))
        rows.append((title, detail, f"play {number}", path))
    return rows
