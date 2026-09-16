# TinyLEO 单组真实 A/B 验收

本次仅自动运行一组成功 A/B；后续重复性由用户手动验证。结果不是离线算法估计。

Shortest Path: 27241ed67b124bec98114f5acba5c3fc
QoS Priority: dac7c802b96343fb992c4ade04924066

统计窗口固定为 80 ≤ t < 240 秒。两份记录均完整 301 帧；全部逐帧位置、链路、场景、时轴与记录的运行代码哈希匹配。

| 流 | 指标 | Shortest Path | QoS Priority | QoS − Shortest |
|---|---|---:|---:|---:|
| c2-north | UDP loss (%) | 46.239 | 6.331 | -39.908 |
| c2-north | ping p95 RTT (ms) | 2505.000 | 140.000 | -2365.000 |
| c2-north | received throughput (Mbit/s) | 2.116 | 3.747 | 1.631 |
| telemetry-east | UDP loss (%) | 34.570 | 34.237 | -0.333 |
| telemetry-east | ping p95 RTT (ms) | 1331.000 | 2113.000 | 782.000 |
| telemetry-east | received throughput (Mbit/s) | 1.305 | 1.307 | 0.002 |
| bulk-cross | UDP loss (%) | 33.274 | 12.188 | -21.087 |
| bulk-cross | ping p95 RTT (ms) | 2653.000 | 2946.000 | 293.000 |
| bulk-cross | received throughput (Mbit/s) | 5.919 | 7.813 | 1.894 |

c2-north: 路由不同 0/160 帧；接收区间覆盖 159.000/160.000 秒与 159.000/160.000 秒。


telemetry-east: 路由不同 0/160 帧；接收区间覆盖 159.000/160.000 秒与 159.000/160.000 秒。


bulk-cross: 路由不同 139/160 帧；接收区间覆盖 159.001/160.000 秒与 159.001/160.000 秒。


本组达到预先定义的可见改善幅度：是。这不是三组重复性验收，也不是普遍优越性结论。

UDP 丢包按接收端有符号计数增量汇总，保留迟到包修正。RTT p95 由成功 ping 原始样本计算。阶段边界跨越的区间不分摊进当前窗口；最终累计报告中无法精确归属区间的尾部字节不补入阶段统计。

地图覆盖线表示 cell 级 SRv6 路由意图，不是逐卫星抓包轨迹。原始队列、路由、接口计数、流量日志均保存在 ZIP 中。

三份失败尝试 0db3736821654266b2a1e94062699ca4、d4dc989dec5543c999965d8851e7a021、a213412edab84fd4a42126029bb693f6 均保留，未混入这组汇总。