# Recommendations and validation

The engine has 35 recommendation conditions based on metrics, sysctls and device properties. Results include priority, type, evidence, commands, persistent settings, expected impact and source. Not all recommendations appear in every report.

Commands are text for operator review; collect does not execute them. Even a fix recommendation does not establish the cause of latency. Swappiness, THP, TCP buffers, backlog and I/O scheduler changes need workload context, resource limits and rollback.

Save the original value, change one factor, repeat comparable collection and inspect both coverage and measurements with diff. Persist changes after validation. Report suggestions are not a universal server-tuning script.

```bash
python3 linuxperf.py diff before.json after.json -o changes.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `generate_recommendations`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/12-recommendations.md)
