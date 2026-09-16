# Scaled TinyLEO DND Demo

A Canada-focused satellite network emulation demo for exploring how routing
choices affect competing traffic flows on a changing LEO topology.

This repository builds on [TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO).
It adapts the toolkit into a smaller regional experiment workflow with
one-second topology updates, browser-based Live/Replay, and recorded
Shortest Path / QoS Priority comparisons. The original TinyLEO research and
networking architecture are credited below.

[Team guide / 组员导览](docs/team-guide.md) · [Documentation](docs/README.md) · [Live setup](tools/replay/LIVE.md)

## What the demo does

The comparison scenario runs C2, telemetry, and bulk UDP flows across the same
recorded physical topology under two routing modes. Receiver measurements and
ping probes help examine how prioritizing one flow affects the others.

- **Regional emulation:** Canada ground stations and a reduced satellite scenario,
  with offline checks for topology consistency, connectivity, and path diversity.
- **One-second updates:** 301 physical states over a 300-second experiment, with
  controller timing and deadline telemetry.
- **Live control:** a browser connects through a local relay and SSH tunnel to a
  manually prepared Linux VM session.
- **Offline replay:** generated HTML and saved recordings support playback,
  seeking, and inspection without an active VM connection.
- **A/B comparison:** matched recordings show geographic route intent alongside
  receiver throughput, packet loss, and ping RTT, including tradeoffs between flows.

The demo uses TinyLEO's northbound routing algorithms and extends the surrounding
experiment, measurement, and visualization workflow. Route overlays represent
controller intent; they are not observed packet-hop traces.

## Get started

```sh
git clone --branch main https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo.git
cd Scaled_TinyLeo_DND_Demo
```

**To browse the project**, start with the [team guide](docs/team-guide.md).
It maps the source files to the experiment workflow and includes local test commands.

**To watch a recorded demo**, obtain the generated `tinyleo-compare.html` and
matched recordings from the experiment owner. A page with embedded recordings
can be opened directly in a browser. Full experiment archives and the generated
demo are distributed separately from this source repository.
The files `tools/replay/seconds.html` and `template.html` are build templates;
see the [Replay guide](tools/replay/README.md) for building a historical replay.

**To run an experiment**, follow the [one-second workflow](docs/second-resolution-emulation.md)
and [Live setup](tools/replay/LIVE.md). Full emulation requires a prepared Linux
VM with network namespaces, SRv6, and the documented dependencies. The browser
alone does not create the emulation environment.

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
resolution, validation, traffic collection, and Live/Replay/Compare workflow.
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
