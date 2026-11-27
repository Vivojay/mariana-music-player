# Native collections in paired Flow

Open a paired browser with `web session flow` from the native Mariana prompt. Keep **Show my library and collections in this tab** checked. **Queue**, **Playlists**, **Albums**, **Likes**, and **Live** browse the profile running on this computer.

| View | Browser controls |
| --- | --- |
| Queue | Search the queue, play or remove recordings, and reorder within a group. Change shuffle, repeat, consumption and autofill, or use undo and redo. Clearing uses the CLI's native confirmation. |
| Playlists | Search saved lists, open their track lists, play an entire list, or add it to the native queue. |
| Albums | Search albums made from indexed local tags and up to 250 saved online editions. Open the saved track list, play resolved tracks and add them to the queue. |
| Likes | Browse favorites and play a recording. Add or remove the current favorite using Flow's playback controls. |
| Live | Browse the native radio catalog, play and star stations, and resynchronize at the live edge. |

The browser shows up to 30 records per page. It sends row actions through the existing native dispatcher and current pairing approval policy. Positional actions check the selected item and revision again before execution. Play-all and album Play replace the native queue, as the corresponding CLI commands do. Add to queue preserves existing entries.

These views read the profile's saved state. Use the native catalog commands to fetch album track lists and search for additional internet radio stations. Playlist editing and nested group operations remain available through the native command surface. Playback stays on the host computer. Collection views use display metadata and action keys.

`python -m unittest discover -s tests -p test_web_collections.py` exercises queue state, revision checks, private-reference filtering, cached album tracks, favorites, and radio with native temporary SQLite stores.
