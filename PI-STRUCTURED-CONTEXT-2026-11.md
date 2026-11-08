# Pi structured context: portable source and release boundary

**Candidate date:** 8 November 2026
**Public parent:** `f0d22fc28d2efb9e9e4ce47239ac946287c239a1`
**Scope:** Pi 1.4 structured prompt integration; no installed rig rollout.

## Why this matters

The previous public extensions could append the same policy by returning the
entire rendered system prompt on every `before_agent_start` invocation.
That forces a replacement system prompt, preventing Pi from using a small,
source-addressable delta for the unchanged sections. Large repeated system
text can consume context/prompt-cache budget even when the task has not changed.

Pi's native `event.systemPromptOptions.sections` makes four stable,
identifiable contributions independently maintainable:

| Native section | Owning public component | Trigger to change |
| --- | --- | --- |
| `pi_project_context_policy` | `adapters/pi/context/project-context.ts` | Admission or leaving a project |
| `pi_request_intake_policy` | `adapters/pi/intake/request-intake-138.ts` | An actual policy/source revision, not each request |
| `pi_codex_plan_consult` | `adapters/pi/project-workflow/codex-plan-consult.ts` | Optional consultation instruction revision |
| `pi_kanban_selection` | `adapters/pi/project-workflow/pi-kanban.ts` | Current project/card change or invalidated selection |

Named sections are **model-facing routing context only**. They cannot grant
execution rights, satisfy project instruction delivery, record completion or
alter independent verifier ownership.

Existing safeguards must remain in place: project identity is bound to exact
file bytes; native instruction reads require complete, context-observed content;
Kanban cards and request intake preserve original source/authorisation; mid-turn
intake guidance remains in the existing `context` event. A prompt-section
change is not a workaround for an owner/OS permission failure.

For old standalone fixtures without `systemPromptOptions.sections`, the
project-context, intake and optional Codex policies preserve an idempotent
prompt-only fallback. New selected-card hints are emitted only on the native
structured path, so old consumers do not acquire an extra forced prompt.

## Validation and hard limits

On the development host, run:

    python -m unittest discover -s tests -p test_pi_conversation.py -v
    python -m unittest discover -s tests -p test_pi_project_workflow.py -v
    python -m unittest discover -s tests -p test_pi_codex_sections.py -v
    python -m unittest discover -s tests -p test_pi_bounded_compaction.py -v

The existing actual Pi 1.4 native project-context fixture is:

    node tests/test_pi_project_context.mjs \
      --pi-package /actual/pinned/pi-coding-agent \
      --context /checkout/adapters/pi/context \
      --fixture-parent /existing/disposable/directory

This test uses an isolated project, native Pi extension loader and actual
read/grep tool-call routes. It checks source delivery, redelivery after the
`session_compact` hook, project exit/re-entry, source changes, path and hash
refusals, and stable named section behavior. It does **not** start a real model,
force a compaction summary of a long live session, modify an active Pi process,
or establish independent whole-project acceptance.

A separate large, disposable session with real native compaction is required
before claiming **lossless model context** across full compaction. In
particular, tests of hook reset and small Q4 shadow turns are not the same as
native large-session summarisation. Provider caching and tool correctness also
require measured backend-level acceptance. The existing private four-source
candidate and its test receipts are deliberately not uploaded verbatim.

## Follow-up gates

- Verify actual Pi 1.4 native loader and prompt diff on the published branch.
- Compare exact source hashes and output under repeated unchanged turns and a
  changed selected card. Never assume token savings from a synthetic fixture.
- Exercise a realistically large *disposable* session through automatic/manual
  compaction, preserved original JSONL, source re-delivery and failed tool
  recovery. No live private session may be used as a disposable fixture.
- Retain separate host/OS-scoped authority: the private session-wide
  `ledgerRan` weakness needs a host-bound negative-tested fix. These prompt
  changes do not fix that gate.
- Do not publish private paths, raw conversations, machine credentials,
  model weights, session backups or user-authored personal context.

See [the public Pi context guide](adapters/pi/context/README.md) and
[the SSOT boundaries](BLESSED-SSOT.md) for existing independent controls.
