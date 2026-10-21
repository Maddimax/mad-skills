# Gerrit PRECHECK-and-submit bot

Watches your own changes in `qt-creator/qt-creator` on
codereview.qt-project.org. When one gets a Code-Review +2 it triggers a
PRECHECK, and when the PRECHECK passes it submits the change.

## What it does

1. Listens to `gerrit stream-events` (`comment-added`, `patchset-created`,
   `change-merged`) for changes you own in `qt-creator/qt-creator`.
2. A change that has a +2 on its **current** patch set, and is not WIP or
   private, gets a PRECHECK triggered once for that patch set, unless
   `qt_ci_bot` has already reported on that patch set: a passed run is
   reused, so the bot submits right away if Gerrit reports the change as
   submittable, and a run that is still in progress is waited for. A new
   run is started when the last one failed or there is none.
3. It then waits for a `qt_ci_bot` message for that patch set:
   - `Quick Check: Passed`: if Gerrit reports the change as submittable
     (a `submitRecords` entry with status `OK`, which also covers the +2
     still being there), it submits.
   - `Quick Check: Failed`: it sends a macOS notification and stops. It
     never retries.
4. If the +2 is withdrawn, or a new patch set arrives, it forgets the
   change and does not submit.

Events are only wake-up hints. Every decision is made from the change as
`gerrit query` reports it, so a missed event, a restart or a reconnect cannot
cause a wrong action. On startup, after every reconnect and every five
minutes while connected, the bot scans your open +2 changes with the same
logic, so a lost event is recovered within five minutes. Every SSH call
has a connect timeout, keepalives and a hard timeout, so a network change
cannot leave the bot waiting on a dead connection. The stream reconnects
with backoff, which resets after a connection has been up for a minute.

## Requirements

- Python 3, standard library only.
- SSH access to codereview.qt-project.org with the Stream Events
  capability. The bot runs as the user `ssh -G codereview.qt-project.org`
  reports. Queries, the event stream and the submit
  (`gerrit review --submit`) all go over SSH.
- `~/.gerrit` in git-config format with `http.user` and `http.pwd`, but
  only for triggering a PRECHECK, which is a plugin action reachable only
  through REST. The file is read when a PRECHECK is actually triggered,
  so a dry run needs no HTTP credentials.
- macOS for the notifications (`osascript`). Elsewhere they only appear
  in the log.

## Usage

Dry run, the default. It logs what it would do and posts nothing:

```bash
python3 -I precheck_submit_bot.py
```

Live, which triggers prechecks and submits changes:

```bash
python3 -I precheck_submit_bot.py --live
```

| Option | Meaning |
|---|---|
| `--live` | Really trigger prechecks and submit. Without it nothing is posted. |
| `--once` | Scan once and exit instead of streaming. |
| `--state FILE` | State file. Default `~/.gerrit-precheck-bot.json`. |

To check the decisions without any side effect, put a +2 on an open
change and run `--once` in dry-run mode. It should print
`DRY-RUN would trigger precheck`.

## Docker

Build the image:

```bash
docker build -t gerrit-precheck-bot .
```

The container needs an SSH key, the Gerrit host key and the user name.
The key must have no passphrase, because the bot connects in batch mode.
Get the host key from your own `known_hosts`, so nothing is trusted
blindly:

```bash
ssh-keygen -F '[codereview.qt-project.org]:29418' | grep -v '^#' >| known_hosts
```

Run it as a dry run, the default:

```bash
docker run -d --name gerrit-bot --restart unless-stopped \
  -e GERRIT_SSH_USER=<your Gerrit user> \
  -v ~/.ssh/id_ed25519:/run/secrets/gerrit_ssh_key:ro \
  -v "$PWD/known_hosts":/run/secrets/known_hosts:ro \
  -v gerrit-bot-data:/data \
  gerrit-precheck-bot
```

