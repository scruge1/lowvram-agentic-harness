# Local project read view

This source candidate reuses the pinned Hermes Kanban component and its real
React/design-system primitives. The backend uses Python's standard library and
the existing project JSON adapter. It does not start Hermes chat, model serving,
dispatch, a private server or a second project registry.

## Design and acceptance

Visual direction: keep the native board and detail surfaces, with a quiet header
that names the selected project and clearly says **Read only**. Use the native
type and component styles; avoid extra panels, decorative imagery or a second
navigation system. The board is the primary workspace.

Content: project identity and view limit, native columns/cards, then the native
task detail and existing result text. Task status is not checked-output authority.
The header's reload action is real. Creation, dispatch, movement and editing must
be disabled and refused by the backend. Do not label unsupported controls as
working. No animation is required; retain native reduced-motion behavior.

Check a full desktop composition and a narrow mobile composition in the actual
browser. Inspect card readability, native detail navigation, focus, disabled
controls, overflow and the selected project's identity. Functional backend checks
do not establish visual acceptance. The owner design review informs hierarchy
and control clarity; this is an app workspace rather than a promotional page.

## Source and runtime boundaries

The native package supplies the Kanban IIFE/CSS and published UI primitives.
Its host React/SDK closure was not installed by the earlier Python-only package
route. A fresh owned build must use the pinned upstream source/workspace lock
and managed Node. No CDN, personal bundle or hand-written replacement board.
Retain build provenance, dependency licences and artifact hashes. Never hide
new imports or bypass an update hold.

The builder requires the actual pinned Git checkout root, clean staged and
working source, and no untracked source. It checks again after the temporary
host is removed. Only explicit root/web `node_modules` and pip metadata paths
are excluded from the untracked check. The manifest records the observed commit,
tree and upstream licence hash. Git covers transitive workspace source; the
installed npm dependency generation still needs its separate locked-install
qualification. An extracted source archive alone is not a Git checkout.

This entry is single-machine loopback only and serves reads from one explicitly
admitted project. It needs no private monitoring server, account or new token
scheme. It is not an OS sandbox or remote authentication solution. Remote
exposure, effect controls and existing-home asset/controller adoption require
their own reviewed paths.

## Open an installed board

After a new home's installation completes, run:

```bash
python /data/my-agent/agent-home.py board --project /data/my-agent/projects/example
```

Open the printed loopback URL on the same machine. The command stays in the
foreground. Stop it to close the view and release its home lease. The project
must already exist; this command does not create a project or board.

The source installer builds the local assets during the new Hermes package's
exclusive phase, before recording its package fingerprint. Its existing package
record owns the asset manifest and hashes. The board command resolves that
record, so normal use needs no asset path or manually supplied hash. Doctor
reports missing or changed UI files. Earlier installed Hermes records do not
acquire a UI record automatically; they require reviewed maintenance.

The native web dependency closure uses the pinned workspace lock and
[npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/), with lifecycle scripts,
audit and funding output disabled. The build checks clean Git source before and
after compilation, retains licences, and records its own host inputs and runtime.
A completed matching build can finish a package-record save after interruption.
Unknown or incomplete output is retained and refused before package effects.

For reviewed development fixtures, `--assets PATH --asset-manifest-sha256 SHA256`
remains an explicit override. `scripts/build_project_board_assets.py` accepts
`--upstream PATH --node PATH --output NEW_PATH`; it does not install dependencies
or replace an existing output. The view checks every recorded asset before
serving it, including the file immediately before delivery.

## Qualification limits

An isolated Linux component fixture exercised the normal stable entry, explicit
local assets and actual native UI. It checked cards, comments, result summaries,
search, desktop/mobile layout, disabled effects and foreign-project refusal.
Closing the owner stopped the listener and allowed an exclusive home lease.
The selected board and knowledge database bytes remained unchanged. The fixture
borrowed one verified public Hermes package environment; it did not establish
complete installation of the selected profile or existing-home adoption.

Automatic installer-owned build and record resolution are implemented in this
source. Actual normal fresh installation followed by the board command remains
unqualified. That proof is required before calling this a one-install feature.
Existing controller and dependency holds remain visible; do not hand-copy a new
runtime or asset record into an older home. Read-only status and saved summaries
do not establish checked-file opening, full native UI controls or task quality.
