#!/bin/sh
# Builds the SSH setup the bot needs from the environment, then runs it.
set -eu

: "${GERRIT_SSH_USER:?set GERRIT_SSH_USER to the Gerrit SSH user name}"
key=${GERRIT_SSH_KEY:-/run/secrets/gerrit_ssh_key}
known_hosts=${GERRIT_KNOWN_HOSTS:-/run/secrets/known_hosts}
for file in "$key" "$known_hosts"; do
    [ -r "$file" ] || { echo "cannot read $file" >&2; exit 1; }
done

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
install -m 600 "$key" "$HOME/.ssh/id"
install -m 644 "$known_hosts" "$HOME/.ssh/known_hosts"
cat >| "$HOME/.ssh/config" <<CONFIG
Host codereview.qt-project.org
  Port 29418
  User $GERRIT_SSH_USER
  IdentityFile $HOME/.ssh/id
  IdentitiesOnly yes
  PreferredAuthentications publickey
  StrictHostKeyChecking yes
  UserKnownHostsFile $HOME/.ssh/known_hosts
CONFIG

exec python3 -I -u /app/precheck_submit_bot.py "$@"
