# Getting started

This is a development setup for a local command-line assistant. Start with the
default profile. A successful installation does not establish model task quality.
The first-report journey is still under qualification.

## Check what you need

The complete bootstrap supports Linux x86_64 with glibc and checks for Git,
curl, tar and the other required OS commands before setup. It installs its own
Python and Node; it does not change your global versions or shell settings.

Choose a dedicated new home folder on a volume with room for its adjacent
`HOME-runtimes` folder, packages, browser, memory embeddings and project files.
The bootstrap requires at least 8 GiB free for its runtime step. This is not a
complete model and package storage estimate; package totals depend on resolution.

The default route attaches to a model you already run locally. Have its server
address and exact model name ready. Configure context and output limits to match
that server. A compatible API does not establish hardware fit or tool capability.

Without a server, the [explicit CPU setup](AGENT-HOME.md#run-from-a-repository-checkout)
downloads a pinned candidate. It requires eight available CPUs, 20 GiB available
RAM and 20 GiB free storage, with more headroom for later work. Its text-only model
and native server downloads total about 5.05 GB, plus runtimes and dependencies.
It has not yet passed the useful first-report task. It is an experiment, not an
automatic model recommendation.

Windows and macOS users should read the [direct installation route](AGENT-HOME.md#run-from-a-repository-checkout).
Its supported features and dependencies differ from this Linux bootstrap.

## Install your home

From a repository checkout, run:

```bash
bash install.sh
```

Answer the home, model and owner prompts. For a read-only plan with an explicit
destination, use `bash install.sh --home /data/my-agent --plan`. Replace
`/data/my-agent` in this guide with your chosen absolute path.

Web search does not require a paid key. [Optional provider setup](RESEARCH-SETUP.md)
explains free-key signup, hidden key entry, provider limits, skipping and revisiting.
Never paste keys into project notes or a personalization prompt.

## Add supported personal context

Ask the assistant you are already using to read the new home's
`agent/prompts/personalize.md` and follow it. It can fill known preferences and
current project context from your instructions and relevant session history.
Leave unsupported facts unknown. Review the changes; do not copy credentials,
private customer material or unrelated conversations.

## Open the assistant

Use the installed command from any directory:

```bash
/data/my-agent/bin/harness-agent --status
/data/my-agent/bin/harness-agent
```

The command selects that home's model, instructions, tools and memory. Starting
inside an unrelated folder does not make that folder a project automatically.
You can ask it to research a question or work on an explicitly selected project;
inspect retrieved sources and proposed file changes.

## Try the first report

This explicit command starts a real model task, creates a new project and checks
its report against the original measured inputs:

```bash
/data/my-agent/envs/hermes/bin/python -B \
  /data/my-agent/runtime/harness/first_project.py run \
  --home /data/my-agent --name first-report
```

The model must write the report. The helper retains the original inputs and
reports failures. Read the final result and the actual file; a passed mechanical
check still needs review for meaning and usefulness. This route has not yet
produced an accepted report in the recorded local CPU trials.

If it fails, retain the project and logs. Do not rerun the same name or overwrite
the inputs to obtain a pass. The [report guide](AGENT-HOME.md#prepare-the-first-checked-report)
explains the result, time budgets and retained evidence.

## Reopen work or fix setup

For an existing admitted project on the qualified Linux route:

```bash
/data/my-agent/bin/harness-agent --continue \
  --project /data/my-agent/projects/first-report
```

It refuses a missing previous session or an active writer instead of silently
starting fresh. Review the retained failure or waiting condition before more work.

For a failed installation, keep both folders and inspect the exact reported
stage before [repair or explicit installer resume](AGENT-HOME.md#run-from-a-repository-checkout).
For an update, use the [reviewed maintenance route](AGENT-HOME.md#explicit-agent-core-source-update);
personal-template changes can require separate review. Do not overwrite your home
with a new checkout. Keep your original files before any removal: this release
does not yet provide a qualified complete backup, restore or uninstall journey.
