#!/usr/bin/env python3
"""Trigger PRECHECK on own qt-creator changes that get a +2, then submit.

Events from `gerrit stream-events` are only wake-up hints. Every decision
is made by `reconcile()` from the change as `gerrit query` reports it, so
a missed event, a restart or a reconnect cannot cause a wrong action: the
scan on (re)connect runs the same code.

Everything goes over SSH except the PRECHECK trigger, which is a plugin
action reachable only through REST and so needs the HTTP credentials in
~/.gerrit. They are read when a PRECHECK is actually triggered.

Without --live nothing is posted: the bot only logs what it would do.
"""
import argparse
import base64
import json
import logging
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HOST = "codereview.qt-project.org"
PROJECT = "qt-creator/qt-creator"
CI_BOT = "qt_ci_bot"
RESCAN_SECONDS = 300
SSH_TIMEOUT = 120
SSH_OPTIONS = ["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]
PRECHECK_ACTION = "gerrit-plugin-qt-workflow~precheck"
# Unverified: mirrors the "Precheck requested with params ..." message.
PRECHECK_BODY = {"type": "default", "buildonly": False, "cherrypick": False}

log = logging.getLogger("precheck-bot")


class Gerrit:
    def __init__(self):
        for line in subprocess.check_output(["ssh", "-G", HOST],
                                            text=True).splitlines():
            if line.startswith("user "):
                self.username = line.split(None, 1)[1]

    def ssh(self, *args):
        return subprocess.run(
            ["ssh", *SSH_OPTIONS, HOST, "gerrit", *args], capture_output=True,
            text=True, check=True, timeout=SSH_TIMEOUT).stdout

    def query(self, q):
        out = self.ssh("query", "--format=JSON", "--current-patch-set",
                       "--comments", "--submit-records", shlex.quote(q))
        rows = [json.loads(line) for line in out.splitlines()]
        return [r for r in rows if r.get("type") != "stats"]

    def submit(self, number, patchset):
        self.ssh("review", "--submit", f"{number},{patchset}")

    def precheck(self, number, revision):
        def cfg(key):
            return subprocess.check_output(
                ["git", "config", "-f", os.path.expanduser("~/.gerrit"), key],
                text=True).strip()
        token = base64.b64encode(
            f"{cfg('http.user')}:{cfg('http.pwd')}".encode()).decode()
        req = urllib.request.Request(
            f"https://{HOST}/a/changes/{number}/revisions/{revision}/"
            f"{PRECHECK_ACTION}",
            data=json.dumps(PRECHECK_BODY).encode(), method="POST",
            headers={"Authorization": "Basic " + token,
                     "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).close()


def notify(text):
    log.warning("NOTIFY: %s", text)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e",
                    f'display notification "{escaped}" with title "Gerrit bot"'],
                   check=False)


def ci_result(comments, after, ps):
    result = None
    for c in comments[after:]:
        text = c["message"]
        if (c["reviewer"].get("username") == CI_BOT
                and text.startswith(f"Patch Set {ps}:")):
            if "Quick Check: Passed" in text:
                result = "passed"
            elif "Quick Check: Failed" in text:
                result = "failed"
    return result


def reconcile(g, state, n, live):
    key = str(n)
    found = g.query(f"change:{n}")
    c = found[0] if found else None
    if (not c or c["project"] != PROJECT or not c["open"]
            or c["owner"]["username"] != g.username):
        state.pop(key, None)
        return
    if c.get("wip") or c.get("private"):
        return

    patchset = c["currentPatchSet"]
    rev = patchset["revision"]
    ps = patchset["number"]
    if not any(a["type"] == "Code-Review" and a["value"] == "2"
               for a in patchset.get("approvals", [])):
        if state.pop(key, None):
            log.info("%s: +2 gone, cancelling", n)
        return

    s = state.get(key)
    if s is None or s["revision"] != rev:
        if not live:
            log.info("%s ps%s: DRY-RUN would trigger precheck", n, ps)
            return
        after = len(c["comments"])
        g.precheck(n, rev)
        state[key] = {"revision": rev, "ps": ps, "after": after, "done": None}
        log.info("%s ps%s: precheck triggered", n, ps)
        return
    if s["done"]:
        return

    result = ci_result(c["comments"], s["after"], ps)
    if result is None:
        return
    if result == "failed":
        s["done"] = "failed"
        notify(f"{n} ps{ps}: precheck failed, not submitting")
        return
    if not any(r["status"] == "OK" for r in c.get("submitRecords", [])):
        s["done"] = "not-submittable"
        notify(f"{n} ps{ps}: precheck passed but change is not submittable")
        return
    if not live:
        log.info("%s ps%s: DRY-RUN would submit", n, ps)
        return
    g.submit(n, ps)
    s["done"] = "submitted"
    notify(f"{n} ps{ps}: submitted")


def scan(g, state, live):
    q = f"owner:self project:{PROJECT} status:open label:Code-Review=2"
    numbers = {c["number"] for c in g.query(q)}
    numbers |= {int(k) for k in state}
    log.info("scan: %s change(s) to check", sorted(numbers) or "no")
    for n in sorted(numbers):
        handle(g, state, n, live)


def handle(g, state, n, live):
    try:
        reconcile(g, state, n, live)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            urllib.error.URLError, KeyError) as e:
        log.error("%s: %r", n, e)


def stream(g, state, live, state_file):
    cmd = ["ssh", *SSH_OPTIONS, "-o", "ServerAliveInterval=30", HOST,
           "gerrit", "stream-events",
           "-s", "comment-added", "-s", "patchset-created", "-s", "change-merged"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    log.info("event stream started (pid %s)", p.pid)
    lines = queue.Queue()

    def pump():
        for line in p.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    try:
        scan(g, state, live)
        save(state, state_file)
        while True:
            try:
                line = lines.get(timeout=RESCAN_SECONDS)
            except queue.Empty:
                scan(g, state, live)
                save(state, state_file)
                continue
            if line is None:
                log.warning("event stream ended")
                return
            ev = json.loads(line)
            ch = ev.get("change", {})
            relevant = (ch.get("project") == PROJECT
                        and ch.get("owner", {}).get("username") == g.username)
            log.info("event %s on %s %s%s", ev.get("type"), ch.get("project"),
                     ch.get("number"), "" if relevant else " (ignored)")
            if not relevant:
                continue
            handle(g, state, ch["number"], live)
            save(state, state_file)
    finally:
        p.kill()
        p.wait()


def save(state, state_file):
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, state_file)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="really trigger prechecks and submit")
    ap.add_argument("--once", action="store_true", help="scan once and exit")
    ap.add_argument("--state", default=os.path.expanduser(
        "~/.gerrit-precheck-bot.json"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(message)s")
    state = json.load(open(a.state)) if os.path.exists(a.state) else {}
    g = Gerrit()
    log.info("running as %s, %s", g.username, "LIVE" if a.live else "dry-run")
    if a.once:
        scan(g, state, a.live)
        save(state, a.state)
        return
    delay = 5
    while True:
        started = time.monotonic()
        try:
            stream(g, state, a.live, a.state)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                urllib.error.URLError, OSError, ValueError) as e:
            log.error("stream: %r", e)
        if time.monotonic() - started > 60:
            delay = 5
        log.info("reconnecting in %ss", delay)
        time.sleep(delay)
        delay = min(delay * 2, 300)


if __name__ == "__main__":
    main()
