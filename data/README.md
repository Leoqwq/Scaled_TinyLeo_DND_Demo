# Offline recordings and experiment data

This directory contains the experiment outputs migrated from `TinyLeo_CA/outputs/`.
No Google Cloud account, VM access, SSH tunnel, or Python environment is required
for offline playback.

## One frontend for Replay and Compare

1. Clone the repository or use GitHub **Code → Download ZIP** and extract it.
2. Open **[replay.html](../replay.html)** at the repository root in a desktop browser.
   GitHub's HTML preview does not execute the page.
3. The default Compare view embeds a real Shortest Path / QoS Priority pair.
   Press **Play**, seek with the slider, or select 10× playback.
4. Select **Flow → bulk-cross** and **First route difference** to inspect routing.
   Review the RTT, loss, throughput, Final summary, and Route statistics below.

Both modes use this same frontend. **Live is currently unavailable**; the
retained Live button is outside the supported offline workflow.

## Select recording files

- **Replay:** click **Import replay**, choose one dated folder's `.replay.json`,
  and press Play. Import switches to Replay. Either recording in the embedded
  pair below provides a complete 301-frame example.
- **Compare:** select one completed schema v2 Shortest Path `.replay.json` and one
  completed schema v2 QoS Priority `.replay.json` in their corresponding fields.
  The page checks scenario, physical topology, and required provenance compatibility.
- Only `.replay.json` is an import format. ZIP/TAR archives, checksums, CSV indexes,
  summary JSON, and raw topology files are evidence or analysis inputs.
- Failed recordings contain partial evidence and cannot serve as completed comparisons.
- Schema v1 recordings support Replay, not multi-flow Compare.

## Pair embedded in replay.html

| Algorithm | Recording |
|---|---|
| Shortest Path | [336d637a… replay JSON](2026-09-08_20-28-45_shortest_path/336d637ad4df45aeb2bf4533187db122.replay.json) |
| QoS Priority | [3b0768e6… replay JSON](2026-09-08_20-34-51_qos_priority/3b0768e620924df4acb4437a5116e6d8.replay.json) |

These later manual recordings each contain 301 frames, pass the pair provenance
check, and exactly match the frontend's embedded data.

## Pair used in the historical acceptance report

| Algorithm | Recording |
|---|---|
| Shortest Path | [27241ed… replay JSON](2026-09-08_19-58-24_shortest_path/27241ed67b124bec98114f5acba5c3fc.replay.json) |
| QoS Priority | [dac7c802… replay JSON](2026-09-08_20-03-33_qos_priority/dac7c802b96343fb992c4ade04924066.replay.json) |

The [acceptance report](compare-20260909/acceptance-report.md) describes this
separate 301-frame pair. Import these files to reproduce its figures; do not
mix them with the default embedded pair. Historical `acceptance-runs.json`
also identifies these run IDs.

The presence of two pairs does not establish formal repeatability acceptance
or general superiority. Map overlays are geographic controller intent, not
packet-captured satellite-hop traces.

## Inventory

[recordings.csv](recordings.csv) lists relative paths, algorithm, schema, frame
count, status, and each recording's comparison eligibility. Two eligible files
are not necessarily compatible with each other; use the frontend's pair check.

- 16 recordings: 11 completed v2 runs, 3 failed v2 runs, and 2 legacy v1 runs.
- Each dated directory contains `.replay.json`, its original `.zip`, and `.sha256`.
- `compare-20260909/` contains the acceptance report, run references, notes, and historical logs.
- `tinyleo-replay.html` is a preserved historical export. Use root `replay.html` for team review.
- `seconds-20260905.tar.gz` and its summary contain the earlier one-second experiment.
- `canada-parity-20260901T232741Z/` and its tar.gz retain the earlier 12-epoch
  experiment, including 64/80/96-satellite candidate data and extracted outputs.

The data occupies about 498 MiB, including archives and extracted copies.
Clone or download the repository to obtain it; Git LFS is not required.
Local `.DS_Store` metadata is excluded from version control.

## Integrity and paths

[SHA256SUMS](SHA256SUMS) covers the published payload files and `../replay.html`.
This guide, the CSV index, and the checksum list itself are excluded.
From `data/`, run `shasum -a 256 -c SHA256SUMS` on macOS or
`sha256sum -c SHA256SUMS` on Linux. Original per-run ZIP checksums are retained.
Documentation translations have updated hashes; raw recordings and archive bytes are unchanged.

Historical absolute paths in reports, `acceptance-runs.json`, and archive
configurations identify the original environment. Use this guide and the CSV's
relative paths in a new clone. Historical service-state descriptions are not
claims that Live is currently operational.

For future local relay sessions, the code defaults to root `data/` and
`replay.html` regardless of the launch directory. Explicit path arguments override
these defaults. The original output directory and HTML filename remain local
compatibility links on the developer machine only, for an already-running relay.

This data accompanies [Scaled TinyLEO DND Demo](../README.md), built on
[TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO). See the root README for citation.
