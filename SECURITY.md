# Security and publication policy

This repository documents a personal assistant that can access private local and connected-service data. Public commits must remain sanitized.

## Never commit

- `.env` files or API keys
- OAuth access or refresh tokens
- Google credential or token files
- Discord bot tokens, server IDs, channel IDs, or private transcripts
- Personal memory, `SOUL.md`, private prompts, or session databases
- Logs containing names, addresses, message content, or request payloads
- Live cron definitions or private automation instructions
- Full production configuration files

## Safe to publish

- Architecture diagrams without private addresses or identifiers
- Placeholder configuration examples
- Aggregate benchmark results
- Synthetic reliability scenarios
- Redacted screenshots
- General troubleshooting lessons

If a secret is committed, revoke or rotate it immediately. Removing it in a later commit is not sufficient because Git history retains earlier versions.