Add `--live` after the image name to really trigger prechecks and
submit. The HTTP credentials for the PRECHECK trigger go in
`-e GERRIT_HTTP_USER=... -e GERRIT_HTTP_PASSWORD=...` or in a mounted
`-v ~/.gerrit:/home/bot/.gerrit:ro`.

| Variable | Meaning |
|---|---|
| `GERRIT_SSH_USER` | Required. Gerrit SSH user name. |
| `GERRIT_SSH_KEY` | Key path in the container. Default `/run/secrets/gerrit_ssh_key`. |
| `GERRIT_KNOWN_HOSTS` | known_hosts path. Default `/run/secrets/known_hosts`. |
| `GERRIT_HTTP_USER`, `GERRIT_HTTP_PASSWORD` | HTTP credentials; otherwise `~/.gerrit` is read. |

The container runs as a non-root user and keeps its state in the `/data`
volume. Logs go to `docker logs`, with UTC timestamps. There is no
macOS notification in a container, so a failed PRECHECK or a change that
is not submittable shows up only as a `NOTIFY:` line in the log.

## Windows (scheduled task)

Docker Desktop on Windows only starts when a user logs in, so after a
reboot the container stays down. Running the script directly as a
scheduled task starts at boot without a login. Requirements: Python 3,
and Git for Windows for its `ssh`.

Do not use the OpenSSH client that ships with Windows: it hangs whenever
its output is a pipe, which is how the bot reads Gerrit's answers. The
`ssh` from Git for Windows works. The bot picks the executable and the
config from environment variables:

| Variable | Meaning |
|---|---|
| `GERRIT_SSH` | The ssh executable, for example `C:\Program Files\Git\usr\bin\ssh.exe`. Default `ssh`. |
| `GERRIT_SSH_CONFIG` | An ssh config file used instead of `~/.ssh/config`, with `User`, `Port`, `IdentityFile` and `UserKnownHostsFile`. |
| `GERRIT_CREDENTIALS_FILE` | The git-config style file with the HTTP credentials. Default `~/.gerrit`. |

A wrapper `.cmd` sets these and runs the script with `--live --state
<file>`, appending to a log. The task runs it as your user with the
logon type S4U (no stored password, no login needed) on a boot trigger,
restarting on failure. Keep the folder with the key and credentials
readable by your user only (`icacls <folder> /inheritance:r /grant:r
"<machine>\<user>:(OI)(CI)F"`).

## State

`~/.gerrit-precheck-bot.json` records, per change, the revision the
PRECHECK was triggered for, the last message that existed at the time,
and the outcome (`submitted`, `failed`, `not-submittable`). The recorded
message is what keeps an earlier PRECHECK result from being mistaken for
the one the bot asked for. Delete the file to make the bot trigger again
for changes that already have a +2.

## Known limits

- The PRECHECK request body is **unverified**. The bot sends
  `{"type": "default", "buildonly": false, "cherrypick": false}` to
  `gerrit-plugin-qt-workflow~precheck`, copied from the
  `Precheck requested with params ...` change message. If Gerrit rejects
  it, the error is logged and the bot tries again on the next event for
  that change. Watch the first live trigger.
- `gerrit review --submit` over SSH and your permission to submit in
  this project have not been tried. The bot submits only when Gerrit
  reports the change as submittable, and Qt's merge flow may add
  requirements beyond that.
- A passed PRECHECK that finished before the +2 is reused. It tested the
  change on the branch as it was then, so if the branch has moved since,
  only Gerrit's own submit checks stand between that and the merge.
- A PRECHECK takes about one to two hours. The bot does not poll, so it
  acts when the `qt_ci_bot` result arrives on the stream.
- Only `qt-creator/qt-creator` and changes owned by the account in
  `ssh -G` reports are handled. The project name is `PROJECT` at the top of
  the script.

## Tests

There is no test file in the repository. The decision logic was checked
with a fake Gerrit object over crafted changes (trigger, dry run, WIP,
other owner or project, withdrawn +2, stale or wrong-patch-set results,
failed and not-submittable results, new patch set), and the real
`gerrit query` output was checked against the fields the bot reads.
