#!/usr/bin/env bash
# Linux x64/glibc bootstrap. Native uv owns Python installation.
set -Eeuo pipefail
umask 077
SOURCE="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
UV_VERSION=0.11.25
UV_SHA=1db18b5e76fa645a7f3865773139bdec8e2d46adbdbb35e7410b34fa8015ccd2
PYTHON_KEY=cpython-3.12.13-linux-x86_64-gnu
UV_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
# Display-only pins for the pre-Python plan. Tests bind these to the canonical
# harness/model-service-pins.json; managed Python owns actual artifact selection.
CPU_MODEL_ID=qwen3vl-8b-instruct-q4-k-m
CPU_MODEL_NAME=Qwen3VL-8B-Instruct-Q4_K_M.gguf
CPU_MODEL_REVISION=f982a07559d4a2f6c8744d840bf6fccab30eea96
CPU_MODEL_SHA=67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2
CPU_MODEL_BYTES=5027784800
CPU_RUNTIME_RELEASE=b11869
CPU_RUNTIME_REVISION=d327bf1f0780f87b8c01b367b61853b0c291d7c4
CPU_RUNTIME_NAME=llama-b11869-bin-ubuntu-x64.tar.gz
CPU_RUNTIME_SHA=529ebb30c8aafcfd7d2ae0606aef346a3f3209d0a49addf382070c0c78fa2a6e
CPU_RUNTIME_BYTES=22438155
home_path= yes=0 plan=0 runtimes_only=0 resume_install=0 local_cpu=0
arguments=()
die() { echo "Bootstrap refused: $*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --home) [[ -z "$home_path" && $# -ge 2 ]] || die 'Supply --home once with its path'; home_path=$2; shift 2 ;;
    --home=*) [[ -z "$home_path" ]] || die 'Supply --home once'; home_path=${1#*=}; shift ;;
    --yes) yes=1; shift ;;
    --plan) plan=1; shift ;;
    --runtimes-only) runtimes_only=1; shift ;;
    --resume-install) resume_install=1; shift ;;
    --local-cpu) local_cpu=1; shift ;;
    --python312|--python312=*|--managed-node|--managed-node=*|--source|--source=*) die 'Bootstrap binds its source, Python and Node; do not override them' ;;
    --help|-h) echo 'Usage: bash install.sh [--home NEW_DIRECTORY] [--plan|--yes] [--local-cpu | --runtimes-only | --resume-install] [agent-home install options]'; exit 0 ;;
    *) arguments+=("$1"); shift ;;
  esac
