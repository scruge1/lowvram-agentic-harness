"""Configured search policy, adapted from the existing canonical search core.

The host resolves the sole research_config catalog before sending a bounded
private request to its worker. Credentials never belong in returned evidence.
This module adds no model, browser, account, service or general fetch fallback.
"""
from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import json
import math
import os
import re
import socket
import stat
import tempfile
import time
import urllib.parse

from . import web_research as web


SOURCE_SHA256 = "9811a8c9442d6d3860972ef29f0d3fcfbbe45bc3228b9a3cadff19a0bbbb65d8"
COOLDOWN_S = 6 * 3600
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STATE_BYTES = 65536
UNATTEMPTED = {"unconfigured", "skipped", "credential_missing", "endpoint_missing", "retention_hold"}


def _normalized_phrase(value):
    return " ".join(re.findall(r"[a-z0-9]+", urllib.parse.unquote(str(value)).lower()))


def _is_relevant(result, required_tokens):
    """Require each declared phrase in the result, without assessing its truth."""
    haystack = _normalized_phrase(" ".join((result.get("t", ""), result.get("s", ""), result.get("u", ""))))
    padded_haystack = " " + haystack + " "
    return all(" " + token + " " in padded_haystack for token in required_tokens)


def policy(value, limit):
    """Canonical coverage policy; None explicitly selects first-success mode."""
    if value is None:
        return {"provider_budget": 5, "minimum_providers": 1, "minimum_unique_domains": 1,
                "required_tokens": [], "results_per_provider": limit, "mode": "first_success"}
    if not isinstance(value, dict):
        raise ValueError("policy must be an object")
    fields = {"provider_budget", "minimum_providers", "minimum_unique_domains", "required_tokens"}
    if not fields.issubset(value) or set(value) - fields - {"results_per_provider"}:
        raise ValueError("Invalid search policy fields")
    numeric = {}
    for field in ("provider_budget", "minimum_providers", "minimum_unique_domains"):
        item = value[field]
        if type(item) is not int or not 1 <= item <= (5 if field != "minimum_unique_domains" else 100):
            raise ValueError("Invalid " + field)
        numeric[field] = item
    if not 2 <= numeric["minimum_providers"] <= numeric["provider_budget"]:
        raise ValueError("Coverage requires at least two providers within the request budget")
    per_provider = value.get("results_per_provider", limit)
    if type(per_provider) is not int or not 1 <= per_provider <= 20:
        raise ValueError("results_per_provider must be 1 through20")
    tokens = value["required_tokens"]
    if not isinstance(tokens, (list, tuple)) or not 1 <= len(tokens) <= 32:
        raise ValueError("required_tokens must contain 1 through32 phrases")
    normalized = []
    for token in tokens:
        if not isinstance(token, str) or len(token) > 256 or not _normalized_phrase(token):
            raise ValueError("Invalid required search phrase")
        phrase = _normalized_phrase(token)
        if phrase not in normalized:
            normalized.append(phrase)
    return {**numeric, "required_tokens": normalized, "results_per_provider": per_provider, "mode": "coverage"}


def bindings(home):
    """Trusted host-only IPC material; never serialize the resolver dataclass."""
    from . import research_config
    settings = research_config.load_settings(home)
    selected = []
    for name in research_config.ORDER:
        item = research_config.resolve_provider(home, name, require_retention=True)
        selected.append({"provider": name, "state": item.state, "endpoint": item.endpoint,
                         "credential": item.credential})
    return settings["home"], selected


def contains_credentials(value, selected):
    """Check decoded output, not serialized/escaped representations of secrets."""
    secrets = [item["credential"] for item in selected if item.get("credential")]
    def contains(item):
        if isinstance(item, str):
            return any(secret in item for secret in secrets)
        if isinstance(item, dict):
            return any(contains(key) or contains(val) for key, val in item.items())
        if isinstance(item, (list, tuple)):
            return any(contains(val) for val in item)
        return False
    return contains(value)


def _path(home):
    from . import research_config
    # Settings and cooldown state share the existing protected directory owner.
    # In particular, mkdir(mode=700) alone does not set a Windows DACL.
    directory = research_config._directory(research_config._home(home), create=True)
    return directory / "provider-cooldowns.json"


def _read(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_STATE_BYTES:
        raise ValueError("Invalid bounded search state file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Search state grew beyond its byte limit")
    return raw


@contextmanager
def _state_lock(path, deadline):
    lock = path.with_suffix(path.suffix + ".lock")
    if lock.exists() or lock.is_symlink():
        _read(lock)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"\0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Search state admission deadline") from None
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        yield
    finally:
        # Close only this operation's description; no inherited owner is unlocked.
        os.close(descriptor)


