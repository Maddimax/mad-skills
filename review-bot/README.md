# review-bot

A scheduled Claude Code task that works through the Gerrit changes waiting for
me (codereview.qt-project.org): it triages them, lets the Qt Code Review bot
review other people's changes, gives +2 when the bot review and a PRECHECK are
clean, and has a subagent fix my own changes (review findings, merge
conflicts).

- `SKILL.md` - the scheduled task prompt (`~/.claude/scheduled-tasks/<name>/SKILL.md`).
- `gerrit-attention-report.py` - read-only report the task runs first
  (`~/.claude/scripts/`). Needs `~/.gerrit` (git-config format, `http.user`
  and `http.pwd`).

## The script

```bash
python3 -I gerrit-attention-report.py                   # compact: 2 lines per change
python3 -I gerrit-attention-report.py --full --only 123 456   # details for chosen changes
python3 -I gerrit-attention-report.py --json            # machine readable
python3 -I gerrit-attention-report.py --all             # include my stale/WIP changes
python3 -I gerrit-attention-report.py --patch 123       # diff of the current patch set
python3 -I gerrit-attention-report.py --start-bot 123   # start the bot once per patch set
```

It fetches in parallel (about 6-10 s) everything needed per change: bot state
for the current patch set (a +1/-1 copied over a rebase counts), precheck
state, `mergeable` (only available per change over REST; `is:mergeable` is not
supported on this host), open parents/children, unresolved threads with the
`reply_to` id, attention reasons, votes, bot jobs, and an action hint
(`READY_FOR_PLUS2`, `NEEDS_BOT`, `CONFLICT`, ...). Only `--start-bot` writes.

Why the conflict check is separate from the attention set: a merge conflict
does not put you in the attention set, and with the cherry-pick submit type a
change stacked on an unmerged parent reads `mergeable: false` until the parent
merges, without a conflict to fix.

## Cost analysis

Both variants ran as read-only dry runs (`claude -p --model sonnet
--output-format json`) at the same time against the same Gerrit state, 23
changes. Cost is `total_cost_usd` from each run's result.

| | Freeform (MCP and `gerrit-api.sh` calls) | Script |
|---|---|---|
| Cost | $0.527 | $0.264 |
| Turns | 40 | 3 |
| Wall time | 54 s | 30 s |
| Cache-read input tokens | 595k | 89k |
| Cache-creation input tokens | 98k | 58k |
| Output tokens | 7.6k | 2.3k |

The script halves the cost. Most of the gap is the turn count: every turn
re-reads the whole conversation, so 40 turns read about 6.7 times as much
cached context as 3 turns. Output sizes: compact report 4.6 KB (about 1.2k
tokens), `--full` for all 23 changes 75 KB (about 19k tokens), `--full --only`
for two changes 5.5 KB. So the task runs the compact view first and asks for
`--full` only on changes it must act on.

The script run also decided better: it counted the bot +1 that Gerrit copied
over a trivial rebase (the freeform run wanted to start the bot again on three
such changes), found a real conflict the freeform run never listed, and kept
the stacked changes waiting for a recheck after a stack rebase.

Caveats: one run of each, Sonnet only, slightly different prompts (the
freeform prompt is a reconstruction of the original reading steps), and dry
runs, so subagent and push costs are not included (they are the same for both).
