# Model evaluation notes

These results came from hands-on experiments on an Intel Core i5-13600KF system with 32 GB DDR4 and an AMD Radeon RX 9070 with 16 GB VRAM.

## Observed results

| Model | Quantization or configuration | Observed decode speed | Context note |
|---|---|---:|---|
| `ornith-1.5:9b` | Q4_K_M | ~77 tok/s in an Ollama CLI test; ~90 tok/s in short API tests | Model advertises up to 262K; assistant configuration varied by test |
| `gemma4:12b` | Local Ollama build | 56.14 tok/s | Tested at a 64K model context |
| `gemma4:26b` | A4B | 44.91 tok/s | Tested at a 64K model context |
| `qwen3:30b-a3b-instruct-2507` | Q4_K_M | 29.78 tok/s | Mixture-of-experts model |
| `qwen3.8:27b` | Q3_K_XL, 32K configuration | 15.39 tok/s | Partial CPU offload |
| `qwen3.8:27b` | Q3_K_M, 131K configuration | 6.28 tok/s | Greater CPU involvement and larger allocation |

## Interpretation

- Decode speed alone does not determine assistant quality.
- Tool adherence, stop behavior, context handling, and vision support are evaluated separately.
- Models that spill substantially into system memory can fit while still producing an uncomfortably slow experience.
- Results from different prompts and context allocations should not be treated as a controlled head-to-head benchmark.

## Planned controlled methodology

Future measurements will hold these variables constant:

- Prompt and target response
- Context allocation
- Quantization family
- Warm versus cold model state
- Number of repetitions
- Prompt-processing and decode measurements
- GPU/CPU allocation
- Hermes tool schema and system-prompt size

