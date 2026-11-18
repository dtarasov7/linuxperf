# Network analysis

Network collection combines procfs TCP/UDP, interface counters, conntrack, softnet, socket memory/orphans, sysctls and SOCK_DIAG listen backlog. Ettool adds driver properties and counters when supported. Unsupported requests on virtual interfaces do not establish network failure.

A PID filter does not turn `/proc/PID/net` into per-process traffic: it reflects a network namespace. Native tcpretrans is system-wide and is not cgroup-filtered. Check event endpoints, units and PID provenance.

TIME_WAIT is often normal. CLOSE_WAIT, retransmits, drops and zero-window events need application and queue context. Network USE saturation is the TIME_WAIT+CLOSE_WAIT count, not a percentage. Two DNS events cannot establish a stable p99 or a timeout cascade.

```bash
python3 linuxperf.py collect --profile standard --focus network -o network.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `listen_queues`, `parse_sockstat`, `parse_ethtool`, `enrich`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/05-network-analysis.md)
