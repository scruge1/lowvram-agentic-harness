"""Local human-terminal research setup. No provider validation requests."""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys
import warnings

from . import research_config as config


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal unknown-argument error would echo an accidental key.
        raise config.ConfigError("Invalid setup arguments; keys are accepted only by hidden terminal entry")


def _terminal():
    config.require(sys.stdin.isatty() and sys.stderr.isatty(),
                   "Run setup directly in your terminal; never paste a key into agent chat or a tool call")


def masked_key():
    _terminal()
    # getpass otherwise warns and can fall back to echoed stdin.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("API key (hidden; Enter keeps the saved key): ", stream=sys.stderr)
        except (getpass.GetPassWarning, EOFError):
            raise config.ConfigError("Hidden terminal entry is unavailable; no key was saved") from None


def guided(home, provider=None):
    _terminal()
    config.load_settings(home)  # Fail before asking for a credential.
    for name in (provider,) if provider else config.ORDER:
        guide = config.CATALOG[name]
        print("\n" + name + ": " + guide["note"])
        print("Guide: " + guide["guide"] + " (checked " + config.GUIDANCE_CHECKED + ")")
        if guide["signup"]:
            print("Sign up yourself: " + guide["signup"])
        choice = input("Enable, skip, remove local key, or keep current [e/s/r/Enter]: ").strip().lower()
        config.require(choice in {"", "e", "s", "r"}, "Choose enable, skip, remove or keep current")
        if not choice:
            continue
        if choice in {"s", "r"}:
            config.configure_provider(home, name, "skipped", remove_credential=choice == "r")
            continue
        key = masked_key() if name in config.KEYED else None
        endpoint = None
        if name == "searxng":
            endpoint = input("Your owned SearXNG endpoint (Enter keeps saved endpoint): ").strip() or None
        acknowledged = None
        if name in config.RETENTION_SOURCES:
            print(name + " is held unless your rights cover stored search results in research artifacts AND native session history.")
            print("Review terms and your intended use: " + config.RETENTION_SOURCES[name])
            acknowledged = input("My current plan and use rights explicitly permit both [yes/Enter]: ").strip().lower() == "yes"
        config.configure_provider(home, name, "enabled", credential=key or None, endpoint=endpoint,
                                  retention_acknowledged=acknowledged)
    return config.provider_status(home)


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("action", choices=("setup", "status", "skip", "revisit", "remove"))
    parser.add_argument("--provider", choices=config.ORDER)
    try:
        args = parser.parse_args(argv)
        if args.action == "status":
            result = config.provider_status(args.home)
        elif args.action in {"setup", "revisit"}:
            result = guided(args.home, args.provider)
        else:
            _terminal()
            config.require(args.provider, "Select a provider")
            result = config.configure_provider(args.home, args.provider, "skipped", remove_credential=args.action == "remove")
        print(json.dumps(result, indent=2))
        return 0
    except config.ConfigError as error:
        print("Research setup held: " + str(error) + ". No provider request was sent.", file=sys.stderr)
        return 2
    except (OSError, EOFError, KeyboardInterrupt):
        # Never format an underlying exception or echo input/config values.
        print("Research setup held. Check the selected home, private file permissions and direct terminal entry. No provider request was sent.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
