"""Advanced opt-in factory handoff from an explicitly selected owned service.

Artifacts and the running pre-home service must already exist and be reviewed.
This module chooses no model, downloads no weights and grants no GPU or task
capability. Failed or interrupted operations retain evidence and never replay.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from . import bootstrap, home as factory, home_entry, model_service, model_service_handoff


SCHEMA = "local-model-service-setup/v1"


class SetupError(ValueError):
    pass


def require(value, message):
    if not value:
        raise SetupError(message)


@contextlib.contextmanager
def _operation(root):
    import fcntl
    state = model_service._within(root, "state/model-service")
    require(state.is_dir(), "The explicit owned service must already be provisioned")
    path = state / "setup.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info, named = os.fstat(descriptor), path.stat(follow_symlinks=False)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino), "Setup lock ownership differs")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SetupError("Another factory operation owns this selected home") from error
        receipt = state / "setup.json"
        require(not receipt.exists() and not receipt.is_symlink(), "Prior setup evidence exists; inspect it before explicit recovery, never replay")
        yield receipt
    finally:
        os.close(descriptor)


def _stop_and_hold(home, root, captured):
    """Compare the exact lifetime under the existing mutation lock, then stop.

    Retain the existing service EX lock until the installed home guard is ready.
    Public service.start respects this lock even though it ignores setup.lock.
    """
    import fcntl
    with model_service._mutation(root):
        require(not home.exists(), "Target home appeared before the exact pre-home stop")
        raw, _ = model_service_handoff._private_read(root / "state/model-service/service.json", 1024 ** 2)
        state = json.loads(raw)
        observed = captured["receipt"]
        require(hashlib.sha256(raw).hexdigest() == observed["service_state_sha256"]
                and state.get("pid") == observed["service_pid"] and state.get("start_ticks") == observed["service_start_ticks"]
                and state.get("nonce_sha256") == observed["nonce_sha256"],
                "Owned service lifetime changed after selection; no process was stopped")
        stopped = model_service._stop(root, state)
        require(stopped.get("status") == "stopped", "The selected pre-home service did not stop")
        lock = root / "state/model-service/service.lock"
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info, named = os.fstat(descriptor), lock.stat(follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                    and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino), "Service admission lock differs")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise


def _preflight(home, selection, *, source, profile):
    require(sys.platform == "linux", "Owned full-agent setup currently requires Linux")
    require(home.is_absolute() and home.resolve(strict=False) == home, "Select the actual absolute future home")
    require(not home.exists() and not home.is_symlink(), "Target already exists; preserve it and use its existing recovery path")
    require(isinstance(selection, dict) and isinstance(selection.get("binding"), dict) and isinstance(selection.get("provider"), dict),
            "Supply the explicit reviewed nonsecret binding and native provider selection")
    binding = selection["binding"]
    route = model_service_handoff._binding(binding)
    # This check intentionally precedes stop, journal creation and scaffold.
    provider = factory.owned_service_provider(home, binding, profile=profile, base_url=route["base_url"], model=route["model_id"],
                                               context_window=route["context"], max_output=route["max_output"],
                                               model_profile=route["transport_profile"], provider=selection["provider"], source=source)
    require(source.is_dir(), "Select the complete installer checkout")
    require(not home.is_relative_to(source) and not source.is_relative_to(home), "Agent home and installer source must be separate trees")
    factory.source_files(source)
    required = [source / "harness/templates/agent-home" / name for name in factory.REQUIRED_TEMPLATES]
    required.extend(source / "harness" / name for name in ("home_entry.py", "home_lifecycle.py", "model_service_handoff.py", "model_service_setup.py"))
    require(all(path.is_file() for path in required), "The selected source lacks required factory templates or owned-service helpers")
    root = model_service._home(home)
    require(root == Path(str(home) + "-runtimes"), "Fresh owned setup requires its permanent bootstrap runtime sibling")
    provision, _, _ = model_service._load(root, verify=False)
    require(provision["specification"]["runtime"]["backend"] == "cpu", "GPU setup remains held pending a qualified resource owner")
    captured = model_service_handoff.capture(home)
    require(captured["receipt"].get("lease_scope") == "pre_home", "Fresh factory setup requires an explicit pre-home serving selection")
    require(captured["binding"] == binding and captured["provider"] == provider, "Reviewed inputs differ from the current owned service selection")
    return root, captured


def create(home, *, selection, source=factory.ROOT, profile="agent", name="Owner", python312=None, managed_node=None):
    """Stop selected pre-home service, use the existing factory, then reattach.

    An interrupted/failed operation is not retried by this entrypoint. Existing
    partial-home doctor/resume-install and explicit service recovery remain the
    owner routes; this function neither rolls back nor guesses their result.
    """
    home, source = Path(home).expanduser(), Path(source).expanduser().resolve(strict=True)
    root, captured = _preflight(home, selection, source=source, profile=profile)
    binding, provider = captured["binding"], captured["provider"]
    with _operation(root) as receipt:
        operation = {"schema": SCHEMA, "home": str(home), "source": str(source), "phase": "validated",
                     "owned_model_service": binding, "provider": provider, "pre_home": captured["receipt"],
                     "automatic_replay": False, "authority": "none", "model_capability_acceptance": "not_probed"}
        admission = None
        def phase(value):
            operation["phase"] = value
            bootstrap.publish_json(receipt, operation)
        try:
            phase("stopping_pre_home")
            admission = _stop_and_hold(home, root, captured)
            phase("pre_home_stopped")
            config = factory.scaffold(home, source=source, profile=profile, name=name, offline=False,
                                      base_url=binding["base_url"], model=binding["model_id"],
                                      context_window=binding["context"], max_output=binding["max_output"],
                                      model_profile=binding["transport_profile"], managed_node=managed_node,
                                      owned_model_service=binding, local_provider=provider)
            phase("installing_packages")
            factory.install_packages(home, config, python312=python312)
            report = factory.doctor(home)
            require(not report["failures"], "Installed home doctor failed; inspect retained setup evidence")
            _, current = home_entry.selected_home(home)
            guard = home_entry._load_guard(home, current.get("lifecycle_guard_sha256"))
            guard.checked_home(home, expected_sha256=current["lifecycle_guard_sha256"])
            require(guard.pending(home) is None, "Pending activation blocks the owned service restart")
            operation["doctor"] = report
            phase("home_guard_ready")
            # A new managed start can now hold this actual home's SH lease.
            os.close(admission)
            admission = None
            phase("starting_after_home")
            model_service.start(home, **model_service_handoff.restart_options(binding))
            attached = model_service_handoff.capture(home)
            require(attached["binding"] == binding and attached["provider"] == provider
                    and attached["receipt"].get("lease_scope") == "home_shared",
                    "Restarted service differs from the selected port/source or lacks its child home lease")
            operation["installed_service"] = attached["receipt"]
            phase("complete")
            return {"schema": SCHEMA, "status": "installed_owned_service", "home": str(home), "setup_receipt": str(receipt),
                    "owned_model_service": binding, "authority": "none", "model_capability_acceptance": "not_probed",
                    "pending_acceptance": report.get("pending_acceptance", [])}
        except BaseException as error:
            operation.update(failed_stage=operation["phase"], phase="failed", error=type(error).__name__ + ": " + str(error),
                             home_exists=home.exists(), recovery="Inspect this receipt and native service state. Use existing doctor/resume-install for a partial home; explicitly review the same-port guarded restart. No automatic replay.")
            bootstrap.publish_json(receipt, operation)
            raise SetupError("Owned setup failed during " + operation["failed_stage"] + "; retained receipt: " + str(receipt)) from error
        finally:
            if admission is not None:
                os.close(admission)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True, help="Reviewed nonsecret capture JSON; not a model recommendation")
    parser.add_argument("--source", type=Path, default=factory.ROOT)
    parser.add_argument("--profile", choices=("agent", "pi", "full"), default="agent")
    parser.add_argument("--name", default="Owner")
    parser.add_argument("--python312")
    parser.add_argument("--managed-node", type=Path)
    args = parser.parse_args(argv)
    try:
        selection = model_service._read(args.selection.expanduser().resolve(strict=True))
        result = create(args.home, selection=selection, source=args.source, profile=args.profile, name=args.name,
                        python312=args.python312, managed_node=args.managed_node)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"schema": SCHEMA, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
