# Security and publication policy

The assistant this repository documents can read private local files and connected accounts. Everything committed here has to be safe for anyone to read.

## Never commit

- `.env` files or API keys
- OAuth access or refresh tokens, or Google credential files
- Discord bot tokens, server IDs, channel IDs, or transcripts
- Personal memory, `SOUL.md`, private prompts, or session databases
- Logs with names, addresses, message content, or request payloads
- Calendar contents or any data returned from a real account
- Live cron definitions or private automation instructions
- Full production configuration files or home-directory paths

## Safe to publish

- Architecture diagrams without private addresses or identifiers
- Placeholder configuration examples
- Benchmark metrics, pass/fail results, and tool sequences
- Synthetic test fixtures and the harness code that uses them
- Redacted screenshots
- General troubleshooting lessons

If a secret is ever committed, revoke or rotate it right away. Deleting it in a later commit does not help, because Git history keeps the earlier version.
