# Production validation checklist

Define the symptom, timing, PID/cgroup and diagnostic load budget before collection. Start with external-tools off and native-ebpf off. Check coverage and permissions, then enable a relevant tracing category if needed.

Use comparable profiles, windows, scope and workload. Observe the diagnostic CPU/memory cost. Two deep workers cannot provide every tool a full window; 32 workers on two vCPUs can cause compiler contention. More concurrency does not repair BCC compatibility or parsing errors.

Keep the baseline. Select one supported hypothesis, a validation plan, the original setting and rollback. Repeat collection and diff after a change, checking application latency and errors too. Do not blindly apply all recommendations: they do not establish every setting's suitability for the workload.

Reports may contain hostnames, PIDs, paths and addresses. Review data before explicit sharing. Collection itself does not upload anything.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off -o before.json
python3 linuxperf.py collect --external-tools off --native-ebpf off -o after.json
python3 linuxperf.py diff before.json after.json -o comparison.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `collect`, `diff_reports`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/21-production-checklist.md)
