---
name: supervised-tasks
description: Use for declared file changes through the installed workflow_step host supervisor.
---

Read the current project checkpoint and call agent_capabilities. Admit the
project, inspect relevant tools, memory and project knowledge, and select a
ready card. Supply a short objective, exact cwd, action argv, verifier argv and
relative output paths to workflow_step. Shell text is not an argv array.

The verifier reads outputs relative to cwd and returns 1 for absent/invalid
outputs. The host runs the same verifier in an empty negative-control directory
before the positive check. Use an absolute verifier script path. A literal echo
or a verifier that ignores the output does not establish task correctness.

No automatic replay follows failure. Read the complete saved failure and state
the changed assumption, new evidence, expected observation and stop condition.
The Linux process owner cleans up owned descendants; it is not an OS sandbox.
Physical actions, credentials and privileged effects retain separate authority.
