# Host Adapter Templates

These templates connect native harness lifecycle events to
`harness.enforcement`. Install the Python package first with `pip install -e .`.

- Claude Code: merge `claude-code/settings.example.json` into the project or user
  settings file.
- Hermes: merge `hermes/config.example.yaml` into `~/.hermes/config.yaml` and run
  `hermes hooks doctor` plus synthetic hook tests.
- Pi: copy `pi/enforcement.ts` to `.pi/extensions/enforcement.ts` in a trusted
  project or install it as a Pi package.

The supervisor supplies the required environment only while it is running a task.
Outside that process, the hook command fails closed with an explicit configuration
error instead of inventing task state.

The Python protocol and generated templates have offline tests. They are not marked
live-host verified until each adapter passes its host's real lifecycle tests.
