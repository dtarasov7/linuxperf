# linuxperf: reading a partial report / Чтение неполного отчёта

This is a synthetic excerpt, not a measurement of a production server and not a complete input file for export/diff. The summary is calculated by the current diagnose() implementation from the five metrics shown. Missing metrics remain unknown. The health score describes measured inputs; it does not certify complete coverage.

Это синтетический фрагмент, не замер рабочего сервера и не полный файл для export/diff. Summary вычислен текущей diagnose() по пяти приведённым метрикам. Остальные значения неизвестны; оценка здоровья не доказывает полноту сбора.

```json
{
  "metadata": {
    "tool": "linuxperf",
    "schema_version": "linuxperf/1.0",
    "profile": "standard",
    "status": "partial"
  },
  "metrics": {
    "cpu_utilization": 20.0,
    "memory_utilization": 40.0,
    "disk_utilization": 2.0,
    "tcp_retransmits": 0.0,
    "swap_usage": 36.0
  },
  "summary": {
    "health_score": 83,
    "score_version": "linuxperf/use-2",
    "coverage": {
      "evaluated": 5,
      "selected": 37,
      "ratio": 0.13513513513513514,
      "categories": {
        "cpu": {
          "evaluated": 1,
          "selected": 5
        },
        "memory": {
          "evaluated": 2,
          "selected": 8
        },
        "network": {
          "evaluated": 1,
          "selected": 16
        },
        "disk": {
          "evaluated": 1,
          "selected": 5
        },
        "container": {
          "evaluated": 0,
          "selected": 2
        },
        "system": {
          "evaluated": 0,
          "selected": 1
        }
      }
    },
    "anomalies": [
      {
        "metric": "swap_usage",
        "category": "memory",
        "value": 36.0,
        "unit": "%",
        "threshold": 10.0,
        "severity": "warning"
      }
    ],
    "unchecked_rules": [
      "cpu_iowait",
      "load_average",
      "memory_psi_pressure",
      "direct_reclaim_rate",
      "compaction_stall_rate",
      "thp_split_rate",
      "numa_miss_ratio",
      "tcp_timewait",
      "cpu_throttling",
      "container_memory_usage",
      "biolatency_p99_ssd",
      "biolatency_p99_hdd",
      "runqlat_p99",
      "dns_latency_p99",
      "cache_miss_ratio",
      "cpu_psi_pressure",
      "io_psi_pressure",
      "disk_avg_latency",
      "network_errors_per_sec",
      "conntrack_usage_pct",
      "softnet_dropped",
      "listen_overflows",
      "nic_rx_discards",
      "tcp_close_wait",
      "softnet_time_squeeze",
      "tcp_abort_on_memory",
      "irq_imbalance",
      "udp_rcvbuf_errors",
      "tcp_rcvq_drop",
      "tcp_zero_window_drop",
      "listen_queue_saturation",
      "gpu_nic_cross_numa"
    ]
  }
}
```

Swap allocation at 36% does not prove active swapping. Memory utilization at 40% does not establish a leak. Check source windows, PSI, reclaim and application behavior before tuning. Missing latency histograms cannot justify a p99 claim or a specific disk bottleneck.

Занятый swap 36% не доказывает активный свопинг; память 40% не доказывает утечку. Проверяйте окна, PSI, reclaim и поведение приложения. Отсутствующая гистограмма не даёт основания вычислять p99 или объявлять конкретную причину дисковой задержки.

For a real report / Для реального отчёта:

```bash
python3 linuxperf.py collect --profile standard --ai-prompt -o report.json
python3 linuxperf.py export report.json --format html -o report.html
```

Attach report.json with the text of report.prompt.txt for model analysis. Inspect per-collector status/reason, metrics units, time_series and observer_overhead. Do not treat missing events, timeouts or truncated output as proof that no issue exists.

Передавайте модели report.json вместе с report.prompt.txt. Проверяйте status/reason каждого сборщика, единицы метрик, time_series и observer_overhead. Отсутствующие события, таймауты и усечённый вывод не доказывают отсутствие проблемы.

[Русское оглавление](ru/00-chapters.md) · [English contents](en/00-chapters.md) · [README](../README.md)
