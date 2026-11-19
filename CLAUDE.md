# CLAUDE.md — Claude Code entry point

The shared, tool-neutral project instructions live in **`AGENTS.md`** (read by
other agent tools directly). This file imports them so Claude Code loads them,
then your per-machine residue. Add any Claude-Code-specific-only notes below.

@AGENTS.md

@CLAUDE.local.md

## Claude Code notes

- **No downstream details (AGENTS.md, "Public repository: no downstream
  details").** Before handing over any commit, release-note or PR text, check
  the staged diff and the message for downstream names, usage figures, rule or
  ADR numbers from other repos, local paths and kernel names.
  - This holds in sessions started from another repository too.
  - A showcase project may be named only after the maintainer has explicitly
    approved that specific mention in the conversation.
  - Never suggest `--no-verify` to get past the local denylist hook, except for
    such an approved mention.
