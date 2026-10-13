"""Run every benchmark text through POST /api/generate and print a comparison.

    python tools/benchmark.py                          # against http://localhost:8000
    python tools/benchmark.py --url https://<demo-url>
    python tools/benchmark.py --mode topics

Full responses (trace included) go to benchmark/results/<timestamp>.json,
which is gitignored: it holds Qloo response data, and the hackathon terms do
not allow publishing that. Every number printed is computed from the actual
responses.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TEXTS = ROOT / "benchmark" / "texts"
RESULTS = ROOT / "benchmark" / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--mode", default="tags", choices=["tags", "topics"])
    ap.add_argument("--destination", default="general")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    files = sorted(TEXTS.glob("*.txt"))
    if not files:
        sys.exit("no benchmark texts in " + str(TEXTS))
    runs = []
    head = f"{'file':24} | overlap | novelty | baseline_n | exp_n | inferred | latency | errors"
    print(head + "\n" + "-" * len(head))
    with httpx.Client(timeout=180) as client:
        for f in files:
            body = {"text": f.read_text(encoding="utf-8").strip(), "destination": args.destination,
                    "mode": args.mode, "advanced": True}
            t0 = time.monotonic()
            try:
                r = client.post(args.url.rstrip("/") + "/api/generate", json=body)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPError as exc:
                print(f"{f.name:24} | request failed: {exc}")
                runs.append({"file": f.name, "error": str(exc)})
                continue
            c = data["comparison"]
            a, b = c["baseline"], c["experimental"]
            inferred = sum(1 for t in b.get("tags") or [] if t["source"] == "qloo_inferred")
            errs = "; ".join(f"{k}: {p['error'][:60]}" for k, p in (("A", a), ("B", b)) if p.get("error")) or "-"
            print(f"{f.name:24} | {c['overlap_count']:7} | {c['novelty_count']:7} | {a['count']:10} | "
                  f"{b['count']:5} | {inferred:8} | {c['total_latency_ms'] / 1000:6.1f}s | {errs}")
            runs.append({"file": f.name, "wall_s": round(time.monotonic() - t0, 2), "response": data})

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.mode}.json"
    out.write_text(json.dumps({"url": args.url, "mode": args.mode, "runs": runs}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\nsaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
