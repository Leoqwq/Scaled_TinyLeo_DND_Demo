# Receiver parser fixture

`iperf320-receiver.jsonl` is a reduced real iperf3 3.20 receiver capture
from a two-second, 1 Mbit/s, 1000-byte UDP host-loopback probe on the
development Mac. The original receiver byte, packet, interval and clock fields
are preserved; unrelated metadata was removed.

This tests JSON parsing and timestamp alignment, not satellite performance.
The end-event receiver totals come from `sum_received`, not `sum`.
Browser Compare fixtures are synthetic contract tests and must not be used
as demonstration evidence of a QoS advantage.