done
((!runtimes_only || !resume_install)) || die 'Choose runtime-only setup or installer resume, not both'
if ((local_cpu)); then
  ((!runtimes_only && !resume_install)) || die '--local-cpu cannot mix runtime-only or resume modes'
  seen_profile=0 seen_name=0
  for ((i=0; i<${#arguments[@]}; i++)); do
    case "${arguments[i]}" in
      --profile|--profile=*)
        ((!seen_profile)) || die 'Supply --profile once'; seen_profile=1
        if [[ "${arguments[i]}" == --profile ]]; then
          ((i+=1)); ((i<${#arguments[@]})) || die '--profile needs agent or pi'; profile=${arguments[i]}
        else profile=${arguments[i]#*=}; fi
        [[ "$profile" == agent || "$profile" == pi ]] || die '--local-cpu supports only agent or pi' ;;
      --name|--name=*)
        ((!seen_name)) || die 'Supply --name once'; seen_name=1
        if [[ "${arguments[i]}" == --name ]]; then
          ((i+=1)); ((i<${#arguments[@]})) || die '--name needs its value'; owner_name=${arguments[i]}
        else owner_name=${arguments[i]#*=}; fi
        [[ -n "$owner_name" && "$owner_name" != --* && "$owner_name" != *$'\n'* && "$owner_name" != *$'\r'* ]] || die 'Use a nonempty one-line owner name' ;;
      *) die '--local-cpu accepts only --profile agent|pi and --name; omit endpoint/model/budget/offline/resume overrides' ;;
    esac
  done
fi
if [[ -z "$home_path" ]]; then read -r -p 'New agent-home directory: ' home_path; fi
[[ -n "$home_path" && "$home_path" != *$'\n'* && "$home_path" != *$'\r'* ]] || die 'Use one nonempty directory path'
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || die 'Initial bootstrap supports Linux x86_64/glibc only'
for command in git curl tar sha256sum df stat realpath flock getconf install mktemp; do command -v "$command" >/dev/null || die "Install the OS prerequisite $command first"; done
getconf GNU_LIBC_VERSION >/dev/null 2>&1 || die 'A glibc Linux host is required'
[[ -f "$SOURCE/harness/bootstrap.py" && -f "$SOURCE/harness/home.py" ]] || die 'Use the complete repository checkout'
home_path=$(realpath -m -- "$home_path")
[[ "$home_path" != / && "$home_path" != "$(realpath -- "$HOME")" ]] || die 'Choose a new dedicated home'
((!local_cpu)) || [[ ! -e "$home_path" && ! -L "$home_path" ]] || die '--local-cpu requires a new home; inspect existing setup evidence'
runtime_root="${home_path}-runtimes"
[[ ! -L "$runtime_root" && "$runtime_root" == "$(realpath -m -- "$runtime_root")" ]] || die 'Runtime directory must not be redirected'
parent=$(dirname -- "$runtime_root")
[[ -d "$parent" ]] || die 'Create/select an existing install parent first'
available=$(df -B1 --output=avail "$parent" | tail -n 1 | tr -d ' ')
[[ "$available" =~ ^[0-9]+$ && "$available" -ge 8589934592 ]] || die 'At least 8 GiB free is required for runtimes, package downloads and headroom'
((!local_cpu)) || [[ "$available" -ge 21474836480 ]] || die '--local-cpu requires at least 20 GiB free on the selected volume'
if [[ -e "$runtime_root" ]]; then
  [[ -d "$runtime_root" && -f "$runtime_root/bootstrap-owner" && ! -L "$runtime_root/bootstrap-owner" ]] || die 'Existing runtime directory has no bootstrap ownership record; preserve it'
  [[ "$(cat "$runtime_root/bootstrap-owner")" == "agent-home-bootstrap/v1:$home_path" ]] || die 'Runtime directory belongs to another home'
else
  [[ ! -e "$home_path" ]] || die 'The selected home already exists without this runtime binding'
fi
cat <<PLAN
Agent home: $home_path
Permanent owned runtimes: $runtime_root (retain it; virtual environments use its Python)
Physical install parent: $(realpath -- "$parent")
Available bytes: $available
Downloads: uv 0.11.25 archive (maximum 50 MiB), native managed CPython 3.12.13/build20260623
  (reserve 100 MiB download), Node22.23.2 archive (31,058,332 bytes).
Installed runtime/cache budget: 2 GiB; minimum free-space check: 8 GiB.
The existing selected agent profile adds its own package/browser/embedding downloads.
Changes: only the selected new home and its explicitly owned sibling runtime directory.
No GPU/driver, OS packages, global PATH or shell-profile changes.
Failed downloads/stages are retained. Package/browser/embedding total download bytes
are unknown before dependency resolution; leave additional storage headroom.
PLAN
if ((local_cpu)); then
  cat <<CPU_PLAN
OPT-IN LOCAL CPU CANDIDATE: $CPU_MODEL_ID (text only; no vision projector).
Model: $CPU_MODEL_NAME; $CPU_MODEL_BYTES bytes; Apache-2.0.
  Revision: $CPU_MODEL_REVISION
  SHA256: $CPU_MODEL_SHA
  https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/$CPU_MODEL_REVISION/$CPU_MODEL_NAME
Native engine: llama.cpp $CPU_RUNTIME_RELEASE; $CPU_RUNTIME_BYTES bytes; MIT.
  Revision: $CPU_RUNTIME_REVISION
  SHA256: $CPU_RUNTIME_SHA
  https://github.com/ggml-org/llama.cpp/releases/download/$CPU_RUNTIME_RELEASE/$CPU_RUNTIME_NAME
These additional artifacts total 5,050,222,955 bytes before extraction.
Managed Python validates canonical pins and at least 20 GiB available RAM/free disk
and 8 available affinity/logical CPUs before model transfer (no exclusive reservation).
CPU threads8/batch threads8, parallel1, context32768/output4096;
GPU layers0/device none. An authenticated home-owned loopback service is started,
stopped before home creation, then restarted on the same port with its home lease.
The service remains running after successful setup; explicit stop/status are available.
The prior two-thread32K/4K report attempt failed the 600-second task at input
prefill. This eight-thread candidate needs same-workload qualification; it has no
accepted agent task quality, speed, general fit or GPU support. No cloud fallback.
Agent/pi profiles only.
CPU_PLAN
else
  echo 'No model weights/server are downloaded or started. Existing local-model attachment remains required.'
fi
((plan)) && exit 0
if ((!yes)); then read -r -p 'Accept the displayed downloads and owned setup/start actions? [y/N] ' reply; [[ "$reply" == y || "$reply" == Y ]] || exit 0; fi
if [[ ! -e "$runtime_root" ]]; then
  mkdir -- "$runtime_root"
  printf '%s\n' "agent-home-bootstrap/v1:$home_path" > "$runtime_root/bootstrap-owner"
fi
[[ ! -L "$runtime_root/bootstrap.lock" && (! -e "$runtime_root/bootstrap.lock" || -f "$runtime_root/bootstrap.lock") ]] || die 'Bootstrap lock is redirected'
exec 9<>"$runtime_root/bootstrap.lock"
flock -n 9 || die 'Another bootstrap owns this runtime directory'
for name in bin downloads cache tmp python; do
  [[ ! -L "$runtime_root/$name" ]] || die 'Owned runtime subdirectory is redirected'
  mkdir -p -- "$runtime_root/$name"
done
archive="$runtime_root/downloads/uv-$UV_VERSION.tar.gz"
if [[ -e "$archive" ]]; then
  [[ -f "$archive" && ! -L "$archive" && "$(sha256sum "$archive" | cut -d ' ' -f1)" == "$UV_SHA" ]] || die 'Existing uv archive conflicts; original preserved'
else
  partial="$archive.partial"
  [[ ! -L "$partial" && (! -e "$partial" || -f "$partial") ]] || die 'uv partial file is redirected'
  [[ ! -e "$partial" || $(stat -c %s "$partial") -le 52428800 ]] || die 'Oversized uv partial preserved'
  if [[ ! -e "$partial" || "$(sha256sum "$partial" | cut -d ' ' -f1)" != "$UV_SHA" ]]; then
    env -i HOME="$HOME" PATH=/usr/bin:/bin TMPDIR="$runtime_root/tmp" \
      curl -q --fail --silent --show-error --location --continue-at - --connect-timeout 20 --max-time 600 \
      --max-filesize 52428800 --proto '=https' --proto-redir '=https' --noproxy '*' --output "$partial" "$UV_URL"
  fi
  [[ "$(sha256sum "$partial" | cut -d ' ' -f1)" == "$UV_SHA" ]] || die 'uv archive hash differs; failed partial retained'
  [[ ! -e "$archive" ]] || die 'uv final appeared concurrently; partial retained'
  mv -n -- "$partial" "$archive"
fi
if [[ ! -e "$runtime_root/bin/uv" ]]; then
  stage=$(mktemp -d "$runtime_root/uv-stage.XXXXXX")
  tar -xzf "$archive" --no-same-owner -C "$stage" uv-x86_64-unknown-linux-gnu/uv
  [[ -f "$stage/uv-x86_64-unknown-linux-gnu/uv" && ! -L "$stage/uv-x86_64-unknown-linux-gnu/uv" ]] || die 'Invalid native uv archive entry'
  install -m 700 "$stage/uv-x86_64-unknown-linux-gnu/uv" "$runtime_root/bin/uv"
  sha256sum "$runtime_root/bin/uv" > "$runtime_root/uv.sha256"
else
  [[ ! -L "$runtime_root/bin/uv" && -f "$runtime_root/uv.sha256" ]] || die 'Existing uv has no binding'
  sha256sum --status -c "$runtime_root/uv.sha256" || die 'Owned uv executable drift'
fi
case "$("$runtime_root/bin/uv" --version)" in 'uv 0.11.25'|'uv 0.11.25 ('*) ;; *) die 'Native uv version differs' ;; esac
env -i HOME="$HOME" PATH=/usr/bin:/bin TMPDIR="$runtime_root/tmp" XDG_CACHE_HOME="$runtime_root/cache" \
  UV_CACHE_DIR="$runtime_root/cache/uv" UV_PYTHON_CACHE_DIR="$runtime_root/cache/python" \
  UV_PYTHON_CPYTHON_BUILD=20260623 UV_PYTHON_INSTALL_DIR="$runtime_root/python" \
  "$runtime_root/bin/uv" --no-config --no-progress python install --no-bin --no-registry "$PYTHON_KEY"
python="$runtime_root/python/$PYTHON_KEY/bin/python3.12"
[[ -f "$python" ]] || die 'Native managed Python executable missing'
if [[ -e "$runtime_root/python.sha256" ]]; then
  sha256sum --status -c "$runtime_root/python.sha256" || die 'Managed Python executable drift'
else sha256sum "$python" > "$runtime_root/python.sha256"; fi
flags=()
((runtimes_only)) && flags+=(--runtimes-only)
((resume_install)) && flags+=(--resume-install)
((local_cpu)) && flags+=(--local-cpu --confirmed)
# FD9 serializes this one bootstrap through the existing package installer.
env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 TMPDIR="$runtime_root/tmp" \
  XDG_CACHE_HOME="$runtime_root/cache" PYTHONDONTWRITEBYTECODE=1 \
  "$python" -I -B "$SOURCE/harness/bootstrap.py" --home "$home_path" --runtime-root "$runtime_root" \
  "${flags[@]}" -- "${arguments[@]}"
