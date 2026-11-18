# System and filesystems

`system_info` includes OS/kernel details, uptime, boot parameters, block-device inventory and local filesystems. Sysfs data depends on namespaces, permissions and hardware. Dmesg is a separate external command; disabling it does not disable basic system inventory.

Local statvfs queries use bounded worker processes with timeouts. Network/autofs mounts are not queried through this path. External-tools off does not disable these built-in workers; they are not third-party diagnostic commands.

System and GPU inventory finish during report assembly, not necessarily in the clean baseline interval. Inspect start/end timestamps and source errors. A present key alone does not guarantee a valid measurement.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off -o system.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `filesystems`, `filesystem_worker`, `restore_metrics`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/08-system-collector.md)
