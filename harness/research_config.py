"""Home-owned search settings. Credentials are for trusted helpers only.

This is cooperative secret handling, not isolation from arbitrary same-user code.
Nothing in this module sends requests, enables ambient providers or starts work.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit

from . import home as agent_home


SCHEMA = "agent-home-research/v1"
AUTH_SCHEMA = "agent-home-research-auth/v1"
MAX_BYTES = 32768
RIGHTS_SOURCE = "https://brave.com/search/api/"
ORDER = ("searxng", "exa", "brave", "tavily", "ddg")
CATALOG = {
    "searxng": {"environment": "SEARXNG_URL", "signup": None,
                "guide": "https://docs.searxng.org/dev/search_api.html",
                "note": "Use your explicitly owned instance with JSON enabled. No provider account key. Setup does not install or probe it."},
    "exa": {"environment": "EXA_API_KEY", "signup": "https://dashboard.exa.ai/",
            "guide": "https://exa.ai/pricing",
            "note": "$10 credits each month plus $10 initial credits; no payment method required. Credits are not a query count. Provider and source terms still apply."},
    "brave": {"environment": "BRAVE_API_KEY", "signup": "https://api-dashboard.search.brave.com/",
              "guide": RIGHTS_SOURCE,
              "note": "$5 monthly credits; card required, no standalone free plan. Storage rights must cover persisted research artifacts and native session history. Otherwise this provider remains held."},
    "tavily": {"environment": "TAVILY_API_KEY", "signup": "https://app.tavily.com/",
               "guide": "https://www.tavily.com/pricing",
               "note": "1,000 API credits/month, no card required. Create a dashboard key with a monthly limit. Credits depend on endpoint/options; source terms still apply."},
    "ddg": {"environment": None, "signup": None,
            "guide": "https://duckduckgo.com/",
            "note": "Keyless fallback; no guaranteed quota or availability."},
}
GUIDANCE_CHECKED = "2026-10-25"


class ConfigError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ConfigError(message)


def _windows_permissions(path, protect=False):
    """Use native owner/DACL APIs; no account change, command or key in argv."""
    import ctypes
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    token = wintypes.HANDLE()
    require(adv.OpenProcessToken(wintypes.HANDLE(-1), 8, ctypes.byref(token)), "Cannot inspect current file owner")
    try:
        size = wintypes.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        require(adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)), "Cannot inspect current file owner")
        sid = ctypes.cast(buffer, ctypes.POINTER(pointer))[0]
        owner, dacl, descriptor = pointer(), pointer(), pointer()
        require(adv.GetNamedSecurityInfoW(ctypes.c_wchar_p(str(path)), 1, 5,
                                        ctypes.byref(owner), None, ctypes.byref(dacl), None,
                                        ctypes.byref(descriptor)) == 0, "Cannot inspect research file permissions")
        try:
            require(adv.EqualSid(owner, pointer(sid)), "Research path belongs to another user")
        finally:
            kernel.LocalFree(descriptor)
        if protect:
            sid_text = ctypes.c_wchar_p()
            require(adv.ConvertSidToStringSidW(pointer(sid), ctypes.byref(sid_text)), "Cannot inspect current file owner")
            try:
                text = "D:P(A;;FA;;;" + sid_text.value + ")"
            finally:
                kernel.LocalFree(sid_text)
            sd, new_dacl = pointer(), pointer()
            require(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(text, 1, ctypes.byref(sd), None), "Cannot protect research file")
            try:
                present, defaulted = wintypes.BOOL(), wintypes.BOOL()
                require(adv.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(new_dacl), ctypes.byref(defaulted)), "Cannot protect research file")
                require(adv.SetNamedSecurityInfoW(ctypes.c_wchar_p(str(path)), 1, 0x80000004,
                                                None, None, new_dacl, None) == 0, "Cannot protect research file")
            finally:
                kernel.LocalFree(sd)
        descriptor, owner, dacl = pointer(), pointer(), pointer()
        require(adv.GetNamedSecurityInfoW(ctypes.c_wchar_p(str(path)), 1, 5,
                                        ctypes.byref(owner), None, ctypes.byref(dacl), None,
                                        ctypes.byref(descriptor)) == 0, "Cannot inspect research file permissions")
        try:
            require(dacl.value and adv.EqualSid(owner, pointer(sid)), "Research file has no private owner ACL")
            count = ctypes.c_ushort.from_address(dacl.value + 4).value
            require(count > 0, "Research file has no owner access")
            for index in range(count):
                ace = pointer()
                require(adv.GetAce(dacl, index, ctypes.byref(ace)), "Cannot inspect research file access")
                require(ctypes.c_ubyte.from_address(ace.value).value == 0
                        and adv.EqualSid(pointer(ace.value + 8), pointer(sid)), "Research file permits another principal")
        finally:
            kernel.LocalFree(descriptor)
    finally:
        kernel.CloseHandle(token)


def _owned(path, *, directory=False, protect=False):
    info = path.lstat()
    require(not path.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400,
            "Research path must not be redirected")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "Unexpected research path type")
    require(directory or info.st_nlink == 1, "Research file must have one link")
    if os.name == "nt":
        _windows_permissions(path, protect)
    else:
        require(info.st_uid == os.getuid(), "Research path belongs to another user")
        if protect:
            path.chmod(0o700 if directory else 0o600)
        require(path.stat().st_mode & 0o077 == 0, "Research path permissions must be owner-only")


def _home(value):
    try:
        selected, _ = agent_home.load(Path(value))
        require(not (selected / "home.json").is_symlink(), "Home identity must not be redirected")
        return selected
    except (OSError, ValueError, KeyError, TypeError):
        raise ConfigError("Select an existing agent home with unchanged identity") from None


def _directory(home, create=False):
    state = home / "state"
    require(state.is_dir() and not state.is_symlink() and state.resolve() == state, "Research state parent must be owned and direct")
    directory = state / "research"
    if not directory.exists():
        require(not directory.is_symlink(), "Research path must not be redirected")
        if not create:
            return directory
        directory.mkdir(mode=0o700)
        _owned(directory, directory=True, protect=True)
    _owned(directory, directory=True)
    return directory


def _read(path):
    if not path.exists():
        require(not path.is_symlink(), "Research path must not be redirected")
        return None
    _owned(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "Research settings exceed their size limit")
    return raw


def _json(raw):
    try:
        value = json.loads(raw)
        require(isinstance(value, dict), "Invalid research settings")
        return value
    except (ValueError, UnicodeError):
        raise ConfigError("Invalid research settings; no values were returned") from None


def _defaults(home):
    return {"schema": SCHEMA, "home": str(home), "providers": {
        name: {"state": "enabled" if name == "ddg" else "unconfigured",
               "retention": "not_confirmed", "rights_source": None,
               **({"endpoint": None} if name == "searxng" else {})} for name in ORDER}}


def _endpoint(value):
    require(isinstance(value, str) and 0 < len(value) <= 2048 and not any(c.isspace() for c in value), "Use an explicit owned SearXNG endpoint")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment)
        parsed.port
    except ValueError:
        valid = False
    require(valid, "Use an HTTP(S) SearXNG endpoint without credentials, query or fragment")
    return value.rstrip("/")


def _settings(home, raw):
    if raw is None:
        return _defaults(home)
    value = _json(raw)
    require(set(value) == {"schema", "home", "providers"} and value["schema"] == SCHEMA
            and value["home"] == str(home) and isinstance(value["providers"], dict)
            and set(value["providers"]) == set(ORDER), "Research settings identity or schema differs")
    for name, item in value["providers"].items():
        require(isinstance(item, dict) and set(item) == ({"state", "retention", "rights_source", "endpoint"}
                if name == "searxng" else {"state", "retention", "rights_source"}), "Unexpected provider settings")
        require(isinstance(item["state"], str) and item["state"] in {"unconfigured", "enabled", "skipped"}
                and isinstance(item["retention"], str) and item["retention"] in {"not_confirmed", "rights_confirmed"}, "Invalid provider state")
        require(item["rights_source"] == (RIGHTS_SOURCE if item["retention"] == "rights_confirmed" else None), "Use the official retention guidance link")
        require(name == "brave" or item["retention"] == "not_confirmed", "Only Brave records this retention acknowledgement")
        if name == "searxng" and item["endpoint"] is not None:
            _endpoint(item["endpoint"])
    return value


def load_settings(home):
    home = _home(home)
    return _settings(home, _read(_directory(home) / "providers.json"))


def _key(value):
    require(isinstance(value, str) and 1 <= len(value) <= 4096
            and all(33 <= ord(c) <= 126 for c in value), "Credential must be a nonempty single-line token")
    return value


def _auth(home, raw):
    if raw is None:
        return {"schema": AUTH_SCHEMA, "home": str(home), "keys": {}}
    value = _json(raw)
    require(set(value) == {"schema", "home", "keys"} and value["schema"] == AUTH_SCHEMA
            and value["home"] == str(home) and isinstance(value["keys"], dict)
            and not set(value["keys"]) - {"exa", "brave", "tavily"}, "Research authentication identity or schema differs")
    for key in value["keys"].values():
        _key(key)
    return value


@dataclass(frozen=True)
class ProviderResolution:
    provider: str
    state: str
    endpoint: str = None
    credential: str = field(default=None, repr=False)
    credential_source: str = "none"
    retention: str = "not_confirmed"
    rights_source: str = None


def resolve_provider(home, provider, environ=None, *, require_retention=True):
    """Trusted helper API; no public/persisted serialization of holder or key.

    A reviewed bounded-child handoff may send minimal validated credentials
    through transient private stdin. Never put the holder in a model result.
    """
    require(provider in ORDER, "Unknown research provider")
    home = _home(home)
    item = load_settings(home)["providers"][provider]
    state = item["state"]
    if state != "enabled":
        return ProviderResolution(provider, state)
    if provider == "brave" and require_retention and item["retention"] != "rights_confirmed":
        return ProviderResolution(provider, "retention_hold")
    env = os.environ if environ is None else environ
    endpoint, credential, origin = None, None, "none"
    if provider == "searxng":
        endpoint = env.get("SEARXNG_URL") or item["endpoint"]
        if not endpoint:
            return ProviderResolution(provider, "endpoint_missing")
        endpoint = _endpoint(endpoint)
    elif provider != "ddg":
        value = env.get(CATALOG[provider]["environment"])
        if value:
            credential, origin = _key(value), "environment"
        else:
            value = _auth(home, _read(_directory(home) / "auth.json"))["keys"].get(provider)
            if not value:
                return ProviderResolution(provider, "credential_missing")
            credential, origin = value, "home"
    return ProviderResolution(provider, "ready", endpoint, credential, origin, item["retention"], item["rights_source"])


def provider_status(home, environ=None):
    home = _home(home)
    settings = load_settings(home)
    env = os.environ if environ is None else environ
    auth = _auth(home, _read(_directory(home) / "auth.json"))
    providers = {}
    for name in ORDER:
        selected = resolve_provider(home, name, environ)
        origin = selected.credential_source
        present = selected.credential is not None
        if name in {"exa", "brave", "tavily"} and settings["providers"][name]["state"] == "enabled":
            origin = "environment" if env.get(CATALOG[name]["environment"]) else "home" if name in auth["keys"] else "none"
            present = origin != "none"
        providers[name] = {"configured_state": settings["providers"][name]["state"],
                           "state": selected.state, "credential_present": present,
                           "credential_source": origin, "tested": False}
    return {"schema": "agent-home-research-status/v1", "providers": providers,
            "guidance_checked": GUIDANCE_CHECKED,
            "limits": "Local configuration only. No provider request, quota check or managed environment forwarding was tested."}


def _replace(path, value, expected):
    require(_read(path) == expected, "Concurrent research settings change")
    raw = (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode()
    require(len(raw) <= MAX_BYTES, "Research settings exceed their size limit")
    fd, name = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            _owned(temporary, protect=True)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(_read(path) == expected, "Concurrent research settings change")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _locked(directory):
    path = directory / "settings.lock"
    if path.exists() or path.is_symlink():
        _owned(path)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "r+b") as stream:
        _owned(path, protect=True)
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ConfigError("Research setup is busy") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def configure_provider(home, provider, state, *, credential=None, endpoint=None,
                       retention_acknowledged=None, remove_credential=False):
    """Human setup only. No credential values in return values or errors."""
    require(provider in ORDER and state in {"enabled", "skipped", "unconfigured"}, "Invalid provider selection")
    require(credential is None or provider in {"exa", "brave", "tavily"}, "This provider has no account key")
    if credential is not None:
        _key(credential)
    require(endpoint is None or provider == "searxng", "Only SearXNG accepts an owned endpoint")
    if endpoint is not None:
        endpoint = _endpoint(endpoint)
    require(retention_acknowledged is None or type(retention_acknowledged) is bool,
            "Retention acknowledgement must be explicit")
    require(retention_acknowledged is None or provider == "brave", "Retention acknowledgement applies to Brave")
    home = _home(home)
    identity = (home / "home.json").read_bytes()
    directory = _directory(home, create=True)
    with _locked(directory):
        config_path, auth_path = directory / "providers.json", directory / "auth.json"
        previous, old_auth = _read(config_path), _read(auth_path)
        settings, auth = _settings(home, previous), _auth(home, old_auth)
        settings["providers"][provider]["state"] = state
        if endpoint is not None:
            settings["providers"][provider]["endpoint"] = endpoint
        if provider == "brave" and retention_acknowledged is not None:
            settings["providers"][provider].update(
                retention="rights_confirmed" if retention_acknowledged else "not_confirmed",
                rights_source=RIGHTS_SOURCE if retention_acknowledged else None)
        if credential is not None:
            auth["keys"][provider] = credential
        if remove_credential:
            auth["keys"].pop(provider, None)
            settings["providers"][provider]["state"] = "skipped"
        require(_home(home) == home and (home / "home.json").read_bytes() == identity, "Home identity changed during research setup")
        if credential is not None or remove_credential:
            _replace(auth_path, auth, old_auth)
        _replace(config_path, settings, previous)
    return provider_status(home, environ={})
