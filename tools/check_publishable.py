"""Working-tree scan: everything git would publish must be free of secrets,
key values and cached Qloo response data.

Covers files that are tracked or would be added (not ignored). The hackathon
terms allow private caching of Qloo responses but not publishing them, so the
cache and benchmark results must stay out of the tree.

    python tools/check_publishable.py
"""
import subprocess
import sys

from _secrets import FORBIDDEN_PATHS, ROOT, local_secret_values, scan_text

TEXTUAL = (".py", ".md", ".txt", ".html", ".js", ".css", ".json", ".toml", ".yml", ".yaml", ".sql", ".example", "Makefile", "Procfile")


def publishable_files():
    r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("git ls-files failed - is this a git repo?")
    return [l for l in r.stdout.splitlines() if l.strip()]


def main():
    problems = []
    secret_values = local_secret_values()
    files = publishable_files()
    for rel in files:
        if any(p.search(rel) for p in FORBIDDEN_PATHS):
            problems.append("{} would be published but must never be".format(rel))
            continue
        if not rel.endswith(TEXTUAL) and "." in rel.rsplit("/", 1)[-1]:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel != "tools/_secrets.py":
            problems += scan_text(text, rel, secret_values)
        if '"entity_id"' in text and '"results"' in text and rel.endswith(".json"):
            problems.append("{} looks like raw Qloo response data; keep it out of the public repo".format(rel))

    print("scanned {} publishable files against {} local secret values".format(len(files), len(secret_values)))
    if problems:
        print("\n{} PROBLEMS - do not publish".format(len(problems)))
        for p in problems:
            print("  x " + p)
        return 1
    print("working tree is publishable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
