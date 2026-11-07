import argparse
import csv
import json

from . import paths
from .ask import ask_hospital, new_run_id, ping
from .discover import discover_all
from .extract import extract_all
from .fetch import fetch_all
from .grade import grade_hospital
from .score import load_golden, load_run, score_run, write_csv
from .sources import build_sources
from .tag import tag_all


def _only(values):
    return set(values) if values else None


def main() -> None:
    p = argparse.ArgumentParser(prog="hfal")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="tiny request to check the model provider's credentials and model access")
    s = sub.add_parser("sources", help="write landing-page rows of data/sources.csv from data/hospitals.csv")
    s.add_argument("--set", choices=["dev", "eval", "all"], default="dev")
    s.add_argument("--hospital", nargs="*", help="limit to these hospital_ids")
    for name in ("discover", "fetch", "extract", "tag"):
        s = sub.add_parser(name)
        s.add_argument("--hospital", nargs="*", help="limit to these hospital_ids")
    s = sub.add_parser("ask")
    s.add_argument("--hospital", nargs="*")
    s.add_argument("--run-id")
    s.add_argument("--dry-run", action="store_true", help="report prompt size per hospital; no model call")
    for name in ("grade", "score"):
        s = sub.add_parser(name)
        s.add_argument("--run", required=True, help="run_id folder under runs/")
    args = p.parse_args()

    if args.cmd == "ping":
        r = ping(paths.settings()["model"])
        print(f"ok: {r['provider']}  model={r['model_id']}  region={r['region'] or '-'}  "
              f"reply={r['reply']!r}  tokens={r['input_tokens']}/{r['output_tokens']}")
    elif args.cmd == "sources":
        build_sources(args.set, only=_only(args.hospital))
    elif args.cmd == "discover":
        discover_all(only=_only(args.hospital))
    elif args.cmd == "fetch":
        fetch_all(only=_only(args.hospital))
    elif args.cmd == "extract":
        extract_all(only=_only(args.hospital))
    elif args.cmd == "tag":
        tag_all(only=_only(args.hospital))
    elif args.cmd == "ask":
        run_id = args.run_id or new_run_id()
        ids = args.hospital or sorted(d.name for d in paths.TEXT.iterdir() if d.is_dir())
        for hid in ids:
            r = ask_hospital(hid, run_id, dry_run=args.dry_run)
            if args.dry_run:
                print(f"{hid}  documents={r.get('documents', 0)}  approx_input_tokens={r.get('approx_input_tokens', 0)}")
                continue
            c = r.get("call") or {}
            print(f"{hid}  done  input_tokens={c.get('input_tokens')}  output_tokens={c.get('output_tokens')}"
                  f"  cached={c.get('cached')}")
        if not args.dry_run:
            print(f"run_id: {run_id}")
    elif args.cmd == "grade":
        run_dir = paths.RUNS / args.run
        rubric = paths.rubric()
        ids = [c["id"] for c in paths.criteria()]
        rows = []
        for hid, recs in load_run(run_dir).items():
            g = grade_hospital(recs, ids, rubric)
            full = json.loads((run_dir / f"{hid}.json").read_text(encoding="utf-8"))
            rep = full.get("reported", {})
            verified = lambda key, field: "; ".join(sorted({x[field].strip().title() for x in rep.get(key, [])
                                                             if x.get("quote_verified")}))
            rows.append(dict(
                hospital_id=hid, status=g["status"], letter=g["letter"] or "",
                errors=g["errors"], auto_fail=";".join(g["auto_fail"]),
                yes=g["counts"]["YES"], no=g["counts"]["NO"], na=g["counts"]["N/A"],
                needs_review=g["counts"]["needs_review"],
                failing=";".join(g["failing"]), review_ids=";".join(g["needs_review"]),
                **{f"reported_{k}": v for k, v in g["reported"].items()},
                languages=verified("languages", "language"),
                languages_from_links="; ".join(rep.get("languages_from_links", [])),
                psa_counties=verified("psa_counties", "county"),
            ))
        write_csv(run_dir / "grades.csv", rows)
        print(f"wrote {run_dir / 'grades.csv'}")
    elif args.cmd == "score":
        run_dir = paths.RUNS / args.run
        golden = load_golden(paths.GOLDEN / "golden.csv")
        metrics, diffs = score_run(golden, load_run(run_dir))
        write_csv(run_dir / "metrics.csv", metrics)
        write_csv(run_dir / "diff.csv", diffs)
        print(json.dumps(metrics, indent=2))
        print(f"{len(diffs)} disagreements -> {run_dir / 'diff.csv'}")


if __name__ == "__main__":
    main()
