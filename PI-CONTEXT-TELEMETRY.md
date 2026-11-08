# Pi context telemetry: effective scope and limits

**Status:** portable read-only introspection. **No provider-payload interception,
model call, tool execution, task approval or complete conversation export.**

The native Pi `agent_capabilities` tool already reports the configured and
active tool registry. Its new auxiliary `context_profile` in tool **details**
records bounded, source-unrevealing measurements from that same invocation:

- SHA-256 and UTF-8 byte length of `ctx.getSystemPrompt()`, when callable.
- Exact configured/active tool counts, and SHA-256/byte lengths of sorted
  active tool parameter schemas and declarations, when the tool registry is
  stable and JSON serialisable.
- `ctx.getContextUsage()`-reported tokens/window when available.
- A hash of the selected model's provider and ID, without its raw credentials.
- An explicit `effective_provider_payload_captured:false` and
  `authority:none` marker.

Unknown values are **null, not zero**. Missing or cyclic schema metadata,
runtime exceptions and registry changes must not make ordinary
`agent_capabilities` discovery fail. No system prompt text, tool schema
body, tool description or API secret is returned in the profile.

The model-facing tool `content` remains the unchanged `pi-native-capabilities/v1`
snapshot. The profile lives in optional `details.context_profile`, where a
host-side diagnostic can compare repeated runs without inflating the model's
normal context.

## Optional local session persistence

The public default computes **no additional context profile** and adds
no prompt/schema-hashing overhead to ordinary `agent_capabilities` calls.

An operator can explicitly set `PI_CONTEXT_PROFILE_ENABLE=1` to include
the hash-only profile in the call's tool details. To additionally append a
small `pi-context-profile/v1` entry to the existing native Pi session
history, set **both** `PI_CONTEXT_PROFILE_ENABLE=1` and
`PI_CONTEXT_PROFILE_PERSIST=1`. Persistence by itself does nothing. No
other service, cloud upload, machine-wide log or agent loop is started.
The append is best effort and cannot grant work.

A context profile is **not a ChatGPT conversation backup**. It contains no
ChatGPT message history, files or screenshots. It also is **not** an exact
capture of a llama.cpp/provider-serialized prompt or a complete,
post-compaction model input. Pi's active prompt, branch selection, tools,
compaction summary and provider formatting are distinct layers. A future
private, explicitly scoped provider-bound capture needs its own
access-control, privacy and completeness qualification.

## Verification

```bash
python -m unittest discover -s tests -p test_pi_context_profile.py -v
```

The synthetic full-extension fixture tests unchanged model-facing capability
content, stable private profile hashes and counts, unknown-versus-zero,
registry drift, cyclic schemas, no prompt leakage, no default session append,
explicit opt-in append and absence of tool/model/network execution.

Before claiming a live token-saving improvement, compare repeated real Pi
requests on the same pinned model/backend and project source. Provider-side
cache accounting, JSONL history retention and useful task quality must be
checked separately. This diagnostic cannot substitute for any of them.
