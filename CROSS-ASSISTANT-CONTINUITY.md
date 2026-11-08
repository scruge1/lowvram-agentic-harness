# Continue a project across Gemini, Codex, Claude, Pi, and local models

**Status:** portable, human-reviewed handoff procedure. This document is not a
validated automatic importer, a live model migration, or a replacement for the
repository's independent acceptance checks.

The objective is **continuity independent of the assistant**. Preserve the
actual code, decisions, constraints, provenance, remaining tasks, and verifiable
results so that a new worker can continue without trusting a previous model's
claims. Historical chat transcripts are useful evidence, but **not** the
source of authority.

## 1. Preserve what already exists

Do this before uninstalling Gemini, changing machines, deleting chats, cleaning
the workspace, or allowing a new agent to rewrite project files.

- **Gemini CLI:** recent releases automatically record project-scoped sessions
  under ~/.gemini/tmp/<project_hash>/chats/. From the same project directory,
  use `gemini --list-sessions` and `gemini --resume`. In a session,
  `/resume` browses old conversations and
  `/resume share handoff.json` exports the selected conversation.
  Check the installed version's command help before relying on exact syntax.
  The documented default retention is **30 days**, with configurable cleanup.
- **Gemini Code Assist:** VS Code offers **Resume Previous Chat** and IntelliJ
  offers **Recent Chats** / query history. Local extension state and retention
  are product/version-specific; do not assume the Gemini CLI folder applies.
- **Gemini Apps / web:** Google Takeout can export Gemini Apps activity, chats,
  and other supported data. **Do not assume** the Apps export contains CLI
  session files, IDE chat histories, repository files, or arbitrary tool logs.
- **Git and project files:** record the exact current commit, branch, remotes,
  uncommitted changes, submodules, and any build/runtime configuration that
  matters. The actual repository often resolves contradictions in chat history.
- **Private artifacts:** retain a separate, access-controlled copy of session
  exports, command logs, screenshots, credentials inventories, and customer
  documents. Do not commit this archive to a public Git repository.

Useful read-only Git inventory from the actual project directory:

    git rev-parse HEAD
    git branch --show-current
    git status --short
    git remote -v

Review the output before sharing: remotes may contain internal hostnames or
credential-bearing URLs. Do **not** run a mass export directly into this repo.

Official references:
- https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/session-management.md
- https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/commands.md
- https://docs.cloud.google.com/gemini/docs/codeassist/use-gemini-code-assist-chat
- https://support.google.com/gemini/answer/16920332
- https://takeout.google.com/

## 2. Build a reviewed continuation packet

Start from [examples/continuity/handoff.template.json](examples/continuity/handoff.template.json).
It is **a template, not executable SSOT state**. Keep raw transcripts outside the
repository and refer to them via private inventory IDs, checksums, or redacted
source references. Do not put absolute personal paths, private session names, or
tokens into a public handoff.

Record at least:

1. **Repository snapshot:** exact commit and branch, dirty-worktree status,
   deployment target, build/run commands, environment assumptions.
2. **Source of truth:** reviewed PRD, requirements, AGENTS.md instructions,
   architecture diagrams, stable interfaces, and exact file digests.
3. **Decision log:** accepted/declined/superseded choices and why, with source
   references. A model summary cannot make an old suggestion accepted.
4. **Execution state:** what ran, the precise commands, passing and failing
   checks, known regressions, and last independently accepted artifact.
5. **Work frontier:** what remains, prerequisites, resource/authority limits,
   completion criteria, and an explicit first task for the next assistant.
6. **Unknowns and conflicts:** missing chats, ambiguous requirements, expired
   evidence, and any mismatch between a transcript and the checked-out code.

Each factual entry needs a provenance label: checked repository bytes, observed
runtime receipt, reviewed decision, or unverified transcript suggestion.
**Unresolved information must remain unresolved.** New assistants must not
silently turn a suggestion into project policy.

## 3. Reconcile history with the actual system

Read the candidate handoff alongside the repository and build records. Audit
architectural differences, test expectations, configuration drift, dead
approaches, and modified files. Validate important facts against source code,
versioned documents and fresh command output.

Keep assistant-specific instructions (Gemini prompts, Claude project files,
Codex rules, Pi settings) as *adapters*. Put accepted project requirements,
domain concepts, acceptance tests, and architectural decisions in shared
project-owned files. An agent's chat history or private memory store must never
be the only copy of a critical decision.

For a stronger host-controlled contract, follow
[BLESSED-SSOT.md](BLESSED-SSOT.md) and [TRUSTED-PROJECT.md](TRUSTED-PROJECT.md).
The portable controller can derive a dependency frontier and test declared
outputs, but cannot infer an arbitrary PRD's meaning. An unresolved source
inventory deliberately blocks execution. Local authority stops at **tested**,
not externally **blessed**.

## 4. Qualify the new assistant before switching the main workflow

- First assignment: **read-only project audit**. Ask the incoming assistant to
  reconstruct module boundaries, current work, test commands and unresolved
  decisions. Compare its report to real files and receipts.
- Next assignment: one small but representative change on an isolated branch or
  worktree. Require the project's real checks, independent acceptance, and a
  clear rollback path. Do not assess success from confident prose.
- Then scale to long tasks. Preserve incremental results and error feedback
  across compaction and session resets, and use evidence-backed recovery.
- Compare assistants on verified completed work, regression rate, context
  reconstruction, tool reliability, resource cost and recovery—not only coding
  benchmark scores or the amount of context each claims to support.
- A provider/model change should not require rewriting the project's canonical
  state. Keep the execution harness and inference backend independently
  replaceable.

There is **no universal turn, token or time cap** imposed by this procedure.
Resource budgets must still match real model context, KV-cache memory,
verification requirements and task deadlines. Large configured context windows
do not prove long-context retrieval quality.

## 5. Release and privacy boundaries

The handoff template and this guide do not automatically import conversations,
change a live Pi session, install an extension, publish historical records,
select a model, or prove that a third-party assistant can resume a private run.
Each of those requires its own approved adapter and target-specific tests.

Before sharing a handoff publicly, remove secrets, session bodies, customer
information, personal paths, SSH targets, tokens, emails, and unlicensed
third-party content. A Git commit history can retain a leaked secret even after
the visible file is deleted.

**Successful transition:** a fresh assistant can use the reviewed packet and
repository to explain the project's exact accepted state, execute a bounded
next stage, pass the existing independent checks, and resume later without
depending on the former assistant's memory.
