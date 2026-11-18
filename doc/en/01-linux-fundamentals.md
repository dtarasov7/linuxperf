# Linux sources and measurement windows

`/proc/stat` supplies CPU counters, `/proc/meminfo` memory gauges, `/proc/vmstat` VM events, `/proc/diskstats` I/O, and `/proc/net/dev` plus SNMP network counters. Sysfs supplies device, NUMA and PCI properties. Cgroup v1/v2 adds limits and group statistics.

Rates use counter differences divided by actual snapshot elapsed time. Counter decreases, changed boot identity or a reused PID must not become positive rates. CPU tick frequency and page size come from sysconf; do not assume a fixed page size.

PSI measures stall time. Load includes more than runnable CPU demand. Allocated swap and historical NUMA misses do not establish current stalls. Consult `metric_specs` for units, method and scope; a container may expose host-wide counters.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off --duration 10s -o baseline.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `snapshot`, `delta`, `pairs`, `metric_spec`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/01-linux-fundamentals.md)
