# Pi request intake and retained work

This is the portable export of intake generation138 and read-loop guard079.
It uses the existing Pi journal and project Hermes board. It does not add a
dispatcher, model request, task database or mandatory planning adviser.

The project coordinator imports `registerRequestIntake` from
`request-intake-138.ts`. Its bindings supply the admitted project, selected
card, selection setter, admission-failure state and existing board caller.
Keep the whole directory together; the digest module is shared by projection,
decision binding and read-loop observation.

Install `agent-framework-core==1.21.0` in a dedicated Python environment. After
placing these files in their final directory, use that environment's Python:

```text
python -B /absolute/intake/framework_binding.py --output /absolute/home/framework-binding.json
```

The destination must be absent. The generator checks core Python source bytes
against the installed wheel RECORD. It then records the actual interpreter,
colocated helper and installed core source hashes. Its JSON response supplies
the binding file SHA256. Set `PI_FRAMEWORK_BINDING` to that absolute filename
and `PI_FRAMEWORK_BINDING_SHA256` to the response hash in the Pi launch
environment. Missing bindings and source drift fail closed. This is installed
source identity, not native adoption or task acceptance.

Intake retains exact source and frozen routing intent. It keeps pause,
cancellation, unresolved failure, task dependency and pending-input gates.
Historical reconciliation cannot grant new execution authority. A complete
retained queue does not establish acceptance of the user's root outcome.

Receipt-backed waits currently require Linux account ownership, no-follow file
opening and opened-descriptor containment checks. Other platforms refuse this
feature before registration or watching. Receipt identity and terminal state
must match the registered job. A matching receipt can deliver one follow-up;
it does not grant permission or accept project quality. Manual resolution and
session waits retain their separate contracts.

The decision helper currently validates POSIX absolute project roots. Qualify
other platform paths and equivalent receipt ownership checks before claiming
support. Also verify actual Pi tool registration, source routing, reload,
pause, failure, cancellation, receipt wakeup and no-replay behavior on the new
host. Offline package tests do not establish these native results.
