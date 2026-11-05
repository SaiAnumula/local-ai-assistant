# Results

Sanitized output from benchmark and harness runs. Each dated folder has its own README describing the files.

| Folder | Hardware | Contents |
|---|---|---|
| [`2026-11-03-24gb/`](2026-11-03-24gb/) | i5-13600KF, RX 9070 16 GB, 24 GB DDR4 | Throughput CSVs, synthetic checks, Hermes agent-loop results, and production fit for the 24 GB retune |

`results/raw/` is the default output folder for the harness scripts and is git-ignored.

Before committing a result:

- Keep timing metrics, pass/fail results, and tool sequences only.
- Remove filesystem paths, usernames, process IDs, and anything from a real account.
- Do not add prompts, generated responses, tokens, or private configuration.
