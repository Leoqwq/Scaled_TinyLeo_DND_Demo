# TinyLEO: Small-scale LEO Satellite Networking for Global-scale Demands

<div style="text-align: justify">
TinyLEO is an open-source community toolkit to enable small-scale Low Earth Orbit (LEO) satellite network for global-scale network demands via dynamic spatiotemporal supply-demand matching. It can sparsify satellite network supplies on demand via compressed sensing, hide complexities of their heterogeneous physical dynamics in its stable model predictive control plane, and move the responsibility for handling them to its data-plane geographic segment anycast for higher network usability, lower resource wastes, faster failovers, simpler satellites, and more flexible network orchestration.
</div>
<p></p>

<div align=center>
<img src="docs/toolkit.png" width="800px"/>
</div>

## Canada experiments and team review

This working version extends the upstream [TinyLEO toolkit](https://github.com/TinyLEO-toolkit/TinyLEO)
with Canada topology validation, one-second emulation, browser Live/Replay,
and multi-flow Shortest Path / QoS Priority comparison. The original toolkit,
paper attribution and Apache 2.0 license are retained.

**组员从这里开始：[项目导览与上手](docs/team-guide.md)。**
Publishing this checkout: [GitHub sharing guide](docs/github-sharing.md).

| Goal | Start here |
|---|---|
| Understand the extensions and what has been validated | [Team guide](docs/team-guide.md) |
| Browse all documentation | [Documentation index](docs/README.md) |
| View recorded experiments in a browser | [Replay guide](tools/replay/README.md) |
| Prepare a Linux VM and run Live / Compare | [Live setup](tools/replay/LIVE.md) |
| Generate and run 301 physical states over 300 seconds | [One-second workflow](docs/second-resolution-emulation.md) |
| Study the original offline / online components | [Synthesizer](network_synthesizer/README.md) · [Orchestrator](network_orchestrator/README.md) |

The latest recorded multi-flow acceptance is **one real A/B pair**, documented
in the [dated validation record](docs/superpowers/plans/2026-09-08-live-qos-progress.md#vm-handover-and-single-pair-acceptance--2026-09-08-local-time).
It is not a repeated-trial or universal QoS superiority result. Full experiment
archives and the generated standalone demo are not included in this checkout;
request them from the experiment owner. Browser fixtures are synthetic tests.

## Code structure

```text
TinyLEO/
├── network_synthesizer/   # Offline demand-driven network synthesis
├── network_orchestrator/ # Northbound routing, MPC, southbound and SRv6
├── tools/                # One-second experiment preparation and execution
│   └── replay/           # Live relay, traffic collection, replay and Compare
├── docs/                 # Team guide, runbooks, historical plans and paper site
├── LICENSE               # Apache 2.0
└── sigcomm25-tinyleo.pdf  # Original SIGCOMM 2025 paper
```

The historical 12-epoch Canada workflow remains available in the
[parity runbook](docs/canada-parity-runbook.md). Use the one-second workflow
above for the newer temporal-resolution experiments.

## How to Cite TinyLEO?

Please use the following BibTeX file when citing TinyLEO:

```bibtex
@inproceedings{tinyleo,
  author  = {Li, Yuanjie and Chen, Yimei and Yang, Jiabo and Zhang, Jinyao and Sun, Bowen and Liu, Lixin and Li, Hewu and Wu, Jianping and Lai, Zeqi and Wu, Qian and Liu, Jun},
  title   = {Small-scale LEO Satellite Networking for Global-scale Demands},
  booktitle={Proceedings of the ACM SIGCOMM 2025 Conference},
  year    = {2025},
}
```

## License

TinyLEO toolkit is released under the [Apache 2.0 license](LICENSE).

```
Copyright 2025 TinyLEO

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

```
