"""Ask the README's three sample questions to the same model that wrote the results, with nothing else.

    uv run python scripts/readme_baseline.py [--model kimi-k3-max]

No system prompt, no tools, no documents, no reply format: just the question, at the same thinking effort the pipeline
uses. This is the comparison for README "Sample questions" (what the model says from memory, next to what the
pipeline found in the hospital's own documents). Three billed calls, written to the usage ledger (purpose
`readme_baseline`). Answers go to runs/readme_baseline/ (git-ignored); the README quotes them.
"""
import argparse
import json
from datetime import datetime, timezone

from hfal import paths
from hfal.files import write_atomic
from hfal.model import plain_answer

# Eval-set hospitals only (never CSSNY's sample), so naming them here is the same as naming them in results/latest/.
QUESTIONS = {
    "q1_assets": "Can Community Memorial Hospital in Hamilton, New York, take a patient's savings or other assets into "
                 "account when deciding whether to give financial assistance?",
    "q2_state_application": "Is the financial assistance application that Rome Memorial Hospital in Rome, New York, "
                            "posts on its website the state's standard uniform financial assistance application?",
    "q3_languages": "In which languages does Mount Sinai Brooklyn offer its financial assistance application?",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="kimi-k3-max", help="a preset under `models:` in settings.yaml")
    args = ap.parse_args()
    paths.use_model("model", args.model)
    cfg = paths.settings()["model"]
    results = {}
    for key, question in QUESTIONS.items():
        print(f"asking {key} ...", flush=True)
        results[key] = plain_answer(cfg, question, "readme_baseline")
        print(f"  {results[key]['output_tokens']} output tokens")
    out = paths.RUNS / "readme_baseline" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(out, json.dumps(results, indent=2, ensure_ascii=False))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
