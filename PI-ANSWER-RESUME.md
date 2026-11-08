# Answer-first continuation for previously approved Pi tasks

**Status:** isolated native Pi 1.4 source port; full release and installed-host
acceptance are separate. This is not a new autonomous dispatcher, a background
monitor or permission to resume arbitrary historical tasks.

## Intended outcome

An assistant performing a long, explicitly approved project task should be
able to answer an ordinary follow-up question without losing its task identity.
The answer itself must not supply new authorization, conceal an unresolved
child or dependency, or automatically select a different retained card.

The new `answer-resume/v3` state is built on the **existing Pi intake journal**
and the public source-bound retained-work decision helper:

1. **Prior source:** an already admitted project and an original owner-approved,
   retained execution scope are recorded in native Pi state. A new user
   question optionally gets a bounded `prior_scope` snapshot containing
   exact tasks, their original source IDs, project identity and scope hash.
   This capture never grants the question execution rights.
2. **Question-only classification:** only a pure `question` part with
   `control=preserve`, no cancellation, no new task and no effectful
   amendments may retain an exact answer-and-return marker. A mixed,
   unclassified, historical, superseded or cross-project source does not.
   A question can still be answered **without routing**; that simply does
   not automatically resume the previous objective.
3. **Answer boundary:** while the question is active, substantive tool calls
   are refused. Once the completed model turn settles, Pi can mark an
   already-routed, exact-bound question as answered. The routing operation
   alone cannot remove the hold.
4. **Return:** the existing source-bound decision engine is projected over
   the exact pre-question scope, not every older task in the queue. Native
   task admission still checks project identity, source containment,
   prerequisites, cancellation, holds and card readiness. A model-generated
   continuation message is a next-step request, **not** a verifier receipt
   or permission grant.
5. **Recovery:** the original captured source, native route intent,
   `question_return` state and independent effect evidence survive a
   normal Pi session tree/reload. An incomplete route is not fabricated
   into successful approval or replayed as a new effect.

## Refusal conditions

A question must not resume work when any of the following holds:
unclassified/mixed intent, changed source hash or project/board identity,
new user source, pending or typed user input, unresolved in-memory child,
explicit pause, unverified dependency, failed tool result, cancelled scope,
retired no-progress hold, cross-project selection, or missing source-bound
project/task evidence.

Existing public protections remain authoritative: the host/OS effect gate,
project instruction source verification, bounded model-facing output,
managed-child native journal, task dependency receipts, and independent
output acceptance. An input from a peer/RPC transport is not automatically
human approval; this mechanism only references a scope that was approved
previously.

## Representative tests

```bash
python -m unittest discover -s tests -p test_pi_conversation.py -v
python -m unittest discover -s tests -p test_pi_project_workflow.py -v
python -m unittest discover -s tests -p test_pi_managed_child.py -v
```

The full-extension fixture verifies that an approved task survives ordinary
questions without duplicate board cards or artificial progress. A direct
answer can resume without polling a status tool; an explicit session-tree
restore retains its pending answer marker. Negative controls check mixed
or unclassified conversation, pause, resource/peer wait, changed project
identity, failed tool, unsettled child, newer input, editor draft and source
tampering. Existing routing uncertainty, source migration and child
recovery tests must continue to pass.

The native Pi loader and complete Linux/Windows offline CI must pass the
**exact published branch** before this is promoted. These fixtures do not
prove a particular model's quality of answer, a real long-context
summarization, unattended task completion, or permission to change the live
private rig. No private prompt/session bodies, model weights, host secrets or
historical source hashes belong in the public repository.
