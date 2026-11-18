# Interpreting NUMA data

Memory_info contains NUMA node memory and numastat, enriched with distance, CPU lists and available balancing/reclaim settings. PCI topology maps GPU/NIC devices to NUMA nodes. These sysfs sources depend on hardware.

Numa_miss_ratio is derived from historical allocation counters. It is not a measurement of remote CPU memory references or current memory latency. A high cumulative ratio warrants placement investigation; a low ratio does not guarantee optimal affinity.

A single-node machine should not trigger an inter-socket hypothesis. Pinning, interleave, zone_reclaim_mode and balancing changes can hurt other workloads. First identify actual CPU/memory placement, then compare repeatable workload behavior before and after one change. Linuxperf does not automatically optimize NUMA placement.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off --focus memory -o numa.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `restore_metrics`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/20-numa-optimization.md)
