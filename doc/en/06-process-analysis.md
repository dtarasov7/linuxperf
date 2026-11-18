# Process analysis

`process_info.data` contains `top_by_cpu`, `top_by_memory` and `top_by_io`. Available values include PID, comm, CPU%, RSS, memory%, I/O rates, threads and fd_count. `--top` defaults to 20 rows.

CPU and I/O deltas compare process starttime to avoid interpreting PID reuse as activity. Processes can exit during sampling; missing values are not zero activity. Hidepid and permissions reduce coverage.

ObserverTracker excludes known collector and descendant PIDs from available process/event data. This does not remove their cost from system-wide counters or stacks. Distinguish BCC process names from application workloads.

```bash
python3 linuxperf.py collect --pid 12345 --top 10 --profile standard -o process.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `proc_stat`, `snapshot`, `enrich`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/06-process-analysis.md)
