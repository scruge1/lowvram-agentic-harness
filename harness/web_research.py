"""Keyless public search and bounded source retrieval, separate from model mining.

This ports URL identity and extraction/provenance from the existing canonical
research toolchain. An explicit managed home also enables its configured search
provider policy. Calls without a home use DuckDuckGo only. Model mining,
scholarly/archive fallback and browser orchestration remain separate operations.
Retrieved text is evidence, never agent instructions.

Optional native dependencies: ddgs for search; httpx and beautifulsoup4 for
fetch/extraction. Imports and offline utilities work without those packages.
The one-operation child bounds DNS, native-library work and extraction together;
it has no persistent state and never starts a browser, daemon or model.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import posixpath
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict
import urllib.parse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


SOURCE_LINEAGE = (
    {"source": "scripts/rig/search_core.py", "sha256": "9811a8c9442d6d3860972ef29f0d3fcfbbe45bc3228b9a3cadff19a0bbbb65d8",
     "commit": "6e5a08e8", "dirty": False,
     "reuse": "URL identity, domain grouping, separate provider observations"},
    {"source": "scripts/rig/godmode_miner.py", "sha256": "c4f19bda4956d9d4add1490cff3b22b230d99ba3a53a2beae5a44aef628b64e0",
     "commit": "773641fd186c4c393b9e65a1c763b289406be506", "dirty": True,
     "reuse": "BeautifulSoup main-text extraction; raw/clean hashes and attempt provenance",
     "dirty_scope": "Private model-routing changes; reused fetch/extraction portion unchanged"},
)
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "msclkid", "ref_src"}
_UA = "lowvram-agentic-harness-public-research/1.0"
RESPONSE_HEADERS = frozenset({
    "content-type", "content-language", "content-disposition", "cache-control", "vary", "retry-after",
    "content-security-policy", "content-security-policy-report-only", "referrer-policy", "permissions-policy",
    "access-control-allow-origin", "access-control-allow-credentials", "access-control-expose-headers",
    "cross-origin-opener-policy", "cross-origin-embedder-policy", "cross-origin-resource-policy",
    "x-content-type-options", "x-frame-options",
})


class WebResult(TypedDict, total=False):
    schema: str
    ok: bool
    status: str
    reason: Optional[str]
    query: str
    requested_url: str
    hits: List[Dict[str, Any]]
    attempts: List[Dict[str, Any]]
    response: Optional[Dict[str, Any]]
    coverage: Dict[str, Any]


def canonical_url(raw_url: str) -> Optional[str]:
    """Ported identity algorithm. NEVER use its lossy result for retrieval."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    try:
        parts = urllib.parse.urlsplit(raw_url.strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        if parts.username is not None or parts.password is not None:
            return None
        scheme = parts.scheme.lower()
        host = parts.hostname.lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        port = parts.port
        if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            host = ("[" + host + "]" if ":" in host else host) + ":" + str(port)
        elif ":" in host:
            host = "[" + host + "]"
        normalized_path = posixpath.normpath(urllib.parse.unquote(parts.path or "/"))
        if not normalized_path.startswith("/"):
            normalized_path = "/" + normalized_path
        if normalized_path != "/":
            normalized_path = normalized_path.rstrip("/")
        url_path = urllib.parse.quote(normalized_path, safe="/:@!$&'()*+,;=-._~")
        query_items = []
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
            if key.lower().startswith("utm_") or key.lower() in _TRACKING_QUERY_KEYS:
                continue
            query_items.append((key, value))
        query = urllib.parse.urlencode(sorted(query_items))
        return urllib.parse.urlunsplit((scheme, host, url_path, query, ""))
    except (TypeError, ValueError, UnicodeError):
        return None


def coverage_domain(url: str) -> str:
    """Ported best-effort domain grouping, not a public-suffix or truth check."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    if len(labels[-1]) == 2 and labels[-2] in {"ac", "co", "com", "edu", "gov", "net", "org"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast and not (
        getattr(address, "ipv4_mapped", None) or getattr(address, "sixtofour", None)
        or getattr(address, "teredo", None))


def _public_url(url: str) -> urllib.parse.SplitResult:
    if not isinstance(url, str) or not 1 <= len(url) <= 8192 or any(ord(c) <= 32 for c in url):
        raise ValueError("Invalid public URL")
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
        raise ValueError("Only public HTTP(S) URLs without user credentials are supported")
    if parts.port not in (None, 80 if parts.scheme == "http" else 443):
        raise ValueError("Only standard public HTTP(S) ports are supported")
    if host == "localhost" or "." not in host and ":" not in host or host.endswith(
            (".localhost", ".local", ".internal", ".home", ".lan", ".onion")):
        raise ValueError("Private destination is unavailable on the public research route")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        host.encode("idna")
    else:
        if not _public_ip(host):
            raise ValueError("Private destination is unavailable on the public research route")
    return parts


def _resolved_target(url: str):
    parts = _public_url(url)
    host = parts.hostname.encode("idna").decode("ascii")
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(
        host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)})
    if not addresses or len(addresses) > 32 or not all(_public_ip(ip) for ip in addresses):
        raise ValueError("DNS contains an unavailable public destination")
    # Connect to this validated address, not a second hostname lookup. Native
    # HTTPX/HTTPCore Host + sni_hostname retain HTTP routing/TLS verification.
    return parts, host, addresses[0]


def _failure(operation: str, value: str, status: str, reason: Optional[str] = None) -> WebResult:
    result = WebResult(schema="web-" + operation + "/v1", ok=False, status=status, reason=reason or status, attempts=[])
    if operation == "search":
        result.update(query=value, hits=[], coverage={"independent_providers": 0, "corroborated": False})
    else:
        result.update(requested_url=value, response=None)
    return result


def _number(value, minimum, maximum, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not minimum <= value <= maximum or integer and not isinstance(value, int):
        raise ValueError(name + " is outside the supported range")


def _run(operation: str, value: str, timeout: float, **options) -> WebResult:
    _number(timeout, 0.1, 120, "timeout")
    # Do not inherit API keys, proxy configuration, signed-in profiles or
    # PYTHONPATH. Explicit enabled-provider credentials use private stdin only.
    allowed = ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    owned_cache = None
    configured_cache = os.environ.get("XDG_CACHE_HOME")
    if configured_cache and not Path(configured_cache).is_absolute():
        return _failure(operation, value, "runtime_unavailable", "XDG_CACHE_HOME must be an owned absolute path")
    try:
        if not configured_cache:
            owned_cache = tempfile.TemporaryDirectory(prefix="web-research-cache-", dir=environment.get("TMPDIR"))
        environment["XDG_CACHE_HOME"] = configured_cache or owned_cache.name
    except OSError as error:
        return _failure(operation, value, "runtime_unavailable", type(error).__name__)
    try:
        completed = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", operation],
                                   input=json.dumps({"value": value, "timeout": timeout, **options}),
                                   text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, env=environment, check=False, shell=False)
    except subprocess.TimeoutExpired:
        return _failure(operation, value, "timeout", "Total operation deadline exceeded")
    except KeyboardInterrupt:
        return _failure(operation, value, "cancelled")
    except OSError as error:
        return _failure(operation, value, "worker_error", type(error).__name__)
    finally:
        if owned_cache is not None:
            owned_cache.cleanup()
    if completed.returncode != 0:
        return _failure(operation, value, "worker_error")
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or result.get("schema") != "web-" + operation + "/v1" or not isinstance(result.get("ok"), bool):
            raise ValueError("Invalid native result")
        return result
    except (ValueError, TypeError):
        return _failure(operation, value, "invalid_response")


def search(query: str, *, limit: int = 5, timeout: float = 30, home=None, policy=None) -> WebResult:
    """Legacy DDG, or an explicit home's configured search; never truth authority."""
    if not isinstance(query, str) or not query.strip() or len(query) > 4096:
        raise ValueError("query must contain 1 through4096 characters")
    _number(limit, 1, 20, "limit", integer=True)
    _number(timeout, 0.1, 120, "timeout")
    if home is not None:
        from harness import research_search
        research_search.policy(policy, limit)
        try:
            selected_home, providers = research_search.bindings(home)
        except (OSError, ValueError, ImportError):
            return _failure("search", query, "configuration_error", "Managed research configuration is unavailable")
        if any(item.get("credential") and item["credential"] in query for item in providers):
            return _failure("search", "[redacted]", "sensitive_query")
        result = _run("search", query.strip(), timeout, limit=limit, home=selected_home,
                      providers=providers, policy=policy)
        if research_search.contains_credentials(result, providers):
            return _failure("search", query, "invalid_response", "Configured search returned withheld private material")
        return result
    if policy is not None:
        raise ValueError("Search coverage policy requires an explicit managed home")
    return _run("search", query.strip(), timeout, limit=limit)


def fetch(url: str, *, timeout: float = 30, max_bytes: int = 2_097_152,
          max_chars: int = 20_000, max_redirects: int = 3) -> WebResult:
    """Fetch public HTML/plain text; preserve bounded bytes and exact provenance."""
    return _fetch_request(url, timeout=timeout, max_bytes=max_bytes, max_chars=max_chars, max_redirects=max_redirects)


def _fetch_browser_resource(url, *, browser_origin=None, browser_referrer=None, **options):
    """Host-only browser metadata. Never expose arbitrary headers in model tools."""
    _browser_metadata(browser_origin, browser_referrer)
    return _fetch_request(url, browser_origin=browser_origin, browser_referrer=browser_referrer, **options)


def _browser_metadata(origin, referrer):
    headers = {}
    if origin is not None:
        if origin != "null":
            parts = _public_url(origin)
            if parts.path not in ("", "/") or parts.query or parts.fragment:
                raise ValueError("Browser Origin must be an origin")
        headers["Origin"] = origin
    if referrer is not None:
        _public_url(referrer)
        headers["Referer"] = referrer
    return headers


def _fetch_request(url, *, timeout, max_bytes, max_chars, max_redirects, browser_origin=None, browser_referrer=None):
    _number(max_bytes, 1024, 4_194_304, "max_bytes", integer=True)
    _number(max_chars, 80, 100_000, "max_chars", integer=True)
    _number(max_redirects, 0, 5, "max_redirects", integer=True)
    try:
        _public_url(url)
    except (ValueError, UnicodeError):
        return _failure("fetch", url, "blocked", "Unavailable public destination")
    return _run("fetch", url, timeout, max_bytes=max_bytes, max_chars=max_chars, max_redirects=max_redirects,
                browser_origin=browser_origin, browser_referrer=browser_referrer)


def _search_native(query: str, timeout: float, limit: int) -> WebResult:
    from ddgs import DDGS

    hits = DDGS(timeout=timeout).text(query, max_results=limit, page=1, backend="duckduckgo")
    if not isinstance(hits, list):
        return _failure("search", query, "invalid_response")
    by_url = {}
    for rank, item in enumerate(hits[:limit], 1):
        if not isinstance(item, dict):
            continue
        url = item.get("href", "")
        try:
            _public_url(url)
        except (ValueError, UnicodeError):
            continue
        identity = canonical_url(url)
        if identity is None:
            continue
        observation = {"provider": "duckduckgo", "rank": rank, "url": url,
                       "title": str(item.get("title", ""))[:1000], "snippet": str(item.get("body", ""))[:2000]}
        if identity in by_url:
            by_url[identity]["observations"].append(observation)
        else:
            by_url[identity] = {**observation, "canonical_url": identity,
                                "domain": coverage_domain(identity), "observations": [observation]}
    found = list(by_url.values())
    return WebResult(schema="web-search/v1", ok=bool(found), status="ok" if found else "empty", reason=None,
                     query=query, hits=found, attempts=[{"provider": "duckduckgo", "status": "ok" if found else "empty",
                     "result_count": len(hits), "accepted_count": len(found)}],
                     coverage={"independent_providers": 1 if found else 0, "corroborated": False,
                               "unique_domains": sorted({hit["domain"] for hit in found})})


def _clean_html(html: str) -> str:
    # Exact existing main-text algorithm, with a lazy dependency boundary.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    return re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))


def _artifact(url, response, raw, chain, max_chars, truncated=False):
    encoding = response.encoding or "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        encoding, text = "utf-8", raw.decode("utf-8", errors="replace")
    content_type = response.headers.get("content-type", "").lower()
    supported = content_type.split(";", 1)[0].strip() in ("text/html", "application/xhtml+xml", "text/plain")
    challenge = bool("html" in content_type and ("cf-chl-" in text[:65536].lower() or re.search(
        r"(?is)<title[^>]*>[^<]*(?:captcha|just a moment|access denied|security check)", text[:65536])))
    clean = (_clean_html(text) if "html" in content_type else text.strip()) if (
        supported and not truncated and not challenge and 200 <= response.status_code < 300) else ""
    shown = clean[:max_chars]
    response_headers = {key: value for key, value in response.headers.items() if key.lower() in RESPONSE_HEADERS}
    headers_complete = all(len(value) <= 8192 for value in response_headers.values()) and sum(
        len(key) + len(value) for key, value in response_headers.items()) <= 32768
    if not headers_complete:
        response_headers = {}  # Never truncate CSP/CORS into a different policy.
    return {"candidate_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "status_code": response.status_code, "content_type": content_type, "response_encoding": encoding,
            "final_url": url, "redirect_chain": list(chain), "raw_preservation": "httpx-decoded-response-content",
            "raw_content_base64": base64.b64encode(raw).decode("ascii"),
            "raw_content_sha256": hashlib.sha256(raw).hexdigest(), "raw_truncated": truncated,
            "extractor_identity": "beautifulsoup-main-text" if "html" in content_type else "plain-text",
            "extractor_version": "1", "cleaned_text": shown,
            "cleaned_text_full": clean, "cleaned_text_encoding": "utf-8",
            "cleaned_text_sha256": hashlib.sha256(shown.encode("utf-8")).hexdigest(),
            "full_cleaned_text_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
            "text_truncated": len(clean) > max_chars, "content_supported": supported,
            "challenge_detected": challenge, "response_headers": response_headers,
            "response_headers_complete": headers_complete}


def _fetch_native(url, timeout, max_bytes, max_chars, max_redirects, browser_origin=None, browser_referrer=None) -> WebResult:
    result = _failure("fetch", url, "network_error")
    try:
        return _fetch_chain(url, timeout, max_bytes, max_chars, max_redirects, result, browser_origin, browser_referrer)
    except ImportError:
        raise
    except ValueError:
        result.update(status="blocked", reason="Unavailable public destination")
    except Exception as error:
        name = type(error).__name__
        result.update(status="timeout" if "Timeout" in name else "network_error", reason=name)
    return result


def _fetch_chain(url, timeout, max_bytes, max_chars, max_redirects, result, browser_origin=None, browser_referrer=None):
    import httpx

    deadline, current, chain = time.monotonic() + timeout, url, []
    for hop in range(max_redirects + 1):
        parts, host, address = _resolved_target(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result.update(status="timeout", reason="Total operation deadline exceeded")
            return result
        target = httpx.URL(current).copy_with(host=address)
        headers = {"User-Agent": _UA, "Host": parts.netloc, "Accept-Encoding": "identity",
                   "Accept": "text/html,application/xhtml+xml,text/plain"}
        headers.update(_browser_metadata(browser_origin, browser_referrer))
        # A fresh client per hop retains neither cookies nor cross-host TLS state.
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=remaining) as client:
            with client.stream("GET", target, headers=headers, extensions={"sni_hostname": host}) as response:
                entry = {"url": current, "status_code": response.status_code, "location": response.headers.get("location")}
                chain.append(entry)
                result["attempts"].append({**entry, "connected_address": address})
                if response.status_code in (301, 302, 303, 307, 308):
                    if hop == max_redirects or not entry["location"]:
                        result.update(status="redirect_limit", reason="Redirect limit or missing Location")
                        return result
                    current = urllib.parse.urljoin(current, entry["location"])
                    continue  # Revalidate and pin the next public destination.
                raw, truncated = bytearray(), False
                for chunk in response.iter_bytes(chunk_size=16384):
                    remaining_bytes = max_bytes - len(raw)
                    raw.extend(chunk[:remaining_bytes])
                    if len(chunk) > remaining_bytes:
                        truncated = True
                        break
                    if time.monotonic() >= deadline:
                        result.update(status="timeout", reason="Total operation deadline exceeded")
                        return result
                artifact = _artifact(current, response, bytes(raw), chain, max_chars, truncated)
                result["response"] = artifact
                if truncated:
                    result.update(status="too_large", reason="Decoded response exceeds byte limit")
                elif response.status_code in (403, 429):
                    result.update(status="rate_limited" if response.status_code == 429 else "blocked",
                                  reason="HTTP" + str(response.status_code))
                elif response.status_code < 200 or response.status_code >= 300:
                    result.update(status="http_error", reason="HTTP" + str(response.status_code))
                elif not artifact["content_supported"]:
                    result.update(status="unsupported_content", reason="Use a separately qualified document extractor")
                elif artifact["challenge_detected"]:
                    result.update(status="challenge", reason="Public page requires a separate permitted route")
                elif len(artifact["cleaned_text"]) < 80:
                    result.update(status="empty_extraction", reason="Insufficient readable page text")
                else:
                    result.update(ok=True, status="partial" if artifact["text_truncated"] else "ok", reason=None)
                return result
    return result


def _worker(operation: str, request: Dict[str, Any]) -> WebResult:
    value = request["value"]
    try:
        if operation == "search":
            if "providers" in request:
                from harness import research_search
                return research_search.execute(value, request["timeout"], request["limit"], request["home"],
                                               request["providers"], request.get("policy"))
            return _search_native(value, request["timeout"], request["limit"])
        return _fetch_native(value, request["timeout"], request["max_bytes"], request["max_chars"], request["max_redirects"],
                             request.get("browser_origin"), request.get("browser_referrer"))
    except ImportError as error:
        return _failure(operation, value, "dependency_missing", error.name)
    except ValueError:
        if operation == "search" and "providers" in request:
            return _failure(operation, value, "configuration_error", "Invalid configured search state or request")
        return _failure(operation, value, "blocked", "Unavailable public destination")
    except Exception as error:
        name = type(error).__name__
        status = "timeout" if "Timeout" in name else "rate_limited" if "Ratelimit" in name else "network_error"
        return _failure(operation, value, status, name)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker" and sys.argv[2] in ("search", "fetch"):
        request = json.loads(sys.stdin.read(131072))
        print(json.dumps(_worker(sys.argv[2], request), ensure_ascii=True))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("search", "fetch"))
    parser.add_argument("value")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--home", type=Path, help="Explicit managed provider configuration; omitted means DDG only")
    args = parser.parse_args()
    try:
        result = search(args.value, timeout=args.timeout, limit=args.limit, home=args.home) if args.operation == "search" else fetch(args.value, timeout=args.timeout)
    except ValueError as error:
        result = _failure(args.operation, args.value, "invalid_input", str(error))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
