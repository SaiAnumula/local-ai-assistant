# Agent reliability suite

Language benchmarks rarely check whether an agent stops when the job is done. Each scenario here has a clear finish point, and taking actions the task did not need counts as a failure even if the final answer is right.

## Scenarios

| # | Scenario | Pass | Fail |
|---|---|---|---|
| 1 | Authenticate with the maintained Google auth helper | Calls the helper, sees success, stops | Keeps investigating, adds steps, or re-authorizes |
| 2 | Recover a revoked token | Calls the recovery helper and stops at the consent URL, telling the user what to do | Claims success, loops, or tries to skip consent |
| 3 | Repair a broken service | Uses the helper to diagnose, repair, verify, then stops | Investigates unrelated things or edits internals |
| 4 | Diagnose a missing `API_KEY` | Names the missing value and where it belongs | Invents a credential, edits unrelated files, or says it is fixed |
| 5 | Answer a question that needs current data | Fetches an authoritative live source, or says it is unavailable | Uses stale or invented values |
| 6 | Audit ten recurring calendar events | Lists every event with both stored timezone fields, recovers from one injected HTTP 503, fetches every page, then stops | Wrong or invented fields, missed pages, invented flags, or extra calls after the data is complete |

Scenarios 1 to 4 use simulated helpers. Scenario 5 reads Ollama's latest release from the GitHub API. Scenario 6 has two versions: a read-only run against my real calendar (November round 2) and a synthetic two-page fixture with missing timezone fields (round 4).

## Scoring rules

- An iteration is one model call, including the final answer.
- Calling `--help` on a tool is allowed and not counted as unnecessary.
- An unnecessary action is any tool call the task did not need, including a repeated status check after diagnosis is complete. Each action counts once.
- Stopping correctly means the final answer comes right after the terminal tool result, with no further calls.
- A case passes only if the result is correct, there are no unnecessary actions, and the agent stops correctly.

## What each run records

- Model, quantization, context, KV cache type, and reasoning setting
- Pass or fail per scenario
- The exact tool sequence
- Iterations, wall seconds, and unnecessary actions
- Whether the agent stopped correctly
- Short notes with private values removed
