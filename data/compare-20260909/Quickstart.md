# TinyLEO Compare：浏览器验收与录制

## 现在怎么打开

打开 <http://127.0.0.1:8765/>。Mac 后台已经运行 SSH 隧道和网页代理；
VM 后台运行控制器及 96 个卫星、6 个地面站节点，不需要再开三个终端。

## 离线讲解

页面内置本次一组真实 Shortest Path / QoS Priority 结果，默认进入 Compare。

1. 默认窗口为整个竞争阶段 80–240 秒；页面从地图和播放控制开始，再向下看曲线、Final summary 和 Route statistics。
2. 在 `Flow` 中选择 `bulk-cross`，点击 `First route difference`，先解释改道，再切 C2 说明路径不变但竞争减少。
3. 同一地图中蓝实线代表 Shortest Path，橙虚线代表 QoS，灰线代表共同路段。
4. 取消 `Only show differences` 可看完整路径；选择 10× 快速同步播放。
5. 继续向下看 RTT、丢包和吞吐量曲线，再用 Final summary 量化收益与代价；不能只凭路径不同宣称优势。

双击同目录的 `tinyleo-compare.html` 也能完全离线展示内置对比，不需要 VM。
直接打开文件不支持 Live。地图覆盖线是地理 cell 层路由策略，不是抓包还原的逐卫星路径。

## 你手动再跑一组

1. 在 HTTP 页面点击 `Live`，等待状态 `completed` 且 `Archive: saved`，或 `ready`。
2. 选择 Shortest Path，点击 `Start emulation`。等待约五分钟及自动下载完成。
3. 选择 QoS Priority，再运行一次；不要同时启动两种算法。
4. 两轮完成后在 Compare 分别导入对应的 `.replay.json`。内置的原验收对照不会被覆盖。

每轮自动保存 `.zip`、`.sha256` 和 `.replay.json` 到上一级 `outputs` 下的独立目录：
`YYYY-MM-DD_HH-MM-SS_shortest_path/` 或 `YYYY-MM-DD_HH-MM-SS_qos_priority/`。
时间取首帧记录的实际运行时间，使用 Mac 本地时区；首帧前失败则用下载时间。
本目录仅保留对比页面、验收报告及后台日志，不再接收单轮结果。
已有 7 轮 Live 结果也已整理至上一级，文件名和内容不变。
无效或未完整结束的记录不能用作 Compare 性能对照，但失败原始档案保留。

## 注意

- 不需要手动创建节点；当前节点已准备好。网页 Start 只启动实验。
- 关闭浏览器不会停止 VM 上的实验；后台代理仍负责下载。
- Mac 休眠、VM 关机或后台 SSH/代理被关闭后，Live 会断开；离线页面不受影响。
- 网页显示 `Disconnected` 或 `failed` 时不要反复点 Start，应先检查后台服务和错误。
- 本次仅自动验收一组 A/B；重复性由你随后手动验证，不声称已通过三组重复实验。
- UDP 区间丢包计数可能因迟到包出现负修正。原值保留并在区间汇总中计入，
  图表不把负修正显示成零丢包；阶段边界外的数据不偷偷挪入当前阶段。

## 当前部署

- VM：`tinyleo-canada-parity`，项目 `satellite-emulator`，zone `northamerica-northeast1-b`。
- VM 源码：`/home/leo/tinyleo-compare-20260909-v1`，包含此次已验证修复。
- VM 准备日志：该目录下 `prepare-v6.log`。
- 测量程序：`/home/leo/tinyleo-tools/iperf-3.20/bin/iperf3`，不替换系统 iperf3。
- Mac 后台日志：本目录的 `ssh-tunnel.log` 和 `relay.log`。
- 私人访问令牌位于 `/Users/leo/.tinyleo-live/`，不在 HTML 或回放档案里。

旧单流手册与旧 `outputs/tinyleo-replay.html` 留作历史参考，不要用旧准备命令覆盖此会话。
