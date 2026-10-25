---
name: supervised-tasks
description: Use for declared file changes through the installed workflow_step host supervisor.
---

Admit the intended project with project_admit first. Admission resets capability,
tool, memory and knowledge observations, even when the project is unchanged.
Then call agent_capabilities and system_tool_query for the task. Query relevant
local memory and project knowledge, read current project_context, and select an
authorized ready card. Complete any remaining context reads. After compaction,
refresh project_context before execution. Do not repeat project_admit merely to
inspect the same board.

Read this installed SKILL.md in full through the native read tool before
workflow_step. A skill summary or this reference alone does not satisfy the
host's skill check. Supply a short objective, exact cwd, action argv, verifier
argv and relative output paths. Shell text is not an argv array.

The verifier reads outputs relative to cwd and returns 1 for absent/invalid
outputs. The host runs the same verifier in an empty negative-control directory
before the positive check. Use an absolute verifier script path. A literal echo
or a verifier that ignores the output does not establish task correctness.

For the prepared first hardware report, read
[first-hardware-report.md](references/first-hardware-report.md). Reuse its fixed
checker and the original preparation hash. It checks facts, units, length and
unchanged inputs; keep interpretation under separate semantic review.

No automatic replay follows failure. Read the complete saved failure and state
the changed assumption, new evidence, expected observation and stop condition.
The Linux process owner cleans up owned descendants; it is not an OS sandbox.
Physical actions, credentials and privileged effects retain separate authority.
