"""Interactive setup for provider consent, public profiles and first-party tools."""
from __future__ import annotations

from . import account_services, connector_registration
from .terminal_io import secret_input
from .connections import command, hub

BUILTINS = {"karaoke": "Karaoke practice", "podcasts": "Podcast subscriptions", "audiobooks": "LibriVox audiobooks"}


def _choose(items, prompt):
    choice = input(prompt + " · " + "  ".join(f"{i}. {name}" for i, (_, name) in enumerate(items, 1))
                   + "  [Enter to cancel] > ").strip()
    if not choice:
        return None
    if choice.isdecimal() and 1 <= int(choice) <= len(items):
        return items[int(choice) - 1][0]
    for key, name in items:
        if choice.casefold() in (key.casefold(), name.casefold()):
            return key
    raise ValueError("Choose one of the listed numbers or names.")


def _register(key):
    redirect = ("Last.fm desktop sign-in uses the request-token flow." if key == "lastfm" else
                "Register the callback http://" + ("localhost" if key == "musicbrainz" else "127.0.0.1") +
                ":8789/accounts/callback with your provider.")
    print(redirect)
    public_id = secret_input(("API key" if key == "lastfm" else "Client ID or key") + " [hidden, Enter to cancel] > ").strip()
    if not public_id:
        return "Setup cancelled."
    secret = "" if key == "spotify" else secret_input("App secret [hidden, Enter to cancel] > ").strip()
    if key != "spotify" and not secret:
        return "Setup cancelled."
    connector_registration.save(key, public_id, secret)
    return f"Registration saved in the OS keychain. Run accounts setup {key} and choose Sign in."


def setup(args, database, dispatch):
    providers = account_services.PROVIDERS
    if len(args) > 1:
        raise ValueError("Usage: accounts setup [service]")
    choices = [*BUILTINS.items(), *((k, v["name"]) for k, v in providers.items())]
    key = args[0].casefold() if args else _choose(choices, "What would you like to set up?")
    if key is None:
        return "Setup cancelled."
    if key in BUILTINS:
        if key == "karaoke":
            if _choose([("demo", "Play the included practice duet")], "Karaoke works offline") is None:
                return "Setup cancelled."
            dispatch("karaoke demo")
            return "Use karaoke status to inspect timing and singer parts."
        family = "podbean" if key == "podcasts" else "librivox"
        term = input(f"Search {BUILTINS[key]} by title (no sign-in needed; Enter to cancel) > ").strip()
        if not term:
            return "Setup cancelled."
        if len(term) > 120 or any(not (c.isalnum() or c in " -_.,&’") for c in term):
            raise ValueError("Use a title of at most 120 letters, numbers, spaces or punctuation such as a dash.")
        dispatch(f'{family} search "{term}"')
        return f"Use {family} help for playback and subscription commands."
    if key not in providers:
        raise ValueError("Unknown service. Run accounts setup to choose one.")
    service = hub(database)
    row = next(r for r in service.run(["list"])["services"] if r["id"] == key)
    actions = []
    if row["pending"]:
        if key == "lastfm":
            actions.append(("finish", "Finish approved sign-in"))
        actions.extend([("list", "Check sign-in"), ("cancel", "Cancel sign-in")])
    elif row["identity"]:
        actions.append(("verify", "Verify connected account"))
    elif row["available"]:
        actions.append(("connect", f"Sign in with {row['name']}"))
    actions.extend([("link", "Save public profile"), ("open", "Open saved profile or service")])
    if key in connector_registration.SUPPORTED:
        if not row["available"]:
            actions.append(("register", "Configure my own registered provider app"))
        if connector_registration.marker(key).is_file():
            actions.append(("forget-registration", "Remove my saved app registration"))
    title = row["name"]
    if not row["available"] and not row["identity"]:
        title += " · Public links available. Registered sign-in options are listed in docs/CONNECTIONS.md."
    action = _choose(actions, title)
    if action is None:
        return "Setup cancelled."
    if action == "register":
        return _register(key)
    if action == "forget-registration":
        connector_registration.forget(key)
        return "Removed your local app registration. Disconnect any existing account separately."
    if action == "link":
        handle = input(row["hint"] + " [Enter to cancel] > ").strip()
        return command(["link", key, handle], database) if handle else "Setup cancelled."
    if action == "list":
        return command(["list"], database)
    return command([action, key], database)
