# Low-VRAM Agentic Harness

A local AI assistant for research, files and ongoing projects. **Early development.**

This repository installs a Pi assistant in a folder you choose. The default setup
includes web research, project Git and task boards, memory tools, and checks for
supervised file work. It uses your configured local model.

The complete assistant is still being qualified. Installation and individual
tool checks have passed in recorded environments; the local CPU candidate has
not yet produced an accepted first report. Expect setup and model limitations,
and review important results.

## Keep a project portable across AI coding assistants

Switching from Gemini to Codex, Claude, Pi or a local model should not erase
architectural decisions or validated work. The [cross-assistant continuity
guide](CROSS-ASSISTANT-CONTINUITY.md) explains how to recover Gemini CLI and
IDE histories, distinguish Google Takeout from local sessions, create a
reviewed handoff packet, and verify the first task on the incoming assistant.
The [candidate handoff template](examples/continuity/handoff.template.json)
records sources, decisions and pending work **without pretending exported chats
are authoritative project state**. No automatic session importer is shipped.

The [8 November 2026 engineering status](NOV-2026-ENGINEERING-STATUS.md)
records recent private work on Pi context lifecycle, repeated tool output,
GPU resource planning and long-running local agents. Those candidates are
not part of this public release until independently qualified.

## Inspect existing Pi sessions safely

For an already-admitted Linux project, the opt-in
[native Pi session catalogue](NATIVE-SESSION-CATALOG.md) can list native
JSONL session headers without reading conversation bodies, creating
another writer or acquiring tool execution authority. It is a local
continuity aid, not a ChatGPT/Gemini/Claude account-history importer.

## Start here

The complete installer currently supports **Linux x86_64 with glibc**. Windows
and macOS have a smaller direct-install route; they do not have the same tested
bootstrap or complete lifecycle support.

```bash
git clone https://github.com/scruge1/lowvram-agentic-harness.git
cd lowvram-agentic-harness
bash install.sh
```

Setup asks where to create your assistant's home, your name, and the address and
exact name of an existing local model. It installs its own Python and Node
runtimes in a permanent folder beside the home. Leave both folders in place.
Model downloads are separate from this default route.

Follow [Getting started](GETTING-STARTED.md) for requirements, personalization,
launch, the first report and reopening work. If you do not have a model server,
the guide links an explicit CPU candidate and its resource and quality limits.

## What is included

- Web search without a paid key, page retrieval, a managed browser and saved
  research sources. Optional providers have [signup and key guidance](RESEARCH-SETUP.md).
- Project files under Git, a project task board, retained work and explicit
  continuation of a selected project.
- Memory tools and a prompt for your current assistant to fill supported personal
  context. Saved memories still need source and accuracy checks.
- Supervised actions with separate output checks and visible failures. Time
  budgets belong to the task; managed sessions have no universal ten-minute cap.

For hardware exploration, the opt-in [read-only dynamic model inventory](DYNAMIC-MODEL-INVENTORY.md)
can inspect GGUF assets and physical GPUs without granting resource ownership or
changing any running model. It does not yet replace the private rig's dynamic
model and GPU selector.

The default profile includes Pi, Hermes, MemPalace, Microsoft Agent Framework
and research. The Claude-mem observer and experimental Harness2/DeepSeek packages
are optional. The full profile is a separate route with different readiness
requirements; it is not needed to try the default assistant.

A browser workspace, complete Library and recorded everyday walkthrough remain
release work. The current entry is the managed command-line assistant.

## Help and technical detail

- [Getting started](GETTING-STARTED.md): install, personalize, launch and reopen.
- [Agent-home guide](AGENT-HOME.md): profiles, repair, updates, lifecycle and exact
  qualification limits.
- [Research setup](RESEARCH-SETUP.md): keyless search, optional free keys and provider limits.
- [Diagnostics](DIAGNOSTICS.md): investigate slow or unreliable work from evidence.
- [Toolkit and developer reference](TOOLKIT.md): low-VRAM inference, Python modules
  and the independent project controller.
- [Upgrade notes](UPGRADES.md) and [release checklist](RELEASE-CHECKLIST.md): changes
  and remaining acceptance work.

Core code is [MIT licensed](LICENSE). Installed third-party packages retain their
own licences; see the [runtime notices](harness/BOOTSTRAP-NOTICES.md).
