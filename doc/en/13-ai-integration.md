# AI prompt and MCP

`--ai-prompt -o report.json` writes report.prompt.txt next to automatically compact JSON. The saved JSON excludes ai_context to avoid duplicating instructions. Paste the prompt into your model chat and attach the full JSON. Stdout reports use report.prompt.txt in the current directory. Generation is local and neither invokes a model nor uploads data.

The prompt includes collection status/reasons, windows and CPU time for the program and children. Peak RSS covers the program itself. Stack/histogram hints require successful nonempty results. Its 27 hypotheses are an optional reference: do not enumerate them or equate a matching pattern with proof. Requested output is limited to 500 words and three likely problems with evidence, confidence and validation.

MCP uses stdio JSON-RPC protocol 2024-11-05. Tools are get_health, collect_metrics, list_anomalies and explain_anomaly. One collection worker runs at a time; cancellation and ping remain supported. Collect_metrics accepts profile/pid/focus rather than the full CLI. Configure clients with command=python3 and args=[absolute path to linuxperf.py, mcp].

```bash
python3 linuxperf.py collect --profile standard --ai-prompt -o report.json
python3 linuxperf.py mcp
```

Implementation: [linuxperf.py](../../linuxperf.py) — `build_ai_context`, `mcp`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/13-ai-integration.md)
