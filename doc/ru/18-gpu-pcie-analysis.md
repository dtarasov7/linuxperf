# GPU, PCIe и NUMA

GPU/NIC inventory использует sysfs PCI class, bus addresses и NUMA node. При наличии nvidia-smi и работающего NVIDIA GPU добавляются utilization, VRAM, driver, температура и питание. Отсутствующий nvidia-smi на VM без GPU не является поломкой CPU/RAM-диагностики.

`gpu_nic_cross_numa` — топологический признак, а не измерение скорости DMA, RDMA или времени cudaMemcpy. Неизвестный NUMA node не превращается в доказанное несовпадение. Для выводов нужен реальный путь данных приложения: CPU affinity, память, GPU и выбранный NIC.

Linuxperf не переставляет PCIe-устройства, не устанавливает драйвер при collect и не выполняет GPUDirect-тесты. Настройки привязки и драйверов проверяются отдельно с возможностью отката. Capabilities и конкретные статусы важнее наличия раздела GPU в JSON.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off -o topology.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `collect`, `restore_metrics`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/18-gpu-pcie-analysis.md)
