# Output and export

Reports use linuxperf/1.0. Category results contain collector, backend, status, reason, data and scope, with source-specific extra fields. Status values are ok, partial, unavailable, skipped and error. Reports are capped at 32 MiB; file writes use temporary files and rename. NaN/Infinity are rejected.

Compact removes formatting whitespace without removing measurements. AI-prompt enables compact and writes instructions separately. Progress/summary use stderr, preserving JSON stdout for -o -. Quiet suppresses progress rather than errors.

HTML is a standalone page containing escaped JSON in pre, not a graphical card/chart dashboard. Folded/SVG need real positive stack samples. Select one collector when stack weight units differ. Flamegraph width represents weight, which is not necessarily CPU time.

```bash
python3 linuxperf.py export report.json --format html -o report.html
python3 linuxperf.py export report.json --format folded --collector profile -o cpu.folded
python3 linuxperf.py export report.json --format flamegraph --collector profile -o cpu.svg
```

Implementation: [linuxperf.py](../../linuxperf.py) — `write_json`, `write_text`, `export`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/16-output-formats.md)
