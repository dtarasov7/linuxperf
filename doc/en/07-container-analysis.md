# PID and cgroup scope

`--cgroup` selects an existing cgroup path with mount-root and membership resolution. Both v1/v2 are supported for quota, cpuset, memory, memory events, throttling and available I/O counters. A combined PID/cgroup selection must have matching membership.

Host CPU count differs from container quota. The primary `cpu_throttling` rule uses cumulative throttled periods; interval rates, period percentage and throttled seconds/s are separate cgroup fields. Do not interpret a lifetime counter as a current stall fraction. Current `container_cpu_utilization` derives from throttled time/quota, not ordinary CPU execution utilization.

Cgroup selection limits process data but not every external trace; results record filter limitations. Native tcpretrans is not cgroup-filtered. Network-namespace statistics and some procfs sources may describe the host. Inspect each result's scope.

```bash
python3 linuxperf.py collect --cgroup /sys/fs/cgroup/example.service --profile quick -o cgroup.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `resolve_cgroup`, `cgroup_sources`, `cgroup_snapshot`, `enrich`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/07-container-analysis.md)
