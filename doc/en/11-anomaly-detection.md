# Anomalies and health score

RULES defines 37 threshold rules; the table below comes from current code. Rules require measured values. Unknown rules appear in unchecked_rules, while demonstrably inapplicable rules appear in not_applicable_rules. Coverage counts evaluated applicable rules.

Health score requires baseline CPU/memory/disk/network data; partial_health_score only describes available data. The algorithm is linuxperf/use-2. USE penalties and anomaly penalties may both apply. This heuristic does not certify system health or collection quality.

Saturation units differ: CPU uses normalized excess load percent, memory allocated swap percent, disk in-flight count, network TIME_WAIT+CLOSE_WAIT count. Do not render every value as a percentage. Score comparisons require compatible algorithm versions, scope and coverage. Thresholds are implementation settings, not universal standards.

| Metric | Category | Warning | Critical | Unit |
|---|---|---:|---:|---|
| `cpu_utilization` | cpu | 80.0 | 95.0 | % |
| `cpu_iowait` | cpu | 10.0 | 30.0 | % |
| `load_average` | cpu | 2.0 | 4.0 | per_cpu |
| `memory_utilization` | memory | 85.0 | 95.0 | % |
| `swap_usage` | memory | 10.0 | 50.0 | % |
| `memory_psi_pressure` | memory | 5.0 | 25.0 | % |
| `direct_reclaim_rate` | memory | 10.0 | 1000.0 | pages/s |
| `compaction_stall_rate` | memory | 1.0 | 100.0 | /s |
| `thp_split_rate` | memory | 1.0 | 100.0 | /s |
| `numa_miss_ratio` | memory | 5.0 | 20.0 | % |
| `tcp_retransmits` | network | 10.0 | 50.0 | /s |
| `tcp_timewait` | network | 5000.0 | 20000.0 | sockets |
| `disk_utilization` | disk | 70.0 | 90.0 | % |
| `cpu_throttling` | container | 100.0 | 1000.0 | periods |
| `container_memory_usage` | container | 80.0 | 95.0 | % |
| `biolatency_p99_ssd` | disk | 5.0 | 25.0 | ms |
| `biolatency_p99_hdd` | disk | 50.0 | 200.0 | ms |
| `runqlat_p99` | cpu | 10.0 | 50.0 | ms |
| `dns_latency_p99` | network | 50.0 | 200.0 | ms |
| `cache_miss_ratio` | memory | 5.0 | 15.0 | % |
| `cpu_psi_pressure` | cpu | 5.0 | 25.0 | % |
| `io_psi_pressure` | disk | 10.0 | 50.0 | % |
| `disk_avg_latency` | disk | 5.0 | 50.0 | ms |
| `network_errors_per_sec` | network | 10.0 | 100.0 | /s |
| `conntrack_usage_pct` | network | 70.0 | 90.0 | % |
| `softnet_dropped` | network | 1.0 | 100.0 | /s |
| `listen_overflows` | network | 1.0 | 100.0 | /s |
| `nic_rx_discards` | network | 100.0 | 10000.0 | packets |
| `tcp_close_wait` | network | 1.0 | 100.0 | sockets |
| `softnet_time_squeeze` | network | 1.0 | 100.0 | /s |
| `tcp_abort_on_memory` | network | 0.1 | 1.0 | /s |
| `irq_imbalance` | network | 5.0 | 20.0 | ratio |
| `udp_rcvbuf_errors` | network | 1.0 | 100.0 | /s |
| `tcp_rcvq_drop` | network | 1.0 | 100.0 | /s |
| `tcp_zero_window_drop` | network | 1.0 | 50.0 | /s |
| `listen_queue_saturation` | network | 70.0 | 90.0 | % |
| `gpu_nic_cross_numa` | system | 1.0 | 1.0 | pairs |

Implementation: [linuxperf.py](../../linuxperf.py) — `diagnose`, `health_score`, `use_metrics`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/11-anomaly-detection.md)
