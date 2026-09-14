# Tags and reusable tag groups

Tags describe media independently of its filename, rating, block status, queue,
or playlist. They are stored in Mariana's database; commands never rewrite audio
files. Names ignore case and normalize repeated whitespace. Quote multiword
names with the same quoting rules as other Mariana commands.

## Everyday commands

```text
tag create "Late Night" --description "Quiet evening music"
tag list
tag attach current "Late Night" ambient
tag attach 12 instrumental
tag show current
tag show 12
tag detach 12 instrumental
tag rename "Late Night" "After Hours"
tag delete "After Hours"
tag delete "After Hours" --yes
```

`tag` alone lists definitions. `tag show` alone shows the current media's tags.
Attach creates missing definitions and leaves existing assignments unchanged.
Detach removes assignments, not definitions; detaching an absent tag is a no-op.
Rename preserves the tag's identity and all its assignments.

A target is `current` (`now` also works) or a positive number from the local
library. Numbers are always library indexes, not positions in tag search results.
Paths and URLs are not accepted as targets. Indexed local files must still be
available and match the selected stable library identity. Current YouTube videos
and feed-identified podcast episodes are also supported. Arbitrary streams,
unindexed local files, radio streams, and unresolved recommendations are not made
durable by tagging them.

Deleting an unused definition happens immediately. A tag used by any media or
group requires explicit confirmation, or `--yes`. This deletes the definition
and its assignments everywhere. Cancelling leaves them unchanged. The selected
identity is bound before prompting; replacement or renamed definitions are not
silently deleted. Ratings, block status, media files, and group definitions stay
intact.

## Tag-only search

```text
tag find --all ambient instrumental
tag find --any ambient jazz
tag find --all ambient --not vocal
tag find --any ambient jazz --not live --source local --limit 20
tag find --not vocal
tag play 2
tag queue 1
```

`--all` requires every listed tag, `--any` requires at least one, and `--not`
excludes every listed tag. Different clauses are combined with AND. Each clause
may be repeated. A missing required tag produces no results; unknown exclusion
tags exclude nothing. At least one tag clause or `--group` is required.
`--limit` is a non-negative count; zero returns no results. `--source` accepts
`local`, `youtube`, `url`, `podcast`, `radio`, or `recommendation` and filters
existing stored identities, including assignments imported through other APIs.

Results retain stable identities instead of being converted to library-index
commands. Missing local items remain visible as unavailable. A catalog move is
resolved to the current path. A result's number is its position in this result
set, not a new durable identity.

`tag play N` plays one numbered result from the latest tag search, while
`tag queue N` appends it to the queue. Both use the result's bound identity and
recheck current availability and playback policy. They do not reinterpret the
result number as a library number. Run a new tag search when the selection is
missing or stale.

## Reusable groups

```text
tag group create Mood --description "Listening moods"
tag group add Mood calm energetic reflective
tag group list
tag group show Mood
tag find --group Mood
tag find --group Mood --all instrumental --not live
tag group remove Mood energetic
tag group rename Mood Feeling
tag group delete Feeling --yes
```

A group is a named set of tags, not an owner of those tags. The same tag can be
in several groups. Adding members creates missing definitions; removing members
does not detach tags from media. Group search matches any member tag and is
intersected with other search clauses. An empty group matches nothing. Limits
apply after all filters.

Deleting a nonempty group requires confirmation or `--yes`. It removes only the
group and its memberships; all tags and media assignments survive. An empty
group can be deleted immediately.

Tag and group names are at most 64 characters; descriptions are at most 512.
Existing definitions can also be referenced by their IDs for rename, delete,
detach, group show/remove, and search. Attach and group add take tag names.
For literal names beginning with `--` in non-search commands, put `--` before
positional values; such tags can be searched using their ID.

## Host integration

`mariana.tag_commands.TagCommandService` takes a `TagStore`, a required
`resolve_target` callback, and an optional `confirm` callback. Call
`execute(arguments)` with the already-tokenized arguments after `tag`—use the
existing `split_command`, not shell execution or command-string reconstruction.
Invalid operations raise `TagError` (a `ValueError`) without printing.

The resolver receives `current` or a positive library-index string exactly once
and returns the selected stable `MediaRef`, or `None`. It should use the host's
current-media snapshot and indexed-library identity binding without persisting
data. The service validates local catalog membership, path, and availability.
Only attach remembers an accepted media identity, using `MediaPreferences`,
without changing rating or block state. Read-only commands never remember media.

The confirmation callback accepts one display prompt and returns a boolean.
Without it, used-tag/nonempty-group deletion raises `TagInUseError` with `--yes`
instructions. The host should reuse its usual confirmation interaction.

`TagCommandResult` exposes `operation`, `message`, `tags`, `groups`, `media_tags`,
`media`, `entries`, `changed_count`, and `cancelled`. Render definitions and
memberships with the host's existing table/label formatting. For search, `entries`
is a tuple of existing `NavigationEntry` contracts with stable IDs and bound
media. Missing entries have `media=None` and an unavailable label. It can populate
`NavigationContext(NavigationScope.RESULTS, result.entries, -1, "tag results")`.
Keep the existing playback availability/block checks when activating any result.
Do not turn labels, names, or result numbers into commands.

The host intercepts `tag play N` and `tag queue N`, selects an occurrence from its
latest tag-search context, and calls `service.resolve_result(entry)` before the
action. That method refreshes the current catalog path by stable ID, preserves
the bound result position, and refuses unavailable or changed-source identities.
It never invokes the mutable library-index resolver. Playback and queue writes
remain with the host; `execute` handles only storage, inspection, and search.
