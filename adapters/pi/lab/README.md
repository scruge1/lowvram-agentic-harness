# Optional component lab

The Linux `full` profile registers `harness_lab`. The default `agent` profile
does not load this extension. Run `/harness-lab` for status, or call:

```json
{"action":"status"}
```

```json
{"action":"demo"}
```

Status checks the selected full-profile pins, recorded Harness2/DeepSeek package
artifacts, the owned Harness2 checkout commit and installed Python code against
that clean checkout. DeepSeek is inspected only. Package identity does not prove
agent quality or that a model experiment works.

Demo uses the actual pinned `harness2.cli.demo` module with `--k 1 --mode both`.
Its native `DemoAdapter` and `DemoProposer` run scripted Python and select signed
ledger answers. They do not call a model. The host independently checks both
fixed input ledgers and the chosen answer for each task in both recursion modes.
A native done count or exit code alone is insufficient.

Each call retains stdout, stderr and `result.json` in a new directory under
`HOME/state/harness-lab/runs`. Interrupted or failed directories stay in place;
the tool does not replay them. The existing home lifecycle guard holds the home
lease. The existing Pi process guard owns descendants through a live parent pipe.
Abort closes that pipe and waits for process settlement before returning.
This is process cleanup, not an untrusted-code sandbox. No arbitrary command,
output path, model, credential or endpoint is accepted from the tool caller.

`experiment` returns a held result. No model, GPU, container, queue or service
experiment is configured. This diagnostic grants no project execution authority.

The helper and command are bound by `PI_HARNESS_LAB_PYTHON`,
`PI_HARNESS_LAB_HELPER`, `PI_HARNESS_LAB_HELPER_SHA256`,
`PI_HARNESS_LAB_COMMAND` and `PI_HARNESS_LAB_COMMAND_SHA256`. The factory derives
the command from its existing lifecycle guard. Missing packages, changed pins,
source drift and another profile refuse before native demo dispatch. Child
environments do not copy provider credentials, proxy settings or Python overrides.

Source adoption was checked with actual Pi 1.4 and copied public Harness2
dependencies in an isolated fixture: package status, both-mode selected answers,
held experiments, profile refusal, active abort and parent loss with released
exclusive home lease. These checks made no provider HTTP requests. They do not
qualify a new full installation, model quality or the private experiment suite.

The separately installed [Harness2 source](https://github.com/google-research/harness2/tree/1cfe254e8d25b15f37048c3730134686abe60335)
is Google Research code under Apache-2.0. This bridge invokes its native CLI;
it does not copy or replace that implementation.
