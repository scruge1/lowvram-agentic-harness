"""Bounded retrieval fallbacks over the existing guarded public transports.

Adapt the scholarly candidates, retry budget and attempt custody from
scripts/rig/godmode_miner.py (_candidates, robust_fetch_v2). Do not port its
unrestricted HTTP client, user-agent rotation, model route or private state.
No alternate source establishes completeness of the originally requested work.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import re
import time

from . import web_research as web


SOURCE_LINEAGE = {
    "source": "scripts/rig/godmode_miner.py",
    "sha256": "c4f19bda4956d9d4add1490cff3b22b230d99ba3a53a2beae5a44aef628b64e0",
    "reuse": "Scholarly candidate intent, total retry budget, selected-attempt provenance",
    "limits": "Adaptation to guarded public transports; not whole private-script or live-use parity",
}
BROWSER_SETTLEMENT_RESERVE = 30.0
BROWSER_MINIMUM_WORK = 10.0
BROWSER_HANDOFF_RESERVE = 0.25
MAX_RETRY_DELAY = 8.0
ATTEMPTS_PER_CANDIDATE = 3
THIN_HTML_CHARACTERS = 400
MAX_EVIDENCE_BYTES = 24 * 1024 * 1024  # Leave8MiB for the existing32MiB store record.
MARKER_HEADROOM = 32768
_PAPER = re.compile(r"/(abs|pdf)/((?:\d{4}\.\d{4,5}|[A-Za-z0-9.-]+/\d{7})(?:v[1-9]\d*)?)(?:\.pdf)?/?\Z")


def candidates(url, *, allow_archive=False):
    """Syntax-only selection. Every actual transport still checks public DNS."""
    parsed = web._public_url(url)
    values = []
    match = _PAPER.fullmatch(parsed.path) if parsed.hostname in {"arxiv.org", "www.arxiv.org"} else None
    if match and not parsed.query and not parsed.fragment:
        paper = match.group(2)
        values.append({"url": "https://ar5iv.org/abs/" + paper, "kind": "scholarly_html"})
        values.append({"url": url, "kind": "abstract" if match.group(1) == "abs" else "original"})
        values.append({"url": "https://arxiv.org/abs/" + paper, "kind": "abstract"})
    else:
        values.append({"url": url, "kind": "original"})
    # No signed/query/fragment URL is disclosed to an archive by this policy.
    if allow_archive and not parsed.query and not parsed.fragment and parsed.hostname != "web.archive.org":
        values.append({"url": "https://web.archive.org/web/2id_/" + url, "kind": "archive"})
    seen = set()
    return [item for item in values if not (item["url"] in seen or seen.add(item["url"]))]


def _retry_delay(packet, attempt, wall_time):
    artifact = packet.get("response") or {}
    headers = artifact.get("response_headers") or {}
    value = headers.get("retry-after")
    if value is None:
        return min(0.5 * 2 ** attempt, MAX_RETRY_DELAY)
    try:
        text = str(value).strip()
        if text.isdigit():
            return float(text)
        date = parsedate_to_datetime(text)
        if date.tzinfo is None:
            return None
        return max(0.0, date.timestamp() - wall_time())
    except (TypeError, ValueError, OverflowError):
        return None  # Do not guess an earlier retry when a server header is invalid.


def _transient(packet):
    code = (packet.get("response") or {}).get("status_code")
    return packet.get("status") in {"timeout", "network_error", "rate_limited"} or code in {429, 500, 502, 503, 504}


def _protected_failure(packet):
    artifact = packet.get("response") or {}
    return (artifact.get("challenge_detected") is True or packet.get("status") == "challenge"
            or artifact.get("status_code") in {401, 407}
            or packet.get("status") in {"cancelled", "cleanup_uncertain"}
            or packet.get("status") == "blocked" and artifact.get("status_code") != 403)


def _fetch_text(packet):
    return str((packet.get("response") or {}).get("cleaned_text_full") or "")


def _retained_capture_complete(response, max_bytes):
    """A short display window does not truncate the separately retained source."""
    if (response.get("raw_truncated") is not False or response.get("content_supported") is not True
            or response.get("challenge_detected") is not False
            or type(response.get("status_code")) is not int or not 200 <= response["status_code"] < 300):
        return False
    full, shown, encoded = (response.get(key) for key in ("cleaned_text_full", "cleaned_text", "raw_content_base64"))
    if (not all(isinstance(value, str) for value in (full, shown, encoded)) or not full.strip()
            or not full.startswith(shown) or not shown
            or type(response.get("text_truncated")) is not bool
            or response["text_truncated"] != (len(shown) < len(full))
            or len(encoded) > 4 * ((max_bytes + 2) // 3)):
        return False
    try:
        raw = base64.b64decode(encoded, validate=True)
        return (len(raw) <= max_bytes
                and hashlib.sha256(raw).hexdigest() == response.get("raw_content_sha256")
                and hashlib.sha256(full.encode("utf-8")).hexdigest() == response.get("full_cleaned_text_sha256")
                and hashlib.sha256(shown.encode("utf-8")).hexdigest() == response.get("cleaned_text_sha256"))
    except (ValueError, UnicodeError):
        return False


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fetch(url, *, timeout=30, max_bytes=2_097_152, max_chars=20_000, max_redirects=3,
          allow_archive=False, allow_browser=False, fetcher=None, renderer=None,
          clock=None, sleeper=None, wall_time=None):
    """Return selected text, scope and complete native attempt packets.

    Transport functions are injected only by trusted host tests/integration.
    The browser has a separate native cleanup reserve. This cooperative budget
    cannot preempt a transport that violates its own timeout/settlement contract.
    """
    web._number(timeout, 0.1, 120, "timeout")
    web._number(max_bytes, 1024, 8_388_608, "max_bytes", integer=True)
    web._number(max_chars, 80, 50_000, "max_chars", integer=True)
    web._number(max_redirects, 0, 5, "max_redirects", integer=True)
    if type(allow_archive) is not bool or type(allow_browser) is not bool:
        raise ValueError("Fallback choices must be explicit booleans")
    plans = candidates(url, allow_archive=allow_archive)
    clock, sleeper, wall_time = clock or time.monotonic, sleeper or time.sleep, wall_time or time.time
    fetcher = fetcher or web.fetch
    started = clock()
    deadline = started + timeout
    # Keep all static candidates/retries within one phase. Otherwise a slow
    # successful shell can leave only a few seconds to start Chromium.
    browser_reserved = allow_browser and timeout > (
        BROWSER_SETTLEMENT_RESERVE + BROWSER_MINIMUM_WORK + BROWSER_HANDOFF_RESERVE + 0.1)
    static_deadline = (deadline - BROWSER_SETTLEMENT_RESERVE - BROWSER_MINIMUM_WORK
                       - BROWSER_HANDOFF_RESERVE) if browser_reserved else deadline
    result = {"schema": "research-fetch/v1", "ok": False, "status": "exhausted",
              "requested_url": url, "reason": "No candidate supplied readable text",
              "attempts": [], "selected_attempt": None, "selected_url": None,
              "selected_kind": None, "selected_native": None, "response": None,
              "document": None, "text": "", "content_scope": "none",
              "requested_source_complete": False, "elapsed_seconds": 0.0,
              "deadline_seconds": timeout, "fallbacks": {"archive": allow_archive, "browser": allow_browser},
              "budget": {"browser_reserved": browser_reserved,
                         "static_phase_seconds": static_deadline - started,
                         "browser_minimum_work_seconds": BROWSER_MINIMUM_WORK,
                         "browser_handoff_reserve_seconds": BROWSER_HANDOFF_RESERVE,
                         "browser_settlement_reserve_seconds": BROWSER_SETTLEMENT_RESERVE}}

    def finish(status=None, reason=None):
        result["elapsed_seconds"] = max(0.0, clock() - started)
        if status is not None:
            result.update(status=status, reason=reason)
        return result

    def record(candidate, mode, packet, began):
        entry = {"candidate_url": candidate["url"], "kind": candidate["kind"],
                 "mode": mode, "elapsed_seconds": max(0.0, clock() - began),
                 "retrieved_at": datetime.now(timezone.utc).isoformat(),
                 "status": packet.get("status", "invalid_response"), "native": packet}
        result["attempts"].append(entry)
        if len(_wire(result)) <= MAX_EVIDENCE_BYTES - MARKER_HEADROOM:
            return True
        # Explicit failed custody instead of silently dropping a response body.
        raw = _wire(packet)
        response = packet.get("response") or {}
        entry.update(status="evidence_limit", native=None,
                     omitted_native={"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                     "status": packet.get("status"),
                                     "raw_content_sha256": response.get("raw_content_sha256"),
                                     "final_url": str(response.get("final_url") or packet.get("page_url") or "")[:8192],
                                     "reason": "Complete packet exceeds cumulative evidence budget; body not retained"})
        return False

    def select(candidate, mode, packet, text):
        artifact = packet.get("response") or {}
        scope = {"archive": "archived_snapshot", "abstract": "abstract_only",
                 "scholarly_html": "scholarly_html"}.get(candidate["kind"], "full_extraction")
        if mode == "render":
            scope = "captured_browser_window"
        thin = mode == "fetch" and "html" in str(artifact.get("content_type", "")).lower() and len(text.strip()) < THIN_HTML_CHARACTERS
        if thin and scope == "full_extraction":
            scope = "thin_extraction"
        complete = (candidate["kind"] == "original" and mode == "fetch" and packet.get("status") in {"ok", "partial"}
                    and not thin and _retained_capture_complete(artifact, max_bytes))
        result.update(ok=True, selected_attempt=len(result["attempts"]) - 1,
                      selected_kind=candidate["kind"], selected_native=packet,
                      selected_url=artifact.get("final_url") or packet.get("page_url") or candidate["url"],
                      response=packet.get("response"), document=packet.get("document"),
                      text=text, content_scope=scope, requested_source_complete=complete)
        if len(_wire(result)) > MAX_EVIDENCE_BYTES - MARKER_HEADROOM:
            index = result["selected_attempt"]
            result.update(ok=False, selected_attempt=None, selected_native=None, response=None,
                          document=None, text="", content_scope="none", requested_source_complete=False,
                          withheld_selection_attempt=index)
            return finish("evidence_limit", "Native attempt retained; selected projection exceeds cumulative evidence budget")
        return finish("ok" if complete else "partial", None)

    def invoke(function, value, **kwargs):
        try:
            packet = function(value, **kwargs)
            return packet if isinstance(packet, dict) else {"ok": False, "status": "invalid_response"}
        except Exception as error:
            # Do not expose URLs, response bodies, environment or exception text.
            state = "timeout" if isinstance(error, TimeoutError) else "network_error" if isinstance(error, OSError) else "adapter_error"
            return {"ok": False, "status": state, "error_type": type(error).__name__}

    for candidate in plans:
        # Archive candidates never invoke Chromium and need no browser reserve.
        candidate_deadline = deadline if candidate["kind"] == "archive" else static_deadline
        for attempt in range(ATTEMPTS_PER_CANDIDATE):
            remaining = candidate_deadline - clock()
            if remaining < 0.1:
                return finish("timeout", "Static retrieval budget exhausted; browser work and settlement remain reserved"
                              if browser_reserved and candidate["kind"] != "archive" else "Total retrieval budget exhausted")
            available = MAX_EVIDENCE_BYTES - MARKER_HEADROOM - len(_wire(result))
            if available < 8192:
                return finish("evidence_limit", "No bounded capacity remains for another native attempt")
            packet_bytes = min(max_bytes, available // 8)
            began = clock()
            packet = invoke(fetcher, candidate["url"], timeout=min(30, remaining), max_bytes=packet_bytes,
                            max_chars=max_chars, max_redirects=max_redirects)
            if not record(candidate, "fetch", packet, began):
                return finish("evidence_limit", "Native packet omitted with exact custody hash; no further attempt")
            if clock() >= deadline:
                return finish("timeout", "Total retrieval budget exhausted; late packet retained")
            if _protected_failure(packet):
                return finish(packet.get("status", "blocked"), "Native policy, authentication, challenge or unsettled transport hold")
            text = _fetch_text(packet)
            artifact = packet.get("response") or {}
            thin = "html" in str(artifact.get("content_type", "")).lower() and len(text.strip()) < THIN_HTML_CHARACTERS
            if packet.get("ok") is True and text.strip() and not (allow_browser and thin):
                return select(candidate, "fetch", packet, text)
            code = (packet.get("response") or {}).get("status_code")
            if _transient(packet):
                delay = _retry_delay(packet, attempt, wall_time)
                if attempt + 1 >= ATTEMPTS_PER_CANDIDATE:
                    return finish(packet.get("status", "exhausted"), "Transient retries exhausted; no quota or outage bypass")
                if delay is None or not math.isfinite(delay) or delay > MAX_RETRY_DELAY or delay + 0.1 >= candidate_deadline - clock():
                    return finish(packet.get("status", "timeout"), "Retry deferred; server delay or remaining budget prevents a bounded retry")
                result["attempts"][-1]["retry_delay_seconds"] = delay
                sleeper(delay)
                continue
            # Browser fallback reads only a successful, unchallenged HTML page.
            artifact = packet.get("response") or {}
            html = "html" in str(artifact.get("content_type", "")).lower()
            if (allow_browser and candidate["kind"] != "archive" and html
                    and isinstance(code, int) and 200 <= code < 300 and not artifact.get("raw_truncated")
                    and packet.get("status") in {"empty_extraction", "ok", "partial"}):
                remaining = deadline - clock() - BROWSER_SETTLEMENT_RESERVE
                if remaining < BROWSER_MINIMUM_WORK:
                    result["attempts"][-1]["browser_hold"] = "Insufficient remaining budget for minimum render work and native settlement"
                else:
                    if renderer is None:
                        from .web_browser import render
                        renderer = render
                    began = clock()
                    rendered = invoke(renderer, candidate["url"], timeout=min(40, remaining), max_chars=max_chars)
                    if not record(candidate, "render", rendered, began):
                        return finish("evidence_limit", "Rendered packet omitted with exact custody hash; no further attempt")
                    if clock() >= deadline:
                        return finish("timeout", "Total retrieval budget exhausted; rendered packet retained")
                    if _protected_failure(rendered):
                        return finish(rendered.get("status", "blocked"), "Native browser hold; no fallback replay")
                    text = str((rendered.get("document") or {}).get("text") or "")
                    if rendered.get("ok") is True and text.strip():
                        return select(candidate, "render", rendered, text)
            static_text = _fetch_text(packet)
            if packet.get("ok") is True and static_text.strip():
                return select(candidate, "fetch", packet, static_text)
            # A generic403 is not a reason to launch a browser or ask an archive.
            # Published arXiv representations are separate canonical candidates.
            if code == 403 and not any(item["kind"] == "scholarly_html" for item in plans):
                return finish("blocked", "HTTP403 preserved; no access-control bypass")
            if code == 403 and candidate["kind"] == "abstract":
                return finish("blocked", "Scholarly representations unavailable; no archive bypass")
            break
    return finish()
