# Historical controller fixture

`agent-home-controller-source60.py.txt` retains the public `harness/home.py` from
commit `3808ec7610d3e2d083cd68124c75d381e956a74d`, Git blob
`6c4f6da54eff24ae49caf79a5b3a445fcd8168ed`. It is test data, not an installer.

The test loader checks exact LF/CRLF byte hashes, copies the actual source to
the test tree and loads it from that true path. Production v1 AST hashes and
admission scopes remain fixed. New controller features must still be refused
by those historical scopes; do not update their production hashes for a fixture.
