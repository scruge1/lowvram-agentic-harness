"""Thin, reversible command bindings for the existing agent-home launcher.

Pi1.4 supplies agentDir/sessionDir and runs in its process cwd. This module
selects those existing inputs; it does not create another agent/session engine.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile


class LaunchError(ValueError):
    pass


def require(value, message):
    if not value:
        raise LaunchError(message)


def canonical(path):
    return Path(path).expanduser().resolve(strict=True)


def session_directory(home, cwd):
    # Native Pi1.4 session-manager.js:getDefaultSessionDirPath, not a new store.
    value = str(canonical(cwd))
    if value.startswith(("/", "\\")):
        value = value[1:]
    encoded = "--" + re.sub(r"[/\\:]", "-", value) + "--"
    return canonical(home) / "agent/sessions" / encoded


def select_project(home, requested=None, cwd=None):
    home, cwd = canonical(home), canonical(cwd or Path.cwd())
    if requested is not None:
        selected = Path(requested).expanduser()
        if not selected.is_absolute():
            local = cwd / selected
            legacy = home / "projects" / selected
            selected = local if local.exists() else legacy
        selected = canonical(selected)
        require(selected.is_dir() and (selected / ".icm/project.json").is_file(),
                "Select an existing admitted project; launch never adopts a random directory")
        return selected
    for candidate in (cwd, *cwd.parents):
        if candidate == home:
            return None
        if (candidate / ".icm/project.json").exists():
            return candidate
    return None


def managed_arguments(home, arguments):
    """Managed selectors precede Pi arguments. Explicit home may confirm binding."""
    values = list(arguments)
    selectors = {}
    while values:
        option, separator, inline = values[0].partition("=")
        if option not in {"--home", "--project", "--status"}:
            break
        values.pop(0)
        require(option not in selectors, "Specify " + option + " only once")
        if option == "--status":
            require(not separator, "--status takes no value")
            selectors[option] = True
        else:
            require(separator or values, option + " requires a value")
            selectors[option] = inline if separator else values.pop(0)
    if "--home" in selectors:
        require(canonical(selectors["--home"]) == canonical(home), "This command is bound to a different agent home")
    if values[:1] == ["--"]:
        values = values[1:]
    require(not selectors.get("--status") or not values, "--status does not run Pi arguments")
    return selectors.get("--project"), bool(selectors.get("--status")), values


def pi_arguments(arguments, model):
    """Refuse Pi1.4 inputs that replace the managed model/profile/session route."""
    arguments = list(arguments)
    output, seen = [], set()
    no_value = {"--help", "-h", "--version", "-v", "--verbose", "--offline", "--print", "-p", "--list-models"}
    values = {"--mode", "--thinking", "--name", "-n", "--use-theme", "--tui-mode"}
    session_flags = {"--continue", "-c", "--resume", "-r", "--session", "--session-id", "--session-dir", "--fork", "--no-session"}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            # Native Pi1.4 parseArgs ends option parsing here. Later tokens are
            # literal prompt/file arguments, including a second '--'.
            output.extend(arguments[index:])
            break
        option, separator, inline = token.partition("=")
        require(option not in session_flags,
                "Managed resume/session overrides are not qualified; start a fresh session in this home/project")
        if option in {"--provider", "--model"}:
            require(option not in seen, "Specify " + option + " only once")
            seen.add(option)
            index += 1
            require(separator or index < len(arguments), option + " requires a value")
            value = inline if separator else arguments[index]
            require(value == ("local" if option == "--provider" else model),
                    "The managed provider/model differs; select another configured home explicitly")
            if not separator:
                index += 1
            continue
        if option in values:
            require(not separator and index + 1 < len(arguments), option + " requires a separate value")
            value = arguments[index + 1]
            if option == "--mode":
                require(value in {"text", "json"}, "Managed RPC mode is not qualified; use text or json mode")
            output.extend([option, value])
            index += 2
            continue
        if token.startswith("-"):
            require(not separator and option in no_value,
                    "Unsupported managed Pi option " + option + "; profile, agent directory and tools stay home-bound")
        output.append(token)
        index += 1
    return output


def command_name(name):
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
            and name != "pi", "Use a unique managed command name; pi is a separate opt-in")
    return name


def bin_directory(value, create=False):
    path = Path(value).expanduser()
    require(path.is_absolute(), "Select an explicit absolute bin directory")
    path = path.resolve(strict=False)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    require(not path.exists() or path.is_dir(), "Selected bin path is not a directory")
    return path


def command_file(directory, name):
    return directory / (name + (".cmd" if os.name == "nt" else ""))


def command_bytes(home, python=None):
    python = Path(python or sys.executable).absolute()
    launcher = canonical(home) / "agent-home.py"
    require(python.is_file() and launcher.is_file(), "The installed Python/home launcher is missing")
    if os.name == "nt":
        require(not any(char in str(python) + str(launcher) for char in '\r\n"'), "Unsupported Windows command path")
        require(str(python).isascii(), "Windows command registration requires an ASCII interpreter path")
        # ASCII batch source avoids changing the user's console code page while
        # retaining Unicode home/bin paths. Python opens the absolute launcher.
        code = ("import runpy,sys; p=bytes.fromhex('" + str(launcher).encode("utf-8").hex()
                + "').decode('utf-8'); sys.argv=[p,'managed','--',*sys.argv[1:]]; "
                  "runpy.run_path(p,run_name='__main__')")
        interpreter = '"' + str(python).replace("%", "%%") + '"'
        return ('@echo off\r\n' + interpreter + ' -B -c "' + code + '" %*\r\n').encode("ascii")
    return ("#!/bin/sh\nexec " + shlex.join([str(python), "-B", str(launcher), "managed", "--"]) + ' "$@"\n').encode("utf-8")


def receipt_path(home, directory, name):
    key = hashlib.sha256((str(directory) + "\0" + name).encode()).hexdigest()[:24]
    home = canonical(home)
    state = home / "state/managed-commands"
    require(state.resolve().is_relative_to(home), "Command receipts must remain inside their agent home")
    return state / (key + ".json")


def read_receipt(home, directory, name):
    path = receipt_path(home, directory, name)
    if not path.exists():
        return None
    require(not path.is_symlink(), "Managed command receipt must not be a symlink")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict) and value.get("schema") == "managed-command/v1" and value.get("home") == str(canonical(home))
            and value.get("bin_dir") == str(directory) and value.get("name") == name
            and isinstance(value.get("commands"), list),
            "Managed command receipt identity differs")
    for item in value["commands"]:
        require(isinstance(item, dict) and item.get("name") in {name, "pi"}
                and item.get("path") == str(command_file(directory, item["name"]))
                and isinstance(item.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                "Managed command receipt path differs")
    return value


def save_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="command-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def inspect_command(home, directory, name="harness-agent"):
    name = command_name(name)
    directory = bin_directory(directory)
    receipt = read_receipt(home, directory, name)
    commands = []
    for label in [name, "pi"]:
        target = command_file(directory, label)
        owned = next((item for item in (receipt or {}).get("commands", []) if item["name"] == label), None)
        present = target.exists() or target.is_symlink()
        matching = bool(owned and present and not target.is_symlink()
                        and hashlib.sha256(target.read_bytes()).hexdigest() == owned["sha256"])
        resolved = shutil.which(label)
        commands.append({"name": label, "path": str(target), "present": present, "owned_unchanged": matching,
                         "path_resolves_to": resolved,
                         "selected_on_process_PATH": bool(resolved and Path(resolved).resolve() == target.resolve())})
    return {"home": str(canonical(home)), "bin_dir": str(directory), "name": name,
            "commands": commands, "registration": (receipt or {}).get("state", "not_registered"),
            "shell_resolution": "Process PATH only; shell aliases/functions and cached commands require shell inspection (type -a / Get-Command -All). No PATH or startup profile was changed."}


def register_command(home, directory, name="harness-agent", default_pi=False):
    name = command_name(name)
    directory = bin_directory(directory, create=True)
    # A previous runtime cannot silently install an entry point it cannot parse.
    require((canonical(home) / "runtime/harness/managed_launch.py").is_file(), "Update this home's runtime before registering its command")
    content = command_bytes(home)
    expected = hashlib.sha256(content).hexdigest()
    old = read_receipt(home, directory, name)
    receipt = old or {"schema": "managed-command/v1", "home": str(canonical(home)),
                      "bin_dir": str(directory), "name": name, "commands": []}
    collisions = []
    for label in [name, *(["pi"] if default_pi else [])]:
        target = command_file(directory, label)
        existing = next((item for item in receipt["commands"] if item["name"] == label), None)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not existing or existing["sha256"] != expected or target.read_bytes() != content:
                collisions.append(str(target))
                if label == name:
                    break
                continue
        else:
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o755)
        if existing is None:
            receipt["commands"].append({"name": label, "path": str(target), "sha256": expected})
        receipt["state"] = "registered"
        save_receipt(receipt_path(home, directory, name), receipt)
    result = inspect_command(home, directory, name)
    result.update(status="collision" if collisions else "registered", collisions=collisions,
                  default_pi_requested=bool(default_pi))
    return result


def remove_command(home, directory, name="harness-agent"):
    name = command_name(name)
    directory = bin_directory(directory)
    receipt = read_receipt(home, directory, name)
    require(receipt is not None, "No owned command registration exists here")
    expected = command_bytes(home)
    for item in receipt["commands"]:
        target = Path(item["path"])
        require(not target.is_symlink() and (not target.exists()
                or target.read_bytes() == expected and hashlib.sha256(expected).hexdigest() == item["sha256"]),
                "Command changed; preserve it and inspect before reversal")
    for item in receipt["commands"]:
        target = Path(item["path"])
        if target.exists():
            backup = receipt_path(home, directory, name).with_suffix("." + item["name"] + ".removed")
            backup.write_bytes(target.read_bytes())
            target.unlink()
    receipt["state"] = "removed"
    save_receipt(receipt_path(home, directory, name), receipt)
    return {**inspect_command(home, directory, name), "status": "removed"}
