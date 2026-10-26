# First hardware report

Use this reference for the prepared first-project hardware report. The host
preparer uses the existing agent-home project command's Git, board and context
admission. It measures inventory through the existing onboarding/probe and reads
configured model metadata. It makes no model request or service change.

Read `FIRST-PROJECT.md` and `hardware-facts.json`. Preserve the prepared
`first-project.json` and the original manifest hash returned by prepare. Do not
alter the checker or its inputs to satisfy the report.

Before drafting, read the complete installed `supervised-tasks/SKILL.md` with
native `read`. Use `project_admit` first, then `agent_capabilities`,
`system_tool_query`, relevant local memory and `project_knowledge_query`.
Read `project_context` for the report directory and finish its `remaining_reads`.
Select an authorized ready card. After compaction, refresh `project_context`;
do not restart project admission and erase the observations already collected.
Tool discovery does not replace the actual query or skill read.

Write a useful 250-400 word `hardware-report.md`; aim near300 words so the
action and complete report fit in one response. Copy the five exact fact labels and explicit
units into a three-column Markdown table. Write `unknown` for unavailable
observations. Cite `hardware-facts.json` and explain the limits in ordinary text.

Use the fixed action argv template in the prepared `FIRST-PROJECT.md` and the
existing `.icm/workspace/PROJECT-SSOT.md`. Replace only its final string with
your complete report text. Its installed Python `-I -B -c` program writes that
separate argv value as UTF-8 to only `hardware-report.md`, with exclusive create
mode. Existing files and symlinks refuse; preserve them for inspection rather
than deleting or replaying. Do not invent an assumed body file. Declare only
`hardware-report.md` as output and keep prepare's original verifier separate.
`first_project.py run` launches the agent and prepares a project; it is not the
report-writing action and must not be nested inside `workflow_step.action`.

Use prepare's exact `check_argv` as `workflow_step.verify`. The fixed checker
always reads relative to cwd and returns 1 for missing or invalid files, so the
normal supervisor can run its empty-directory negative control. The expected
manifest SHA belongs in the verifier argv; recomputing it from modified inputs
does not preserve the original task. The checker also enforces the actual word
count. Do not substitute a model's claimed word count.

A passed checker proves the pinned input hashes, fact rows, explicit units,
source citation and word bound. It still reports semantic review required.
Inspect the actual report for unsupported customer comparisons, model-fit
claims, and ambiguous descriptions of actions. Inventory observation is read
only; writing the report changes a file. Configured caps do not prove serving
limits, local inference, hardware fit or tool capability. The probe's first GPU
is not a selected inference device.

Do not claim that a later task never ran a tuner from an English sentence in
the report. This checker does not observe tool execution. Such a claim requires
the actual retained run trace and its stated coverage. Preserve unknowns when
that evidence is absent. Do not launch tuning, change servers or GPUs, download
models, use cloud fallback or commit as part of this report task.

Inspect a failed run before an evidence-bound correction; do not replay effects
automatically. Preserve the output and normal workflow receipt. A useful real
report, independent readback, reopening the project and harmless recovery remain
separate acceptance steps. A green predicate or Done card is not the full user
outcome.
