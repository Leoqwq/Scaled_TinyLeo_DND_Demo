# Scaled TinyLEO DND Demo

A Canada-focused satellite network emulation demo for exploring how routing
choices affect competing traffic flows on a changing LEO topology.

This repository builds on [TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO).
It adapts the toolkit into a smaller regional experiment workflow with
one-second topology updates, offline browser replay, and recorded
Shortest Path / QoS Priority comparisons. The original TinyLEO research and
networking architecture are credited below.

[Team guide / 组员导览](docs/team-guide.md) · [Offline data guide](data/README.md) · [Documentation](docs/README.md)

## What the demo does

The comparison scenario runs C2, telemetry, and bulk UDP flows across the same
recorded physical topology under two routing modes. Receiver measurements and
ping probes help examine how prioritizing one flow affects the others.

- **Regional emulation:** Canada ground stations and a reduced satellite scenario,
  with offline checks for topology consistency, connectivity, and path diversity.
- **One-second updates:** 301 physical states over a 300-second experiment, with
  controller timing and deadline telemetry.
- **Offline replay:** generated HTML and saved recordings support playback,
  seeking, and inspection without an active VM connection.
- **A/B comparison:** matched recordings show geographic route intent alongside
  receiver throughput, packet loss, and ping RTT, including tradeoffs between flows.

The demo uses TinyLEO's northbound routing algorithms and extends the surrounding
experiment, measurement, and visualization workflow. Route overlays represent
controller intent; they are not observed packet-hop traces.

## Open the offline demo

Download and extract this repository using GitHub **Code → Download ZIP**, or clone it:

```sh
git clone --branch main https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo.git
```

**Replay and Compare use the same browser frontend:**

[`data/compare-20260909/tinyleo-compare.html`](data/compare-20260909/tinyleo-compare.html)

Open this downloaded HTML file in a desktop browser, then switch between
**Replay** and **Compare** on the page. GitHub's file preview does not run the
frontend. No server, Python, Google Cloud account, or VM connection is needed.
**Live is currently unavailable.** The retained Live button is not part of this
release's usage workflow.

### Which data should I select?

| Mode | Data to select | Steps in the same frontend |
|---|---|---|
| **Replay** — inspect one recorded run | One `.replay.json` from a dated folder in `data/`; use a completed 301-frame run for a full replay | Click **Import replay**, select the file, then press **Play**. Import switches the page to Replay. |
| **Compare** — compare two algorithms | Two completed, compatible **schema v2** `.replay.json` files: one `shortest_path`, one `qos_priority` | Click **Compare**, load each file into its matching **Shortest Path recording** / **QoS Priority recording** field, then press **Play**. |

For a first look, the page opens in Compare with the following real pair already
embedded. No import is required. Use either file alone for Replay, or select both
in their respective fields to reproduce the default comparison:

| File field | Recording path relative to the repository root |
|---|---|
| **Shortest Path recording** | [`data/2026-09-08_20-28-45_shortest_path/336d637ad4df45aeb2bf4533187db122.replay.json`](data/2026-09-08_20-28-45_shortest_path/336d637ad4df45aeb2bf4533187db122.replay.json) |
| **QoS Priority recording** | [`data/2026-09-08_20-34-51_qos_priority/3b0768e620924df4acb4437a5116e6d8.replay.json`](data/2026-09-08_20-34-51_qos_priority/3b0768e620924df4acb4437a5116e6d8.replay.json) |

Choose **Flow → bulk-cross** and **First route difference** to inspect routing
changes. The charts and summary show measured performance and tradeoffs.

All 16 runs are listed in [`data/recordings.csv`](data/recordings.csv), including
schema, frame count, status, and file paths. For Compare, use completed v2 runs
marked `comparison_eligible=True`; the frontend also checks that the pair shares
the same scenario, physical topology, and required provenance. Eligibility of
each file alone does not guarantee that any two files can be paired.
Legacy v1 recordings are Replay-only. Failed runs contain partial evidence and
must not be used as completed performance comparisons.

