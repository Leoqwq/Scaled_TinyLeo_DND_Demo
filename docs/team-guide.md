# Team guide

## Project scope

This project extends [TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO) with
Canada experiment workflows and a browser interface. The upstream synthesizer,
MPC controller, SRv6 data plane, paper attribution, and Apache 2.0 license are retained.

| Component | Source entry points |
|---|---|
| Offline Replay / Compare frontend | [`replay.html`](../replay.html) at the repository root |
| Canada topology validation | `network_orchestrator/topology_artifact_validator.py` |
| One-second orbit states and clock | `network_synthesizer/second_orbits.py`, `network_orchestrator/second_clock.py` |
| Experiment preparation, execution, checks | `tools/prepare_second_run.py`, `tools/run_second_emulation.py`, `tools/check_second_run.py` |
| Upstream-derived baseline and added QoS routing | `network_orchestrator/northbound.py` |
| Multi-flow scenario and capacity adaptation | `tools/replay/scenario.py`, `tools/replay/competition.py` |
| Traffic, archives, and kernel evidence | `traffic.py`, `competition_archive.py`, `evidence.py` under `tools/replay/` |
| VM session and local relay | `tools/replay/live.py`, `tools/replay/live_server.py` |
| UI template and comparison logic | `seconds.html`, `compare.js`, `compare_ui.js` under `tools/replay/` |

Start with the [cumulative change overview](upstream-changes.md),
[emulation parameters](emulation-profile.md), and [offline data guide](../data/README.md),
then explore the relevant source.
The [one-second workflow](second-resolution-emulation.md) documents the experiment model.

## Watch recordings

Download the repository and open **[replay.html](../replay.html)** in a desktop
browser. Both Replay and Compare use this one frontend. The default Compare
view embeds a real pair; press Play to start. No Google Cloud account, VM, SSH,
Python, or server is needed. Live is currently unavailable.

For Replay, click **Import replay** and select one `.replay.json`.
For Compare, select a completed, compatible v2 Shortest Path recording and a
QoS Priority recording in their respective fields. Recommended paths, failed
recordings, and checksums are listed in the [data guide](../data/README.md).
GitHub previews HTML as source; download it before opening it.
`tools/replay/seconds.html` is a build template and `docs/index.html` is the
upstream paper website, not an alternative demo entry point.

## Validation boundaries

The final section of the [dated acceptance record](superpowers/plans/2026-09-08-live-qos-progress.md#vm-handover-and-single-pair-acceptance--2026-09-08-local-time)
records one real A/B pair on September 8, 2026: both runs completed 301 frames
with zero recorded deadline misses. C2 improved in that pair; other flows had
tradeoffs. This does not establish repeatability or general QoS superiority.
The frontend embeds a later pair, separately identified in the data guide.

Earlier plans preserve historical checkpoints. Their pending items should be
read alongside the final acceptance record. Historical VM results do not certify
later source changes. Model estimates, measured packets, and synthetic browser
fixtures are different forms of evidence.

## Local checks

From the repository root, using Python 3.10 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install numpy networkx
python -m unittest discover -s tools/replay -p 'test_*.py' -v
```

HTTP tests need permission to bind loopback ports. These are local dependencies,
not the full VM deployment environment; versions are not pinned.
With Node.js installed, run the browser-independent comparison checks:

```sh
node tools/replay/test_compare.cjs
```

Browser regression tests additionally require Playwright, Google Chrome, and a
rendered HTML file; see the [Replay developer guide](../tools/replay/README.md).
Local checks do not cover Linux namespaces, SSH deployment, or SRv6 forwarding.
Some upstream `test/` scripts execute full experiments; do not treat a repository-wide
test discovery command as a lightweight check.

## Data and configuration

- Shared recordings and future local relay downloads use the root `data/` directory.
- The relay defaults to `<repository>/data` and `<repository>/replay.html`, independent
  of the working directory. Explicit `--output` and `--html` arguments override these defaults.
- An already-running process retains its original arguments. This development machine
  keeps local compatibility links for the former output directory and HTML path;
  new clones do not need these links. No VM restart or Live availability is implied.
- Preserve raw evidence and verify new recordings before committing them.
- Temporary outputs can use ignored `outputs/` or `tools/replay/results/` directories.
- Never commit SSH keys, session tokens, or private machine configurations;
  use `*.local.json` for machine-specific JSON.
- Historical `/home/leo/...` and `/Users/leo/...` paths identify the original environment.

See [GitHub sharing](github-sharing.md) and the [documentation index](README.md).
