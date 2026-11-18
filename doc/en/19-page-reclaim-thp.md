# Reclaim, compaction and THP

Collection uses vmstat, PSI, buddyinfo, sysctls and transparent_hugepage sysfs policy. Direct_reclaim_rate, compaction_stall_rate and thp_split_rate use counter deltas when both snapshots exist. Raw pgscan/pgsteal values can remain historical counters.

Direct reclaim indicates reclamation on an allocation path, but assessing latency needs PSI and workload observations. Compaction and THP splits are not equivalent to exhausted RAM. A sysfs THP policy alone does not prove stalls.

Start with a clean baseline and correlate memory PSI, reclaim and I/O windows. There is no universal swappiness, watermark or THP setting for every workload. Linuxperf emits recommendations as text; it does not apply sysctls or systemd units.

```bash
python3 linuxperf.py collect --focus memory --external-tools off --native-ebpf off --duration 30s -o reclaim.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `collect`, `restore_metrics`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/19-page-reclaim-thp.md)
