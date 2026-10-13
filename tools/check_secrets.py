"""Scan every commit for secrets, forbidden paths and leaked key values.

Ported from Whyf. check_publishable.py looks at the working tree; this looks
at history, because a key committed today and deleted tomorrow is still in
the history when the repo goes public.

    python tools/check_secrets.py
    python tools/check_secrets.py --verbose

Exit 1 means do not push. A secret already committed is compromised whether or
not you rewrite history: rotate it first, then clean the history.
"""
import subprocess
import sys

from _secrets import FORBIDDEN_PATHS, ROOT, local_secret_values, scan_text


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=ROOT,
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else ""


def main():
    verbose = "--verbose" in sys.argv
    blocking = []

    # ---- 0. .env / private must be ignored right now ------------------------
    for name in (".env", "private", "var"):
        if (ROOT / name).exists():
            r = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT, capture_output=True)
            if r.returncode != 0:
                blocking.append("{} exists and is NOT gitignored".format(name))

    commits = [c for c in git("rev-list", "--all").split() if c]
    if not commits:
        print("no commits yet, nothing in history to scan")
    else:
        # ---- 1. paths that were ever tracked --------------------------------
        tracked = {l.strip() for l in git("log", "--all", "--pretty=format:", "--name-only").splitlines() if l.strip()}
        for path in sorted(tracked):
            if any(p.search(path) for p in FORBIDDEN_PATHS):
                blocking.append("{} was committed at some point. It is in history even if it is gone now.".format(path))

        # ---- 2. every unique blob, once -------------------------------------
        blobs = {}
        for line in git("rev-list", "--objects", "--all").splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                blobs.setdefault(parts[0], parts[1])
        secret_values = local_secret_values()
        scanned = 0
        if blobs:
            proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            raw, _ = proc.communicate(("\n".join(blobs) + "\n").encode())
            # walk the stream by its own headers; trees are in the list too
            offset = 0
            while offset < len(raw):
                nl = raw.find(b"\n", offset)
                if nl < 0:
                    break
                header = raw[offset:nl].split()
                if len(header) < 3:
                    offset = nl + 1
                    continue
                sha, kind, size = header[0].decode(), header[1], int(header[2])
                body = raw[nl + 1:nl + 1 + size]
                offset = nl + 1 + size + 1
                if kind != b"blob":
                    continue
                try:
                    text = body.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                scanned += 1
                blocking += scan_text(text, blobs.get(sha, "(unknown path)"), secret_values)
        print("scanned {} commits".format(len(commits)))
        if verbose:
            print("  {} tracked paths, {} unique blobs, {} local secret values compared".format(
                len(tracked), scanned, len(secret_values)))

    if blocking:
        print("\n{} BLOCKING".format(len(blocking)))
        for b in dict.fromkeys(blocking):
            print("  x " + b)
        return 1
    print("no secrets found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
