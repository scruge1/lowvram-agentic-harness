"""Fresh-context Chromium research using native Playwright, never signed-in state.

Playwright (Apache-2.0) owns locators, waits, rendering and downloads. The
existing public HTTPX route owns every HTTP(S) response. Browser requests never
continue directly to the network. This is read-only public research, not a
general browser agent, authentication bridge, crawler, or service.

The existing Linux Pi process guard owns the one-operation worker and all its
browser descendants. Windows process ownership is not qualified by this module.
Text capture skips image, media and font network requests. HTML, CSS,
JavaScript, data requests and explicit downloads retain the guarded transport.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from typing import Any, Dict, Optional, Sequence

try:
    from . import web_research as web
except ImportError:
    import web_research as web


NATIVE_SOURCE = {
    "library": "playwright", "license": "Apache-2.0",
    "api": "https://playwright.dev/python/docs/api/class-browsercontext",
    "method": "Fresh context; DOM locators/waits; armed expect_download; native routing",
    "boundary": "No private CLI paths, browser profiles, cookies or stealth code copied",
}
LAUNCH_ARGS = ["--disable-gpu", "--disable-webgl", "--disable-accelerated-2d-canvas",
               "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run",
               "--js-flags=--max-old-space-size=256", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
               "--disable-quic", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]

_DOM = r"""({offset,limit}) => {
 const root=document.body; let text='',visited=0,more=false;
 if(root){const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
  while((node=walker.nextNode())){if(++visited>5000){more=true;break;}
   const p=node.parentElement;if(!p||p.closest('script,style,nav,footer,header,aside,form'))continue;
   const style=getComputedStyle(p);if(style.display==='none'||style.visibility==='hidden')continue;
   const range=document.createRange();range.setStart(node,0);range.setEnd(node,Math.min(node.length,offset+limit+1));
   if(!range.getClientRects().length)continue;
   const value=node.data.trim();if(value){text+=value.slice(0,offset+limit+1-text.length)+'\n';}
   if(text.length>offset+limit){more=true;break;}}
 }
 const cut=s=>s.trim().slice(0,300);
 const headings=[...document.querySelectorAll('h1,h2,h3')].slice(0,30).map(e=>({level:e.tagName,text:cut(e.textContent)}));
 const links=[...document.querySelectorAll('a[href]')].slice(0,60).map(e=>({text:cut(e.textContent),url:e.href.slice(0,8192)}));
 const tables=[...document.querySelectorAll('table')].slice(0,5).map(t=>({rows:[...t.rows].slice(0,25).map(r=>[...r.cells].slice(0,10).map(c=>cut(c.textContent))),truncated:t.rows.length>25}));
 return {text:text.slice(offset,offset+limit),offset,next_offset:more?offset+limit:null,truncated:more,
  headings,links,tables,node_limit:visited>5000,metadata_truncated:document.querySelectorAll('a[href]').length>60||document.querySelectorAll('table').length>5};
}"""


def _failure(url, status, reason=None):
    return {"schema": "web-browser/v1", "ok": False, "status": status,
            "requested_url": url, "reason": reason or status, "sources": [], "blocked_requests": [], "downloads": []}


def _guard() -> Optional[Path]:
    configured = os.environ.get("PI_WEB_RESEARCH_GUARD")
    root = Path(__file__).resolve().parents[1]
    choices = [Path(configured)] if configured else [root / "pi-task-worker.py", root / "adapters/pi/project-workflow/pi-task-worker.py"]
    for file in choices:
        if file.is_file():
            expected = os.environ.get("PI_WEB_RESEARCH_GUARD_SHA256")
            if configured and (not expected or hashlib.sha256(file.read_bytes()).hexdigest() != expected):
                return None
            return file.resolve()
    return None


def render(url: str, *, timeout: float = 40, max_chars: int = 12_000, offset: int = 0,
           wait_selector: Optional[str] = None, click_selectors: Sequence[str] = (),
           download_selector: Optional[str] = None) -> Dict[str, Any]:
    """One guarded public page operation; selectors come from current DOM evidence.

    No private-network allowlist is exposed. Local fixture access exists only
    through an internal test-supplied transport, never a model/CLI option.
    """
    web._number(timeout, 2, 120, "timeout")
    web._number(max_chars, 80, 50_000, "max_chars", integer=True)
    web._number(offset, 0, 200_000, "offset", integer=True)
    selectors = [item for item in [wait_selector, download_selector] if item is not None] + list(click_selectors)
    if isinstance(click_selectors, str) or len(click_selectors) > 4 or any(
            not isinstance(item, str) or not 1 <= len(item) <= 300 for item in selectors):
        raise ValueError("Use at most four bounded click selectors and one wait/download selector")
    try:
        web._public_url(url)
    except (ValueError, UnicodeError):
        return _failure(url, "blocked", "Unavailable public destination")
    if sys.platform != "linux":
        return _failure(url, "unsupported_platform", "Linux owned-process route required")
    guard = _guard()
    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if guard is None:
        return _failure(url, "dependency_missing", "Reviewed Pi process guard required")
    if not cache or not Path(cache).is_absolute() or not Path(cache).is_dir():
        return _failure(url, "dependency_missing", "Configure an owned PLAYWRIGHT_BROWSERS_PATH")
    request = {"url": url, "timeout": timeout, "max_chars": max_chars, "offset": offset,
               "wait_selector": wait_selector, "click_selectors": list(click_selectors), "download_selector": download_selector}
    encoded = base64.b64encode(json.dumps(request).encode()).decode("ascii")
    allowed = ("PATH", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    temporary = Path(cache).parent / "browser-temp"
    configuration = Path(cache).parent / "browser-config"
    try:
        temporary.mkdir(mode=0o700, exist_ok=True)
        configuration.mkdir(mode=0o700, exist_ok=True)
    except OSError as error:
        return _failure(url, "runtime_unavailable", type(error).__name__)
    environment.update(PLAYWRIGHT_BROWSERS_PATH=cache, PI_TASK_TIMEOUT=str(timeout), PYTHONDONTWRITEBYTECODE="1",
                       CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", TMPDIR=str(temporary),
                       TMP=str(temporary), TEMP=str(temporary), XDG_CACHE_HOME=str(Path(cache).parent),
                       XDG_CONFIG_HOME=str(configuration))
    try:
        process = subprocess.Popen([sys.executable, "-B", str(guard), "--guard", sys.executable, "-B",
                                    str(Path(__file__).resolve()), "--worker", encoded],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    except OSError as error:
        return _failure(url, "runtime_unavailable", type(error).__name__)
    owner, process.stdin = process.stdin, None
    try:
        stdout, stderr = process.communicate(timeout=timeout + 15)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        owner.close()  # Existing guard stops and reaps its complete owned tree.
        try:
            process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            return _failure(url, "cleanup_uncertain", "Owned guard did not settle; preserve its PID " + str(process.pid))
        return _failure(url, "timeout" if process.returncode == 124 else "cancelled")
    finally:
        owner.close()
    if process.returncode == 124:
        return _failure(url, "timeout", "Total operation deadline exceeded; owned guard settled")
    if process.returncode != 0:
        return _failure(url, "worker_error", stderr.decode("utf-8", errors="replace")[-1000:])
    try:
        result = json.loads(stdout)
        if result.get("schema") != "web-browser/v1" or not isinstance(result.get("ok"), bool):
            raise ValueError("Invalid browser result")
    except (ValueError, AttributeError):
        return _failure(url, "invalid_response")
    result["guard_sha256"] = hashlib.sha256(guard.read_bytes()).hexdigest()
    return result


async def _browse_native(request, fetcher=None):
    """Internal transport injection is for explicit owner-controlled fixtures only."""
    from playwright.async_api import async_playwright

    url, timeout = request["url"], request["timeout"]
    result = _failure(url, "browser_error")
    deadline = time.monotonic() + timeout
    sources, blocked, downloads, cache = result["sources"], result["blocked_requests"], result["downloads"], {}
    used_bytes, resource_count = 0, 0
    max_total, max_resource, max_resources = 4_194_304, 524_288, 32
    lock = asyncio.Lock()
    fetcher = fetcher or web._fetch_browser_resource
    def remaining():
        return max(0.1, deadline - time.monotonic())
    def key(value):
        return urllib.parse.urldefrag(value)[0]
    async def get(value, main=False, origin=None, referrer=None):
        nonlocal used_bytes, resource_count
        identity = (key(value), origin, referrer)
        if identity in cache:
            return cache[identity]
        async with lock:
            if identity in cache:
                return cache[identity]
            resource_count += 1
            if resource_count > max_resources or max_total - used_bytes < 1024:
                packet = web._failure("fetch", value, "resource_limit")
            else:
                cap = min(2_097_152 if main else max_resource, max_total - used_bytes)
                try:
                    packet = await asyncio.to_thread(fetcher, value, timeout=min(remaining(), 20), max_bytes=cap,
                                                     max_chars=1000, max_redirects=3 if main else 0,
                                                     browser_origin=origin, browser_referrer=referrer)
                except ValueError:
                    packet = web._failure("fetch", value, "blocked")
                except Exception as error:
                    packet = web._failure("fetch", value, "network_error", type(error).__name__)
            artifact = packet.get("response")
            if artifact:
                raw = base64.b64decode(artifact["raw_content_base64"], validate=True)
                used_bytes += len(raw)
                sources.append({"url": value, "final_url": artifact["final_url"], "status": packet["status"],
                                "http_status": artifact["status_code"], "bytes": len(raw),
                                "raw_sha256": artifact["raw_content_sha256"], "raw_truncated": artifact["raw_truncated"],
                                "redirect_chain": artifact["redirect_chain"]})
                if main or len(raw) <= 131072 and any(kind in artifact["content_type"] for kind in ("text/", "json", "javascript")):
                    sources[-1]["content_base64"] = artifact["raw_content_base64"]
            cache[identity] = packet
            return packet
    initial = await get(url, main=True)
    initial_artifact = initial.get("response")
    if initial_artifact and not initial_artifact.get("response_headers_complete"):
        result.update(status="incompatible_fetch_record", reason="Complete reviewed response headers are required")
        return result
    renderable = bool(initial_artifact and not initial_artifact["raw_truncated"]
                      and 200 <= initial_artifact["status_code"] < 300
                      and "html" in initial_artifact["content_type"] and initial["status"] in ("ok", "partial", "empty_extraction"))
    if not initial.get("ok") and not renderable:
        result.update(status=initial["status"], reason=initial.get("reason"))
        return result
    final_url = initial["response"]["final_url"]
    cache[(key(final_url), None, None)] = initial  # One exact source snapshot, no duplicate root fetch.
    browser = None
    accepted_download = None
    with tempfile.TemporaryDirectory(prefix="web-browser-", dir=Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).parent) as job, \
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as denied_proxy:
        # No proxy service: reserve a port WITHOUT listening. Chromium download
        # traffic can bypass context.route, so unhandled native HTTP must fail.
        denied_proxy.bind(("127.0.0.1", 0))
        proxy = {"server": "http://127.0.0.1:" + str(denied_proxy.getsockname()[1]), "bypass": "<-loopback>"}
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch(headless=True, downloads_path=job, args=LAUNCH_ARGS, proxy=proxy)
                context = await browser.new_context(service_workers="block", accept_downloads=True,
                                                    permissions=[], ignore_https_errors=False)
                context.set_default_timeout(min(remaining() * 1000, 10_000))
                async def route_handler(route):
                    value, method = route.request.url, route.request.method
                    if method != "GET" or not value.startswith(("http://", "https://")):
                        blocked.append({"url": value[:8192], "method": method, "reason": "read_only_public_http"})
                        return await route.abort("blockedbyclient")
                    resource_type = route.request.resource_type
                    if resource_type in {"image", "media", "font"}:
                        blocked.append({"url": value[:8192], "method": method, "resource_type": resource_type,
                                        "reason": "nonessential_text_resource"})
                        return await route.abort("blockedbyclient")
                    metadata = route.request.headers
                    packet = await get(value, origin=metadata.get("origin"), referrer=metadata.get("referer"))
                    artifact = packet.get("response")
                    if not artifact or artifact["raw_truncated"] or not artifact.get("response_headers_complete") or packet["status"] in (
                            "blocked", "challenge", "too_large", "rate_limited", "redirect_limit", "resource_limit", "timeout"):
                        reason = "incompatible_fetch_record" if artifact and not artifact.get("response_headers_complete") else packet["status"]
                        blocked.append({"url": value[:8192], "method": method, "reason": reason})
                        return await route.abort("blockedbyclient")
                    headers = {name: value for name, value in artifact["response_headers"].items()
                               if name.lower() in web.RESPONSE_HEADERS}
                    # Playwright1.64 adds permissive CORS headers to fulfilled
                    # cross-origin responses when ACAO is absent. An explicit
                    # invalid empty value preserves the origin's denial.
                    if metadata.get("origin") and "access-control-allow-origin" not in headers:
                        headers["access-control-allow-origin"] = ""
                    await route.fulfill(status=artifact["status_code"], body=base64.b64decode(artifact["raw_content_base64"]), headers=headers)
                await context.route("**/*", route_handler)
                async def websocket_handler(route):
                    blocked.append({"url": route.url[:8192], "reason": "websocket_unavailable"})
                    await route.close(code=1008, reason="Read-only public research")
                await context.route_web_socket("**/*", websocket_handler)
                page = await context.new_page()
                async def extra_page(other):
                    if other != page:
                        await other.close()
                context.on("page", extra_page)
                async def download_handler(download):
                    if not accepted_download or key(download.url) != accepted_download:
                        blocked.append({"url": download.url[:8192], "reason": "unapproved_download"})
                        await download.cancel()
                page.on("download", download_handler)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)[:500]) if len(errors) < 10 else None)
                await page.goto(final_url, wait_until="domcontentloaded", timeout=remaining() * 1000)
                if request.get("wait_selector"):
                    await page.locator(request["wait_selector"]).wait_for(state="visible", timeout=remaining() * 1000)
                for selector in request.get("click_selectors", []):
                    locator = page.locator(selector)
                    if await locator.count() != 1:
                        raise ValueError("Click requires one current DOM match")
                    await locator.click(timeout=remaining() * 1000)
                if request.get("download_selector"):
                    link = page.locator(request["download_selector"])
                    if await link.count() != 1 or await link.evaluate("e=>e.tagName") != "A":
                        raise ValueError("Download requires one current link")
                    href = await link.get_attribute("href")
                    accepted_download = key(urllib.parse.urljoin(page.url, href or ""))
                    if not accepted_download.startswith(("http://", "https://")):
                        raise ValueError("Only declared HTTP(S) downloads are supported")
                    source_url = accepted_download
                    packet = await get(source_url)
                    expected = packet.get("response")
                    if not expected or expected["raw_truncated"] or not 200 <= expected["status_code"] < 300:
                        raise ValueError("Bounded download source unavailable")
                    source_bytes = base64.b64decode(expected["raw_content_base64"])
                    # Native HTTP download interception is incomplete. Deliver
                    # the guarded source snapshot through a local Blob instead;
                    # never click the remote network-download link.
                    accepted_download = await page.evaluate("""data=>{
                      const s=atob(data),bytes=new Uint8Array(s.length);
                      for(let i=0;i<s.length;i++)bytes[i]=s.charCodeAt(i);
                      const u=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
                      const a=document.createElement('a');a.id='__host_research_download';a.href=u;
                      a.download='research-download.bin';a.textContent='Research download';
                      a.style='position:fixed;top:0;left:0;z-index:2147483647';document.body.appendChild(a);return u;
                    }""", base64.b64encode(source_bytes).decode("ascii"))
                    if not accepted_download.startswith("blob:"):
                        raise ValueError("Native browser did not create a local download")
                    async with page.expect_download(timeout=remaining() * 1000) as event:
                        await page.locator('#__host_research_download').click(timeout=remaining() * 1000)
                    download = await event.value
                    actual = Path(await download.path())
                    if actual.stat().st_size > max_resource:
                        raise ValueError("Download exceeds byte limit")
                    raw = actual.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != expected["raw_content_sha256"]:
                        raise ValueError("Download does not match its guarded source bytes")
                    downloads.append({"url": source_url, "browser_download_url": download.url,
                                      "transport": "host-fetch/browser-blob", "suggested_filename": download.suggested_filename[:200],
                                      "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                      "content_base64": base64.b64encode(raw).decode("ascii")})
                    await page.evaluate("u=>{document.querySelector('#__host_research_download')?.remove();URL.revokeObjectURL(u)}", accepted_download)
                document = await page.evaluate(_DOM, {"offset": request["offset"], "limit": request["max_chars"]})
                document["text_sha256"] = hashlib.sha256(document["text"].encode()).hexdigest()
                result.update(ok=bool(document["text"].strip()), status="partial" if blocked or errors or document["truncated"] else "ok",
                              reason=None, page_url=page.url, source_final_url=final_url, title=(await page.title())[:500],
                              document=document, resource_bytes=used_bytes, resource_count=resource_count, page_errors=errors,
                              browser_version=browser.version, native_api="playwright", clean_context=True,
                              launch_args=list(LAUNCH_ARGS), native_network="reserved_unlistening_proxy", proxy=proxy)
                if not result["ok"]:
                    result.update(status="empty_extraction", reason="No readable rendered text")
            finally:
                if browser is not None:
                    await browser.close()
    return result


def _worker(request):
    try:
        return asyncio.run(asyncio.wait_for(_browse_native(request), timeout=request["timeout"]))
    except ImportError as error:
        return _failure(request["url"], "dependency_missing", error.name)
    except Exception as error:
        name = type(error).__name__
        return _failure(request["url"], "timeout" if "Timeout" in name else "browser_error", str(error)[-1000:])


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        print(json.dumps(_worker(json.loads(base64.b64decode(sys.argv[2]))), ensure_ascii=True))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--wait-selector")
    args = parser.parse_args()
    result = render(args.url, timeout=args.timeout, wait_selector=args.wait_selector)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
