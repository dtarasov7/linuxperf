# Disk analysis

Diskstats yields per-device IOPS, bytes/s, mean latency, queue and busy time. Diskstats sectors are converted using 512 bytes, independently of physical sector size. Sysfs adds rotational state, scheduler, read-ahead and partition information.

Mean latency does not determine p99. Biolatency needs real nonempty buckets and known units; SSD/HDD rules also need device classification. Do not add partition, device-mapper and physical-device I/O as independent traffic. NVMe busy time does not express exhaustion of all parallel capacity.

An unsupported probe from biolatency/biosnoop is a missing kernel attachment point, not disk latency. Installing headers alone does not resolve it. Deep disk tracing shares the global deadline, so queued tools may receive shorter windows.

```bash
python3 linuxperf.py collect --profile deep --focus disk --max-workers 2 -o disk.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `collect`, `enrich`, `external_metrics`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/04-disk-analysis.md)