def _atomic_write(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Search state exceeds its byte limit")
    descriptor, temporary = tempfile.mkstemp(prefix=".search-provider-state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _read(path)  # Refuse a redirected/replaced destination before publication.
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_state(path, names, now):
    """Recover canonical backup and cap poisoned cooldowns, retaining old bytes."""
    raw, state, recovered = _read(path), {}, False
    try:
        state = json.loads(raw) if raw is not None else {}
        if not isinstance(state, dict):
            raise ValueError("Search state is not an object")
    except (ValueError, UnicodeError):
        backup = _read(path.with_suffix(path.suffix + ".bak"))
        try:
            state = json.loads(backup) if backup is not None else {}
            if not isinstance(state, dict):
                state = {}
        except (ValueError, UnicodeError):
            state = {}
        recovered = True
    clean = {}
    for name in names:
        until = state.get(name, {}).get("cooldown_until") if isinstance(state.get(name), dict) else None
        if type(until) in (int, float) and math.isfinite(until) and until > now:
            clean[name] = {"cooldown_until": min(until, now + COOLDOWN_S)}
    return clean, recovered or clean != state, raw


def _state(home, names, deadline, *, rate_limited=None):
    path, now = _path(home), time.time()
    with _state_lock(path, deadline):
        state, changed, previous = _load_state(path, names, now)
        if rate_limited is not None:
            state[rate_limited] = {"cooldown_until": now + COOLDOWN_S}
            changed = True
        if changed:
            # Publish the repaired current file before rotating its predecessor;
            # a malformed current file must not first erase the valid backup.
            _atomic_write(path, state)
            if previous is not None:
                backup = path.with_suffix(path.suffix + ".bak")
                # Keep the exact predecessor even if it is malformed JSON.
                _read(backup)
                descriptor, staged = tempfile.mkstemp(prefix=".search-state-backup-", dir=path.parent)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(previous)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(staged, backup)
        return state


def _searx_target(url):
    """Only the explicit operator endpoint may address its owned local service."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None \
            or parts.password is not None or parts.fragment or any(ord(c) <= 32 for c in url):
        raise ValueError("Invalid configured search endpoint")
    host = parts.hostname
    answers = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    addresses = sorted({answer[4][0] for answer in answers})
    if not addresses:
        raise ValueError("Configured endpoint has no address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or getattr(ip, "ipv4_mapped", None):
            raise ValueError("Configured endpoint has an unavailable address")
    return parts, host, addresses[0]


def _request(name, selected, query, count, deadline):
    """Native HTTPX, fixed keyed endpoints, no redirects/cookies/proxy inheritance."""
    import httpx
    credential = selected.get("credential")
    headers, body, method = {"Accept": "application/json", "Accept-Encoding": "identity"}, None, "GET"
    if name == "searxng":
        url = selected["endpoint"].rstrip("/") + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    elif name == "exa":
        url, method = "https://api.exa.ai/search", "POST"
        headers["x-api-key"] = credential
        body = {"query": query, "numResults": count, "type": "auto", "contents": {"text": {"maxCharacters": 300}}}
    elif name == "brave":
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": query, "count": count})
        headers["X-Subscription-Token"] = credential
    elif name == "tavily":
        url, method = "https://api.tavily.com/search", "POST"
        headers["Authorization"] = "Bearer " + credential
        body = {"query": query, "max_results": count, "search_depth": "basic", "include_answer": False,
                "include_raw_content": False, "auto_parameters": False}
    else:
        raise ValueError("Unknown native provider")
    parts, host, address = _searx_target(url) if name == "searxng" else web._resolved_target(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Total search deadline")
    target = httpx.URL(url).copy_with(host=address)
    headers.update({"Host": parts.netloc, "User-Agent": web._UA})
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=min(remaining, 25)) as client:
        with client.stream(method, target, headers=headers, json=body, extensions={"sni_hostname": host}) as response:
            if response.status_code == 429:
                return [], "rate_limited"
            if not 200 <= response.status_code < 300:
                return [], "http_" + str(response.status_code)
            raw = bytearray()
            for chunk in response.iter_bytes(chunk_size=16384):
                if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                    return [], "too_large"
                raw.extend(chunk)
                if time.monotonic() >= deadline:
                    raise TimeoutError("Total search deadline")
            data = json.loads(bytes(raw))
    if not isinstance(data, dict):
        return [], "invalid_response"
    rows = data.get("web", {}).get("results", []) if name == "brave" else data.get("results", [])
    if not isinstance(rows, list):
        return [], "invalid_response"
    key = "text" if name == "exa" else "description" if name == "brave" else "content"
    hits = [{"t": row.get("title", ""), "u": row.get("url", ""),
             "s": " ".join(str(row.get(key, "") or "").split())[:2000]}
            for row in rows[:count] if isinstance(row, dict)]
    return hits, "ok" if hits else "empty"


def execute(query, timeout, limit, home, selected, selected_policy=None):
    """Canonical coverage/skip/budget algorithm, scoped to one owned operation."""
    rules = policy(selected_policy, limit)
    deadline = time.monotonic() + timeout
    names = [item["provider"] for item in selected]
    state = _state(home, names, deadline)
    secrets = [item["credential"] for item in selected if item.get("credential")]
    if any(secret in query for secret in secrets):
        return web._failure("search", "[redacted]", "sensitive_query")
    attempted, considered, attempts, by_url, contributing = 0, 0, [], {}, []
    met, expired = False, False
    for item in selected:
        if attempted >= rules["provider_budget"]:
            break
        name, considered = item["provider"], considered + 1
        until = state.get(name, {}).get("cooldown_until", 0)
        if item["state"] != "ready" or until > time.time():
            status = item["state"] if item["state"] != "ready" else "cooling_down"
            attempts.append({"provider": name, "attempted": False, "status": status,
                             "result_count": 0, "accepted_count": 0, "cooldown_until": until or None})
            continue
        if name == "brave" and (len(query) > 600 or len(query.split()) > 75):
            attempts.append({"provider": name, "attempted": False, "status": "query_unsupported",
                             "result_count": 0, "accepted_count": 0, "cooldown_until": None})
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            expired = True
            break
        started, attempted = time.monotonic(), attempted + 1
        try:
            if name == "ddg":
                native = web._search_native(query, remaining, rules["results_per_provider"])
                rows = [{"t": hit["title"], "u": hit["url"], "s": hit["snippet"]} for hit in native["hits"]]
                status = "ok" if rows else native["status"]
            else:
                rows, status = _request(name, item, query, rules["results_per_provider"], deadline)
        except ImportError:
            rows, status = [], "dependency_missing"
        except Exception as error:
            # Never retain raw exception messages, request URLs, headers or bodies.
            kind = type(error).__name__
            rows, status = [], "timeout" if "Timeout" in kind else "rate_limited" if "Ratelimit" in kind else "provider_error"
        if time.monotonic() >= deadline:
            rows, status, expired = [], "timeout", True
        if status == "rate_limited":
            state = _state(home, names, deadline, rate_limited=name)
        accepted, invalid, withheld = 0, 0, 0
        for rank, raw in enumerate(rows[:rules["results_per_provider"]], 1):
            if not isinstance(raw, dict):
                invalid += 1
                continue
            if any(secret in str(raw.get(key, "")) for secret in secrets for key in ("t", "u", "s")):
                withheld += 1
                continue
            normalized = {key: str(raw.get(key, "") or "")[:4096] for key in ("t", "u", "s")}
            try:
                web._public_url(normalized["u"])
                identity = web.canonical_url(normalized["u"])
                if identity is None:
                    raise ValueError("Invalid result URL")
            except (ValueError, UnicodeError):
                invalid += 1
                continue
            if not _is_relevant(normalized, rules["required_tokens"]):
                continue
            accepted += 1
            observation = {"provider": name, "rank": rank, "title": normalized["t"],
                           "url": normalized["u"], "snippet": normalized["s"]}
            if identity not in by_url:
                by_url[identity] = {**observation, "canonical_url": identity,
                                    "domain": web.coverage_domain(identity), "observations": []}
            by_url[identity]["observations"].append(observation)
        if accepted and name not in contributing:
            contributing.append(name)
        attempts.append({"provider": name, "attempted": True, "status": status,
                         "result_count": len(rows), "accepted_count": accepted, "invalid_url_count": invalid,
                         "withheld_result_count": withheld, "latency_ms": max(0, round((time.monotonic() - started) * 1000)),
                         "cooldown_until": state.get(name, {}).get("cooldown_until")})
        domains = {hit["domain"] for hit in by_url.values()}
        met = len(contributing) >= rules["minimum_providers"] and len(domains) >= rules["minimum_unique_domains"]
        if met or expired:
            break
    exhausted = considered == len(selected)
    reason = "coverage_met" if met else "total_deadline" if expired else "provider_chain_exhausted" if exhausted else "provider_budget_exhausted"
    successful_empty = attempted > 0 and all(a["status"] == "empty" for a in attempts if a["attempted"])
    result_status = "ok" if met else "timeout" if expired else "coverage_unmet" if by_url else "empty" if successful_empty else "providers_unavailable" if not attempted else "search_exhausted"
    return {"schema": "web-search/v1", "query": query, "ok": met, "status": result_status,
            "reason": None if met else reason, "policy": rules, "hits": list(by_url.values()), "attempts": attempts,
            "coverage": {"met": met, "exhausted": not met, "stop_reason": reason,
                         "attempted_providers": attempted, "contributing_providers": contributing,
                         "independent_providers": len(contributing), "corroborated": False,
                         "unique_domains": sorted({hit["domain"] for hit in by_url.values()}),
                         "budget_exhausted": attempted >= rules["provider_budget"], "chain_exhausted": exhausted}}
