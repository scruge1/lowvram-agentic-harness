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

This entry is single-machine loopback only and serves reads from one explicitly
admitted project. It needs no private monitoring server, account or new token
scheme. It is not an OS sandbox or remote authentication solution. Remote
exposure, effect controls and existing-home asset/controller adoption require
their own reviewed paths.

## Current component route

The installed stable entry exposes `board --project PATH`. Its current advanced
asset flags are `--assets PATH --asset-manifest-sha256 SHA256`. It prints the
loopback URL while the foreground view is running. Open that URL on the same
machine. Stop the foreground command to close the view and release its lease.

Build the local assets from a fresh copy of the exact upstream commit with its
unchanged workspace lock. Install only its web dependency closure with
`npm ci --workspace web --include-workspace-root=false --ignore-scripts
--no-audit --no-fund`. Then run `scripts/build_project_board_assets.py` with
`--upstream PATH --node PATH --output NEW_PATH`. The builder requires the reviewed
managed Node version and verifies the upstream inputs. Supply the resulting
manifest's SHA-256 to the board command. The view checks every asset against it,
including each file immediately before delivery.

An isolated Linux component fixture exercised the normal stable entry, local
assets and actual native UI. It checked cards, comments, result summaries,
search, desktop/mobile layout, disabled effects and foreign-project refusal.
Closing the owner stopped the listener and allowed an exclusive home lease.
The selected board and knowledge database bytes remained unchanged. The fixture
borrowed one verified public Hermes package environment; it did not establish
complete installation of the selected profile or existing-home adoption.

Automatic installer-owned asset build and admission remain open. A normal fresh
install followed by the board command must qualify that path before this is a
one-install feature. Existing controller or dependency holds must remain visible;
do not hand-copy a new runtime or asset record into an older home.
