# Native bootstrap sources

The bootstrap downloads upstream runtime archives. The repository does not
bundle Python, Node, uv, model weights or a model server.

- uv0.11.25: <https://github.com/astral-sh/uv/releases/tag/0.11.25>.
  Linux x64 GNU archive SHA256:
  `1db18b5e76fa645a7f3865773139bdec8e2d46adbdbb35e7410b34fa8015ccd2`.
  Astral's MIT licence is at
  <https://github.com/astral-sh/uv/blob/0.11.25/LICENSE-MIT>.
- CPython3.12.13/build20260623: native uv managed-Python distribution.
  <https://docs.astral.sh/uv/guides/install-python/>.
  Retain its included CPython and bundled-library licences. Distribution details:
  <https://docs.astral.sh/python-build-standalone/distributions/>.
- Node22.23.2 Linux x64 archive: 31,058,332 bytes; SHA256
  `d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307`.
  <https://nodejs.org/download/release/v22.23.2/SHASUMS256.txt>.
  The complete native archive retains Node's MIT and bundled dependency notices
  in its `LICENSE` file. No dependency licence is replaced by this repository's
  licence.

The download transaction reuses the existing source system's immutable
revision/hash, resume, conflict refusal and free-space checks. Its Rig model
choices, private paths, service queue and storage floor are excluded.
Runtime-version checks do not establish full agent operation, model fit,
generation quality or an accepted project outcome.
