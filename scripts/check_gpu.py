"""Verificação da GPU para o Kronos (Fase 4). Requer PyTorch instalado (requirements-gpu.txt).

Uso:
    python scripts/check_gpu.py
"""
from __future__ import annotations

import time


def main() -> int:
    try:
        import torch
    except ImportError:
        print("PyTorch não está instalado. Veja as instruções em requirements-gpu.txt.")
        return 1

    print(f"PyTorch {torch.__version__}")
    if not torch.cuda.is_available():
        print("CUDA indisponível: o PyTorch instalado não enxerga a GPU."
              " Reinstale com a versão CUDA indicada no site do PyTorch.")
        return 2

    dev = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(dev)
    free, total = torch.cuda.mem_get_info(dev)
    print(f"GPU: {props.name}")
    print(f"VRAM total: {total / 2**30:.2f} GB; livre agora: {free / 2**30:.2f} GB")
    print(f"CUDA do PyTorch: {torch.version.cuda}")

    # Teste rápido de desempenho: multiplicação de matrizes 4096 x 4096 em float16.
    a = torch.randn(4096, 4096, device=dev, dtype=torch.float16)
    b = torch.randn(4096, 4096, device=dev, dtype=torch.float16)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(20):
        a @ b
    torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    tflops = 20 * 2 * 4096**3 / dt / 1e12
    print(f"Teste de multiplicação: {tflops:.1f} TFLOPS (float16)")
    print(f"Memória máxima usada no teste: {torch.cuda.max_memory_allocated(dev) / 2**20:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
