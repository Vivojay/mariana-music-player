"""Compatibility shim for the retired Reddit/RPAN integration."""

RETIRED_MESSAGE = (
    "Reddit live sessions (RPAN) have been retired and are no longer available in Mariana Player."
)
WARNING = RETIRED_MESSAGE
redditsessions = None


def get_redditsessions():
    return []


def display_seshs_as_table(_sesh_list):
    return [], ("title", "upvotes", "downvotes")
