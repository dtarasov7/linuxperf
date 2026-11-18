# Quick start

Run these commands from the project root on Linux with Python 3.8+. The first collection disables both external tools and native eBPF. Basic collection does not require root, although permissions can restrict process and kernel data.

Quick selects four tracers and a 10 s window; standard selects a different small set and 30 s; deep selects the entire catalog and 60 s. External tools and native eBPF default to auto. Two external/native collectors share a queue by default. Many workers may saturate CPUs with BCC compilation.

JSON goes to the output file or stdout; progress goes to stderr. Use `-q` to suppress progress. Inspect `metadata.status`, `summary.coverage`, `source_errors` and category statuses. Partial collection can still contain useful measurements.

With `--ai-prompt`, the JSON becomes compact and a separate `.prompt.txt` is created. Paste that instruction into your model chat and attach the JSON. Export HTML or compare reports afterwards.

```bash
python3 linuxperf.py collect --profile quick --external-tools off --native-ebpf off -o baseline.json
python3 linuxperf.py collect --profile standard --ai-prompt -o report.json
python3 linuxperf.py export report.json --format html -o report.html
python3 linuxperf.py diff baseline.json report.json -o diff.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `parser`, `prepare`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/00-quickstart.md)