Import **`.replay.json` only**, not ZIP/TAR archives, `.sha256`, CSV indexes,
summary JSON, or raw topology files. Archives are retained for evidence and analysis.
The [offline data guide](data/README.md) also identifies the separate pair used
in the historical acceptance report; its numbers should not be mixed with the
default embedded pair.

The full data directory is about 498 MiB. The HTML files elsewhere in the
repository are historical exports, templates, or the original paper website;
use the single frontend linked above for both Replay and Compare.

## Validation status

The [dated experiment record](docs/superpowers/plans/2026-09-08-live-qos-progress.md#vm-handover-and-single-pair-acceptance--2026-09-08-local-time)
documents one accepted multi-flow A/B pair on September 8, 2026. Both runs
completed 301 frames with zero recorded one-second deadline misses. C2 improved
in that pair, while other flows showed tradeoffs.

This is a demonstration result, not a repeated-trial finding or a general claim
that QoS Priority outperforms Shortest Path. The record applies to that experiment
version; later source changes are not automatically VM-validated. Synthetic
browser fixtures test interface behavior and are not performance evidence.

## Repository map

| Location | Contents |
|---|---|
| [`network_synthesizer/`](network_synthesizer/) | TinyLEO network synthesis, with regional/windowed and one-second orbit additions |
| [`network_orchestrator/`](network_orchestrator/) | TinyLEO routing, MPC, southbound and SRv6 code, with emulation and validation adaptations |
| [`tools/`](tools/) | Preparation, execution, and checking of one-second runs |
| [`tools/replay/`](tools/replay/) | Live relay, traffic collection, recording, replay, and comparison UI |
| [`data/`](data/README.md) | Offline demo, recorded runs, raw archives, and integrity checksums |
| [`docs/`](docs/README.md) | Guides, runbooks, and dated design/validation records |

The [12-epoch Canada runbook](docs/canada-parity-runbook.md) is retained as a
historical workflow. The files under `docs/static/` and `docs/index.html` belong
to the original TinyLEO paper website, not the browser experiment demo.

## Acknowledgments and citation

This project is derived from **TinyLEO**, developed by Yuanjie Li, Yimei Chen,
Jiabo Yang, Jinyao Zhang, Bowen Sun, Lixin Liu, Hewu Li, Jianping Wu, Zeqi Lai,
Qian Wu, and Jun Liu. TinyLEO provides the underlying network synthesis,
orbital model predictive control, and geographic segment anycast architecture.

This repository's extensions focus on the Canada experiment setup, temporal
resolution, validation, traffic collection, and offline Replay/Compare workflow.
It is a derivative demo, not the official TinyLEO distribution.

- [Original source code](https://github.com/TinyLEO-toolkit/TinyLEO)
- [Official project and paper website](https://tinyleo-toolkit.github.io/TinyLEO/)
- [Paper included in this repository](sigcomm25-tinyleo.pdf)

When using the underlying TinyLEO methods or toolkit in research, cite the
original SIGCOMM 2025 paper. When referring to this demo's extensions or results,
also identify this repository and the commit or recording used.

```bibtex
@inproceedings{tinyleo,
  author  = {Li, Yuanjie and Chen, Yimei and Yang, Jiabo and Zhang, Jinyao and Sun, Bowen and Liu, Lixin and Li, Hewu and Wu, Jianping and Lai, Zeqi and Wu, Qian and Liu, Jun},
  title   = {Small-scale LEO Satellite Networking for Global-scale Demands},
  booktitle={Proceedings of the ACM SIGCOMM 2025 Conference},
  year    = {2025},
}
```

## License

This repository retains the [Apache License 2.0](LICENSE) from TinyLEO.
Original copyright attribution: **Copyright 2025 TinyLEO**.
The upstream license and source notices are preserved alongside the demo extensions.
