# 组员导览 / Team guide

## 这个仓库是什么

本项目基于原版 [TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO)，增加 Canada
实验工作流和浏览器演示。原版的网络合成器、MPC 控制器、SRv6 数据面、论文与
Apache 2.0 许可仍保留。目录没有重新搬动，以保持既有脚本的相对路径可用。

| 内容 | 主要入口 |
|---|---|
| Canada 拓扑一致性与连通性验证 | `network_orchestrator/topology_artifact_validator.py` |
| 每秒物理轨道状态与实验时间轴 | `network_synthesizer/second_orbits.py`、`network_orchestrator/second_clock.py` |
| 准备、运行、检查一秒实验 | `tools/prepare_second_run.py`、`tools/run_second_emulation.py`、`tools/check_second_run.py` |
| 原版路由算法 | `network_orchestrator/northbound.py` |
| 多流场景与容量竞争适配 | `tools/replay/scenario.py`、`tools/replay/competition.py` |
| 真实流量采集、归档与证据 | `tools/replay/traffic.py`、`competition_archive.py`、`evidence.py`（均在同目录） |
| Live 服务和本地中继 | `tools/replay/live.py`、`tools/replay/live_server.py` |
| Replay / Compare 页面与统计 | `tools/replay/seconds.html`、`compare.js`、`compare_ui.js`（均在同目录） |

建议先读本页，再看 [一秒实验说明](second-resolution-emulation.md) 和
[Live 操作说明](../tools/replay/LIVE.md)，最后按兴趣进入源码。

## 已验证到哪一步

[验收记录的最后一节](superpowers/plans/2026-09-08-live-qos-progress.md#vm-handover-and-single-pair-acceptance--2026-09-08-local-time)
记录了 2026-09-08 的一组真实 Shortest Path / QoS Priority A/B 实验：两次均完成
301 帧，记录的 deadline miss 均为零。该组实验中 C2 指标改善，但其他流存在取舍。
这不等于完成重复性验证，也不代表 QoS 在所有场景下优于基线。

早期计划和进度文件保留历史上下文；其中旧的“待验收”段落应结合最后的验收记录阅读。
既有记录也不自动证明之后的工作区修改已在 VM 上重新验证。
模型路径意图、真实包测量和浏览器合成测试数据是三类不同证据。

## 只看演示

从仓库下载完整文件后，用桌面浏览器打开
[`data/compare-20260909/tinyleo-compare.html`](../data/compare-20260909/tinyleo-compare.html)。
页面已内置真实 A/B 录制，默认进入 Compare，点击 Play 即可播放。
无需 Google Cloud 账号、VM、SSH 或 Python；Live 当前不可用。
Replay 也使用同一个 HTML：点击 Import replay 导入单份 `.replay.json`。
Compare 则选取一份 Shortest Path 和一份 QoS Priority 的完整、匹配 v2 录制，
具体推荐文件路径见下面的离线数据指南。

全部 16 轮录制、原始归档和早期实验输出都在根目录 `data/`，
具体导入方式、成功/失败记录清单及校验步骤见 [离线数据指南](../data/README.md)。
GitHub 的 HTML 预览不运行页面，需下载后打开。
`tools/replay/seconds.html` 仍是构建模板，`docs/index.html` 仍是原版论文网站。

## 本地轻量检查

在仓库根目录执行，使用 Python 3.10 或更高版本：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install numpy networkx
python -m unittest discover -s tools/replay -p 'test_*.py' -v
```

这里覆盖 Replay/Compare 的本地 Python 测试；HTTP 测试需要允许绑定本机回环端口。
这是轻量依赖集合，不是完整 VM 部署环境，依赖尚未锁定版本。
如已安装 Node.js，还可以运行不需要浏览器的比较统计检查：

```sh
node tools/replay/test_compare.cjs
```

浏览器回归另需 Playwright、Google Chrome 和生成后的 HTML，详见
[Replay README](../tools/replay/README.md)。完整 emulation 需要配置好的 Linux VM、
SSH、网络命名空间和 SRv6 环境；普通 Mac 本地检查不覆盖这些部署步骤。
原版 `test/` 中部分脚本会运行完整实验，不应把全仓测试发现命令当成轻量检查。

## 数据和配置

- 原版已跟踪的 `.npy` 数据及图片保留，供既有示例使用。
- 已共享录制及后续本地下载使用根目录 `data/`；提交新增数据前核对录制完整性和凭据。
- 临时输出仍可放在被忽略的 `outputs/` 或 `tools/replay/results/`。
- SSH 私钥、Live session token 和真实机器配置不提交；机器专用 JSON 可使用 `*.local.json`。
- 旧文档中的 `/home/leo/...` 和 `/Users/leo/...` 是历史环境路径，使用前替换为自己的路径。
- 地图、吞吐、延迟和丢包结果的含义与限制见 [Live 说明](../tools/replay/LIVE.md)。

上传方式见 [GitHub 分享指南](github-sharing.md)；所有文档入口见 [索引](README.md)。
