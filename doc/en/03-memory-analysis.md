# Memory analysis

`memory_info` contains meminfo, vmstat, NUMA and THP data, enriched with PSI, buddyinfo, socket memory and sysctls. Main memory utilization uses MemAvailable rather than only MemFree.

`swap_usage` is allocated swap percentage, not swap I/O rate. Pressure needs supporting evidence such as PSI, direct reclaim, major faults and application behavior. Distinguish cumulative vmstat values from interval rates in `metrics`.

One RSS snapshot cannot prove a leak. Compare repeated equivalent windows and process rankings. Deep memleak tracing can be expensive; without PID it may trace kernel allocations. Its positional argument is a reporting interval; linuxperf bounds execution with a timer.

```bash
python3 linuxperf.py collect --focus memory --external-tools off --native-ebpf off -o memory.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `collect`, `restore_metrics`, `parse_sockstat`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/03-memory-analysis.md)
