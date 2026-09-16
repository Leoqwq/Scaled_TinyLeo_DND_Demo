# Offline replay data / 离线回放数据

本目录收录原 `TinyLeo_CA/outputs/` 的完整实验输出。组员无需 Google Cloud 账号、
VM 权限、SSH 隧道或 Python 环境即可观看内置回放。

## 最快打开方式

1. 下载并解压整个仓库（GitHub **Code → Download ZIP**），或 clone `main`。
2. 用桌面浏览器打开 [compare-20260909/tinyleo-compare.html](compare-20260909/tinyleo-compare.html)。
   GitHub 文件预览不会执行 HTML，必须下载后在本地打开。
3. 页面默认进入 **Compare**，已内置一组真实 Shortest Path / QoS Priority 录制，
   无需选择数据文件。点击 **Play**，或使用时间滑块；可以选择 10× 播放。
4. 在 **Flow** 中选择 `bulk-cross`，点击 **First route difference** 查看路由差异。
   向下查看 RTT、丢包、吞吐量曲线、Final summary 和 Route statistics。

请使用 **Replay / Compare**。**Live** 需要实验负责人的 VM 环境和权限，当前不面向组员开放。
离线页面保留了 Live 入口，但它不影响已有录制的播放。

## 导入其他录制

- **单轮回放：** 点击 **Import replay**，选择任一日期目录内的 `.replay.json`。
- **两轮比较：** 在 **Compare** 的 Shortest Path 和 QoS Priority 两个文件选择框中，
  分别导入对应的 v2 `.replay.json`。页面会验证场景、物理拓扑和运行来源是否匹配。
- ZIP 是原始证据档案，不能直接作为浏览器导入文件。
- 失败记录保留用于排查，只包含部分时间轴；不能作为完整性能对照。
- 旧版 schema v1 记录用于 Replay，不适用于多流 Compare。

## HTML 内置的真实 A/B 对照

| Algorithm | Recording |
|---|---|
| Shortest Path | [336d637a… replay JSON](2026-09-08_20-28-45_shortest_path/336d637ad4df45aeb2bf4533187db122.replay.json) |
| QoS Priority | [3b0768e6… replay JSON](2026-09-08_20-34-51_qos_priority/3b0768e620924df4acb4437a5116e6d8.replay.json) |

这两份稍后的手动录制各有 301 帧，已通过配对来源检查，与 HTML 内置数据完全一致。

## 历史验收报告对应的 A/B 对照

| Algorithm | Recording |
|---|---|
| Shortest Path | [27241ed… replay JSON](2026-09-08_19-58-24_shortest_path/27241ed67b124bec98114f5acba5c3fc.replay.json) |
| QoS Priority | [dac7c802… replay JSON](2026-09-08_20-03-33_qos_priority/dac7c802b96343fb992c4ade04924066.replay.json) |

[验收报告](compare-20260909/acceptance-report.md)的数字对应这一组，各有 301 帧。
要复核报告，请在 Compare 中导入这两份文件；不要将默认内置那组的数字与报告混用。
历史 `acceptance-runs.json` 也记录了这一组的 run ID。

两组记录不等于已完成正式重复性验收，也不代表普遍优越性结论。
地图表示控制器的地理路由意图，不是逐卫星抓包轨迹。

## 数据清单

完整的逐轮索引见 [recordings.csv](recordings.csv)：包含相对路径、算法、schema、
帧数、完成状态及录制自身的 comparison eligibility 标记。
两份文件各自 eligible 仍不保证互相匹配，应以 Compare 配对检查为准。

- 16 轮录制：11 轮完成的 v2、3 轮失败的 v2、2 轮旧版 v1。
- 每个日期目录保留 `.replay.json`、原始 `.zip` 和 `.sha256`。
- `compare-20260909/`：内置 A/B 页面、验收报告、历史操作说明及后台日志。
- `tinyleo-replay.html`：早期一秒录制的独立回放页面。
- `seconds-20260905.tar.gz` 及 summary：早期一秒实验归档。
- `canada-parity-20260901T232741Z/` 及同名 tar.gz：早期 12-epoch 实验的
  解压数据和原始压缩包，包括 64/80/96 卫星候选数据。

完整目录约 498 MiB，包含压缩包及解压副本。Git clone 或仓库 ZIP 下载即可取得数据，
不需要 Git LFS。`.DS_Store` 为本机元数据，不上传。

## 校验与历史路径

[SHA256SUMS](SHA256SUMS)覆盖本次发布的数据文件（不包含此 README、索引与校验清单本身）。
在 `data/` 中运行 `shasum -a 256 -c SHA256SUMS`（macOS）或
`sha256sum -c SHA256SUMS`（Linux）可验证下载完整性。
每轮 ZIP 的原有 `.sha256` 也保留。

历史报告、`acceptance-runs.json`、归档配置及 Quickstart 中的开发机/VM 绝对路径
仅用于记录当时的环境，不是组员需要创建的目录；请以本页及 recordings.csv 的相对路径为准。
历史 Quickstart 对“后台正在运行”的描述不代表当前服务状态。

此数据随 [Scaled TinyLEO DND Demo](../README.md) 分享，底层工具与研究来自
[TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO)；引用方式见项目首页。
