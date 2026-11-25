---
name: review-attentionsetself
description: Review all waiting review Requests.
---

Use the `codereview` MCP server (tools `mcp__codereview__gerrit_*`) for all
Gerrit access. If its tools are not loaded, load them with ToolSearch. If it
needs authorization, stop and tell me to run /mcp; do not fall back to SSH or
curl with the credentials in ~/.gerrit; the only REST access is through
`~/.claude/scripts/gerrit-attention-report.py`, which reads them itself.

FIRST run `python3 -I ~/.claude/scripts/gerrit-attention-report.py`
(compact: two lines per change, read-only, ~10 s), then
`... --full --only <n> [<n>...]` ONLY for the changes you must act on in detail
(fixes, conflicts, unresolved threads, failed precheck); changes that are
READY_FOR_PLUS2, NEEDS_BOT or waiting need no more detail.
It is the only place to READ Gerrit state: do not call
`gerrit_query_changes`, `gerrit_get_reviews` or `gerrit_get_change` to look at
changes it already reports. For every open change that is in my attention set or
owned by me (my WIP and >21-day-old changes are skipped unless in my attention
set; `--all` shows them) it prints: bot state for the current patch set, precheck
state (and the failure text), mergeable (the REST endpoint, the only source),
open parents/children, attention reasons, votes, commit message, files,
unresolved threads with their full text and the `reply_to` id, recent change
messages, bot jobs, and an action hint (READY_FOR_PLUS2, NEEDS_BOT,
NEEDS_PRECHECK, CONFLICT, FIXES-REQUESTED, ...). Verify a hint before voting or
pushing. Other options:
- `--json` the same as JSON.
- `--patch <n>` the unified diff of the current patch set (only when you must
  read code; for mine, the fix subagent reads code itself).
- `--start-bot <n> [<n>...]` starts the Qt Code Review bot on the current patch
  set with the detected guidance. It refuses when a job already exists for that
  patch set, so it is safe to call; it is the only way the bot is started.
If one of my changes has an unresolved thread whose last comment is mine (I
replied and wait for the reviewer), it needs no fix: list it as waiting.
Re-run the script (without `--full`) at the end of the run: the attention set is
a snapshot and comments such as "rebase?" arrive meanwhile.

The MCP (`mcp__codereview__gerrit_*`) is for WRITES only: `gerrit_post_review`
(votes, replies with `reply_to` from the script, `resolve`), `gerrit_precheck`,
`gerrit_draft_comments`. Use `gerrit_get_reviews unresolved_only` only to verify
a reply landed, and `gerrit_ci_*` only to dig into a failed CI run.

The MCP account may vote +2 on Code-Review (`gerrit_post_review` `labels`).
If a vote is refused because of the account's limits, do not work around it
with REST or SSH; report the change as ready for my +2 instead.

If a change is owned by me and asks for fixes, start an Opus 5.5 - Medium
subagent to create the fix. When fixed and pushed (git push, as before),
answer the comments with `gerrit_post_review` `replies` (using each thread's
`reply_to`, `resolve: true` for those you fixed). Copy a parent's `range`
only if the tool asks for it; verify afterwards with `gerrit_get_reviews`
`unresolved_only`. Re-trigger the Qt Code Review bot afterwards.

If one of my changes is blocked due to a merge conflict, fix the conflict and
push. Trigger the Qt Code Review bot afterwards.

Conflicts do not put me in the attention set; the script checks `mergeable`
on all my open changes. Treat `mergeable: false` as a conflict, except: the
submit type is cherry-pick, so Gerrit tests each change alone against the target
branch, and a change stacked on an unmerged parent (open_parents in the script)
that touches files its parent adds reads `mergeable: false` until the parent
merges. Check with `git range-diff` after rebasing the whole stack onto the
branch tip: if all patches come out unchanged, there is no conflict to fix;
push nothing and list it in the report as waiting on its parent.

If they are not mine, do not review them yourself. Use the Qt Code Review bot
instead. There is no MCP tool for it; start it with
`gerrit-attention-report.py --start-bot <n>` (at most once per patch set; it
never re-requests a queued, running or finished one). A bot review exists when
the script shows bot=clean, findings or reviewed for the current patch set.
A Qt Review Bot +1/-1 that Gerrit copied over a trivial rebase counts as the
bot's verdict for the new patch set (the script reports it as clean/findings);
do not start the bot again for it. Do not post your own findings. If the bot's review of the latest
patch set has no unresolved findings (QtReviewBot Code-Review+1), list the
change, give it Code-Review +2. Otherwise leave it alone and list it in the
report.

Only give +2 when a PRECHECK has also run successfully
on the latest patch set (the script's precheck field).
If none was requested for that patch set, request one once with
`gerrit_precheck` and hold the +2; if it is pending or failed, do not
re-request it and do not +2, just list it in the report.

If a change (mine or someone else's) would benefit from a human trying it
out, for example a visible UI or behaviour change that the bot cannot judge,
ask me for a manual check. First prepare a local build of that change's latest
patch set, then create any necessary test files / projects I need to test it.
Then ask me with a question whether I want to start the test, saying what to
try. Only when I answer yes, launch the built application for me. Wait until
that process has exited, then ask me for my opinion of the change. Do not vote
or comment on the change based on a manual test until I have answered.

And finally, if you need to run a local test, use your own Windows and Linux
build machines (configure their hosts and checkout paths here).

## Permissions

You are allowed to execute git, build the necessary projects, and read/write
to gerrit through the codereview MCP server (comments, replies, resolving
threads, precheck, votes including +2).
