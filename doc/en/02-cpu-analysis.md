# CPU analysis

`cpu_utilization` uses `/proc/stat` deltas. Per-core states, steal, iowait, IRQ, context switches, load and PSI provide context. Process and host CPU percentages use different denominators: a process may exceed 100% across cores.

When tracing is enabled, primary CPU metrics use the clean baseline before BCC starts. Later samples are in `time_series` with `observer_active=true`. Low baseline CPU can coexist with full utilization during BPF compilation. Inspect baseline and observed window lengths, sample count and observer overhead.

Runqlat measures scheduler waiting and cpudist CPU execution duration. Partial histograms or unknown units limit interpretation. Neither load nor a high p99 alone proves a single-thread bottleneck. Compare against a separate baseline run.

```bash
python3 linuxperf.py collect --profile standard --focus cpu --max-workers 2 -o cpu.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `snapshot`, `collect`, `sample_summary`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/02-cpu-analysis.md)
