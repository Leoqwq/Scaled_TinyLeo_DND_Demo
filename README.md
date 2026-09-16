# Scaled TinyLEO DND Demo

A Canada-focused satellite network emulation demo for exploring how routing
choices affect competing traffic flows on a changing LEO topology.

This repository builds on [TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO).
It adapts the toolkit into a smaller regional experiment workflow with
one-second topology updates, offline browser replay, and recorded
Shortest Path / QoS Priority comparisons. The original TinyLEO research and
networking architecture are credited below.

[Changes from TinyLEO](docs/upstream-changes.md) · [Emulation profile](docs/emulation-profile.md) · [Team guide](docs/team-guide.md) · [Offline data](data/README.md)

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

The demo compares TinyLEO's upstream-derived Shortest Path baseline with this
fork's added `qos_priority` policy, and extends the experiment, measurement, and
visualization workflow. Route overlays represent
controller intent; they are not observed packet-hop traces.

## Scaled emulation parameters

These parameters describe the recorded multi-flow demo; Live is currently unavailable.

| Parameter | Recorded demo configuration |
|---|---|
| Scale | **96 satellite nodes + 6 ground stations = 102 emulated nodes** on one Linux VM |
| Altitude and orbit | **573 km**; circular Kepler model with Earth rotation, synthetic anchor |
| Geographic scope | Six Canada scenario cells: **12, 13, 14, 23, 24, 25** in an 11 x 11 grid |
| Ground stations | Whitehorse, Yellowknife, Iqaluit, Vancouver, Calgary, Toronto |
| Duration | **300 seconds**, states t=0…300: **301 snapshots at 1-second intervals** |
| Experiment machine | Documented GCP **n2-standard-8: 8 vCPUs, 32 GiB RAM**; controller and all nodes share the VM |
| Link rates | **10 Mbit/s ISL**, **100 Mbit/s GSL**; 1000-packet queues; configured random loss 0% |
| Traffic | C2 **4 Mbit/s**, priority 5; telemetry **2 Mbit/s**, priority 3; bulk **9 Mbit/s**, priority 1 |
| Comparison window | **80–240 s**, when all three UDP flows compete; payload size 1000 bytes |
| Measurement | iperf3 **3.20** receiver records, ping RTT, controller timing, and kernel evidence |

**Coverage needs qualification:** the original 96-satellite, 12-epoch synthesis
satisfied **93.75% of modeled demand**, below its 95% target. This is neither
Canada land-area coverage nor radio visibility certification. The newer 301-state
topology has a separate **93.023% two-edge-disjoint-path epoch ratio**, with
32 topology changes and 36 gateway handovers. Only 12–14 of the 96 satellites
participate in the matched regional topology at a given state. The inherited
GSL elevation cutoff is not enforced.

The [full emulation profile](docs/emulation-profile.md) gives station coordinates,
traffic phases, coverage definitions, host evidence, and recorded resource usage.
Exact VM image/kernel/Python versions and disk configuration are not established
by the published run metadata. Ubuntu 22.04+ is a documented deployment requirement,
not a verified image identifier.

## What changed from TinyLEO?

The [consolidated change overview](docs/upstream-changes.md) covers the cumulative
fork changes against upstream commit `bd5dc97`: priority-aware routing and routing
analysis tools; bounded regional synthesis; topology validation; single-VM/SRv6
runtime fixes; one-second propagation and timing; real multi-flow measurements;
versioned archives; and the unified Replay/Compare frontend with bundled data.
It identifies source files and representative commits, and separates inherited
TinyLEO methods from this project's extensions.

## Open the offline demo

Download and extract this repository using GitHub **Code → Download ZIP**, or clone it:

```sh
git clone --branch main https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo.git
```

**Replay and Compare use the same browser frontend:**

[`replay.html`](replay.html)

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
| [`replay.html`](replay.html) | Unified offline Replay / Compare frontend |
| [`data/`](data/README.md) | Recorded runs, raw archives, and integrity checksums |
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
