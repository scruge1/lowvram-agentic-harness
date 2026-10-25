# Optional search providers

DuckDuckGo is the keyless default. Add other providers only if you want them.
The host uses one configured order: SearXNG, Exa, Brave, Tavily, DuckDuckGo.
An unconfigured or skipped provider is not activated by an ambient API key.
These source modules need the managed-command integration before an installed
home offers the commands below. Setup itself sends no provider request.

Run setup directly in your own terminal:

```text
python HOME/agent-home.py research setup
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

Guidance checked on 25 October 2026; plans and terms can change:

| Provider | Signup and current guidance |
|---|---|
| SearXNG | Use your explicitly owned instance. Its [search API](https://docs.searxng.org/dev/search_api.html) needs JSON enabled; many public instances disable it. No account key is collected. Setup does not install or probe a service. |
| Exa | [Signup](https://dashboard.exa.ai/), [pricing](https://exa.ai/pricing): $10 monthly credits plus $10 initial credits; no payment method required. Credits are not a fixed query count. |
| Brave | [Dashboard](https://api-dashboard.search.brave.com/), [quickstart](https://api-dashboard.search.brave.com/documentation/quickstart), [plans and storage guidance](https://brave.com/search/api/): $5 monthly credits, card required, no standalone free plan. Retained results require storage rights. |
| Tavily | [Signup](https://app.tavily.com/), [pricing](https://www.tavily.com/pricing): 1,000 credits/month, no card required. [Create a key](https://help.tavily.com/articles/9170796666-how-can-i-create-an-api-key) and set its monthly usage limit. Endpoint/options determine credit use. |

Brave stays held unless you explicitly confirm that your current rights cover
stored search results in **both research artifacts and native session history**.
A private artifact also stores data. A key, free credits or a plan name does not
establish storage rights. Revisit can withdraw the acknowledgement. The runtime
must skip a held provider before making a request or retaining its results.
Exa and Tavily setup does not promise unlimited storage or grant rights in third
party content. See the current [Exa terms](https://exa.ai/terms) and
[Tavily terms](https://www.tavily.com/terms), and check source rights for your use.

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
