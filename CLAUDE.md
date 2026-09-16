# Repository guidance

- Read `README.md` and `docs/team-guide.md` for scope and navigation.
- `docs/upstream-changes.md` tracks fork changes; `docs/emulation-profile.md` defines recorded parameters.
- QoS priority routing is a fork addition; distinguish synthesis coverage from radio coverage.
- Preserve upstream attribution, `LICENSE`, and paper citations.
- Keep the existing source layout: scripts and example configs use relative paths.
- Local Replay tests: `python -m unittest discover -s tools/replay -p 'test_*.py' -v`.
  They require numpy/networkx; HTTP tests bind loopback ports.
- Pure JavaScript comparison check: `node tools/replay/test_compare.cjs`.
- Full emulation requires a prepared Linux VM; local tests do not certify it.
- Treat `docs/superpowers/` as dated design and evidence, not a current task queue.
- Keep measured packet results, model estimates, and synthetic fixtures distinct.
- Shared experiment recordings belong in `data/`; preserve raw evidence and checksums.
- Keep machine credentials outside tracked source.
- Inspect existing uncommitted work before edits; do not overwrite it.
- Deployment and traffic experiments have external effects; follow the requested scope.
