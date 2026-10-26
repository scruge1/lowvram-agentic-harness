# Low-VRAM Agentic Harness

A local AI assistant for research, files and ongoing projects. **Early development.**

This repository installs a Pi assistant in a folder you choose. The default setup
includes web research, project Git and task boards, memory tools, and checks for
supervised file work. It uses your configured local model.

The complete assistant is still being qualified. Installation and individual
tool checks have passed in recorded environments; the local CPU candidate has
not yet produced an accepted first report. Expect setup and model limitations,
and review important results.

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
