# GPU, PCIe and NUMA

GPU/NIC inventory uses PCI class, bus addresses and NUMA nodes from sysfs. A working NVIDIA GPU and nvidia-smi add utilization, VRAM, driver, temperature and power values. Missing nvidia-smi on a VM without a GPU does not invalidate CPU/memory diagnosis.

Gpu_nic_cross_numa is a topology indicator rather than a DMA/RDMA/cudaMemcpy performance measurement. Unknown NUMA placement does not prove a mismatch. Interpretation requires the actual application data path: CPU affinity, memory, GPU and chosen NIC.

Collect does not move PCIe devices, install drivers or run GPUDirect benchmarks. Validate affinity/driver changes separately with rollback. Availability and individual statuses matter more than a GPU section existing in JSON.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off -o topology.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `collect`, `restore_metrics`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/18-gpu-pcie-analysis.md)
