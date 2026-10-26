# Optional search providers

DuckDuckGo is the keyless default. Add other providers only if you want them.
The host uses one configured order: SearXNG, Exa, Brave, Tavily, DuckDuckGo.
An unconfigured or skipped provider is not activated by an ambient API key.
Use the installed home command below. Setup itself sends no provider request.

Run setup directly in your own terminal:

```text
python HOME/agent-home.py research setup
python HOME/agent-home.py research setup --provider tavily
python HOME/agent-home.py research status
python HOME/agent-home.py research skip --provider exa
python HOME/agent-home.py research revisit --provider exa
python HOME/agent-home.py research remove --provider exa
```

Setup shows official links, lets you skip each provider and accepts a key with
hidden terminal input. Enter keeps the saved key; `revisit` lets you replace it.
`skip` keeps the saved key but prevents use, including environment overrides.
`remove` deletes that provider's local key and leaves it skipped. It does not
revoke the provider's account key or remove an environment variable.

Create your own accounts and keys at the official sites. Never paste a key into
agent chat, a tool call, a command argument or a tracked project file. Setup
refuses non-terminal input and aborts if hidden entry is unavailable. It does
not create accounts, open a browser, change billing or validate a key online.

Guidance checked on 26 October 2026; plans and terms can change:

| Provider | Signup and current guidance |
|---|---|
| SearXNG | Use your owned instance root URL, such as `http://127.0.0.1:8888`. Its [search API](https://docs.searxng.org/dev/search_api.html) requires `json` in [`search.formats`](https://docs.searxng.org/admin/settings/settings_search.html). Disabled JSON returns 403; a working HTML page does not prove API readiness. No account key is collected. Setup does not install or probe a service. |
| Exa | [Signup](https://dashboard.exa.ai/), [pricing](https://exa.ai/pricing): $10 monthly credits plus $10 initial credits; no payment method required. [Create a dashboard key](https://exa.ai/docs/get-started/quickstart). Credits are not a fixed query count. |
| Brave | [Dashboard](https://api-dashboard.search.brave.com/), [quickstart](https://api-dashboard.search.brave.com/documentation/quickstart): activate the Search plan, then create its key under API Keys. Card required; $5 monthly credits, no standalone free plan. Review usage limits and auto-reload before enabling it. The [billing FAQ](https://api-dashboard.search.brave.com/documentation/resources/help-feedback) permits a prepaid balance of $0; auto-reload can charge the card and is uncapped if no monthly limit is set. Retained results require [storage rights](https://brave.com/search/api/). |
| Tavily | [Signup](https://app.tavily.com/), [pricing](https://www.tavily.com/pricing): 1,000 credits/month, no card required. Under dashboard API keys, [create a named key and set its monthly usage limit](https://help.tavily.com/articles/9170796666-how-can-i-create-an-api-key). The installed adapter uses [basic Search at 1 credit per request](https://docs.tavily.com/documentation/api-credits). |

Brave stays held unless you explicitly confirm that your current rights cover
stored search results in **both research artifacts and native session history**.
A private artifact also stores data. A key, free credits or a plan name does not
establish storage rights. Revisit can withdraw the acknowledgement. The runtime
must skip a held provider before making a request or retaining its results.
Exa and Tavily setup does not promise unlimited storage or grant rights in third
party content. See the current [Exa terms](https://exa.ai/terms) and
[Tavily terms](https://www.tavily.com/terms), and check source rights for your use.

The installed search adapters use SearXNG JSON search, Exa Search, Brave Web
Search and Tavily basic Search. They do not enable the providers' hosted answer,
research-agent, crawl or map products. A provider website may need JavaScript
for signup; setup prints links for your browser and accepts only the resulting
key in your own terminal. It does not automate login or keep browser cookies.
The SearXNG adapter does not accept account login, HTTP Basic credentials or
proxy authentication; supply an owned endpoint reachable without those fields.

Normal search stops after the first usable configured provider. Missing,
skipped, rights-held or cooling-down providers make no request. A failure may
reach the next configured provider only within the remaining operation budget;
it does not guarantee a result or independent corroboration. DuckDuckGo uses
the explicit keyless backend, with no guaranteed quota or availability. A
blocked or failed request is not evidence that no sources exist.

Fetching a discovered URL is a separate operation. Its bounded retry,
scholarly-candidate and guarded JavaScript rendering routes do not use these
keys. Archive retrieval remains explicit opt-in. Rendering uses a clean browser
without login cookies and can return only a captured text window; it cannot
bypass authentication, a CAPTCHA or site access rules. A search key does not
grant access to a destination page. See [agent-home research tools](AGENT-HOME.md)
for artifact windows and operation budgets.

The existing home identity binds `state/research/providers.json` and
`state/research/auth.json`. The first contains settings; the second contains
local keys with owner-only permissions. Both stay outside Git. Setup uses a
short native file lock, complete candidate validation, drift checks and atomic
file replacement. An interrupted multi-file edit can leave a saved key with an
unchanged provider state; inspect status and revisit instead of assuming setup
completed. It never enables a provider merely because a key exists.

Status returns presence and configuration state, never a key or fingerprint.
“Ready” here means locally configured, **not tested**. This module does not
inspect account quotas, confirm storage rights or prove managed environment
forwarding. Enabled providers can use `EXA_API_KEY`, `BRAVE_API_KEY`,
`TAVILY_API_KEY` or `SEARXNG_URL` before local settings only when the trusted
helper actually receives that variable. No `.env`, global configuration or
another application's key store is searched.

`research_config.resolve_provider` is a trusted host-helper API. Its secret
field is excluded from `repr`; the holder has no default JSON serialization.
Do not serialize the holder, copy credentials into a model request or include
them in HTTP errors, native event records or evidence artifacts. A reviewed
bounded-child handoff may pass only minimal validated credential fields through
transient private stdin; it must not retain or echo that input. A local permission
check is not an OS sandbox: arbitrary code running as the same user can access
that user's files. Normal-path secret suppression and any accidental native
file-read guard are separate from stronger process isolation.

For source development, `python -m harness.research_setup --home HOME ACTION`
is the same parser. The managed entry owns its normal home lifecycle lease;
calling the source module directly does not establish installed lifecycle or
provider acceptance.

Existing homes retain their installed controller and may not expose this grouped
command. Use that home's supported update plan and its exact source constraints;
an update can hold controller changes. Fresh installations include the command.
Preserve existing personal data and do not copy controller files around an
update refusal.
