# Comparing reports

Diff accepts two linuxperf/1.0 reports. It compares common metrics, USE values, device/interface measurements and available percentiles. Changes include comparable, reason, delta and percent_change.

Missing is not zero. Different units, methods, hosts or scope may prevent comparison. Changed boot identity, profile and score version are reported. Percentage change is undefined when the previous value is zero.

Anomalies_resolved excludes rules that simply became unevaluated; these appear in anomalies_unverified. Read coverage_before/after alongside regressions and improvements. Fewer anomalies caused by missing tools do not demonstrate performance improvement.

```bash
python3 linuxperf.py diff before.json after.json -o diff.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `load_report`, `diff_reports`, `compare_inventory`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/14-report-diffing.md)
