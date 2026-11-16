"""Token use and cost of model calls: a summary at the end of `ask` and `judge`, and a ledger to add up over time.

Two records, both git-ignored (under runs/):
  runs/usage.csv           the ledger. One row for every call that reached the model provider (so it was billed),
                           appended by model.call_model at the moment the reply arrives. A call answered from the
                           response cache is not a row, because it cost nothing this time. A call that failed after
                           the provider replied (refused, cut off at max_output_tokens, reply not valid JSON) IS a row:
                           it was billed and produced no answer. `hfal usage` adds the ledger up.
  runs/RUN_ID/usage.json   the totals of one `ask` or `judge` run, written when the run ends.

Cost = tokens x the price per million tokens in settings.yaml `prices`, at the price in force when the call was made
(the ledger stores the dollars, so a later price change does not rewrite history). A model with no price listed has
tokens counted and its cost left blank, never guessed. Output tokens are the count the provider reports, which
includes the model's thinking.

Prompt caching (Nov 12, model.prompt_cache): input_tokens is the whole prompt; cache_read_tokens and
cache_write_tokens are the parts of it read from or written to the provider's prompt cache, priced at the model's
`cache_read` and `cache_write` prices. A call with cache tokens but no cache price for its model has its cost left
blank. Rows written before Nov 12 have no cache columns (blank): their cost is as it was logged.

OCR (src/hfal/ocr.py) is in the same ledger: one row per page sent to Amazon Textract, purpose "ocr", provider
"textract", no tokens, cost = settings.yaml `ocr.price_per_page`. Pages read from the OCR cache are not rows.
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone

from . import paths
from .files import read_csv, read_csv_rows, read_json_or_none, write_csv, write_json

LEDGER_FIELDS = ["time_utc", "purpose", "run_id", "hospital_id", "provider", "model", "effort",
                 "input_tokens", "output_tokens", "cost_usd", "status", "cache_read_tokens", "cache_write_tokens"]


def ledger_path():
    return paths.RUNS / "usage.csv"


def upgrade_ledger(path) -> None:
    """Rewrite a ledger whose header is older than LEDGER_FIELDS with the current header (new columns blank), so
    appended rows line up. Nothing else changes. Written to a temporary file first, then swapped in."""
    if not path.exists():
        return
    header = next(iter(read_csv_rows(path, "utf-8")), [])
    if header == LEDGER_FIELDS:
        return
    rows = read_csv(path, "utf-8")
    write_csv(path, ({k: r.get(k, "") or "" for k in LEDGER_FIELDS} for r in rows), LEDGER_FIELDS, atomic=True)


def _int(v) -> int:
    return int(v or 0)


def price_for(provider: str, model: str, prices: dict | None = None) -> dict | None:
    """{'input': $/million, 'output': $/million} for a model, or None when settings.yaml has no price for it.

    Anthropic API: the longest price key the model name starts with (so 'claude-sonnet-5-5' also covers a dated
    name the API may report). Any other provider needs its own key 'provider/model' (Bedrock is priced separately)."""
    prices = paths.settings().get("prices", {}) if prices is None else prices
    if provider != "anthropic":
        return prices.get(f"{provider}/{model}")
    keys = [k for k in prices if "/" not in k and model.startswith(k)]
    return prices[max(keys, key=len)] if keys else None


def cost_usd(info: dict, prices: dict | None = None) -> float | None:
    """Dollars for one call's tokens, or None when the model has no price (or no cache price for cache tokens)."""
    p = price_for(info.get("provider", "anthropic"), info.get("model", ""), prices)
    if not p:
        return None
    read, write = _int(info.get("cache_read_tokens")), _int(info.get("cache_write_tokens"))
    if (read and "cache_read" not in p) or (write and "cache_write" not in p):
        return None
    plain = _int(info.get("input_tokens")) - read - write
    return (plain * p["input"] + read * p.get("cache_read", 0) + write * p.get("cache_write", 0)
            + _int(info.get("output_tokens")) * p["output"]) / 1_000_000


def _ledger_row(info: dict, status: str, tag: dict, cost: float | None) -> dict:
    return {
        "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": tag.get("purpose", ""), "run_id": tag.get("run_id", ""),
        "hospital_id": tag.get("hospital_id", ""), "provider": info.get("provider", ""),
        "model": info.get("model", ""), "effort": info.get("effort") or "",
        "input_tokens": info.get("input_tokens", 0), "output_tokens": info.get("output_tokens", 0),
        "cost_usd": "" if cost is None else f"{cost:.6f}", "status": status,
        "cache_read_tokens": info.get("cache_read_tokens", 0) or 0,
        "cache_write_tokens": info.get("cache_write_tokens", 0) or 0,
    }


def log_call(info: dict, status: str = "ok", tag: dict | None = None) -> None:
    """Append one billed call to the ledger. Never stops a run: a failure to write is reported and the run goes on."""
    tag = tag or {}
    try:
        # A service not priced by tokens (Textract OCR: per page) passes its own cost_usd.
        cost = info["cost_usd"] if "cost_usd" in info else cost_usd(info)
        path = ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        upgrade_ledger(path)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS, lineterminator="\n")
            if new:
                w.writeheader()
            w.writerow(_ledger_row(info, status, tag, cost))
    except OSError as e:
        print(f"warning: could not write the usage ledger ({e}); this call's tokens are not recorded there",
              file=sys.stderr)


class Totals:
    """Adds up the call info that `ask` and `judge` get back from call_model, for one run."""

    def __init__(self):
        self.fresh = self.cached = 0
        self.input = self.output = 0                 # tokens actually billed in this run (fresh calls only)
        self.cache_read = self.cache_write = 0       # parts of self.input read from / written to the prompt cache
        self.cost = 0.0
        self.unpriced = set()                        # models used with no price in settings.yaml
        self.avoided_input = self.avoided_output = 0       # what the cached answers would have used
        self.avoided_cost = 0.0

    def add(self, info: dict | None) -> None:
        if not info:                                 # no model call (nothing collected, or too large)
            return
        c = cost_usd(info)
        if info.get("cached"):
            self.cached += 1
            self.avoided_input += info.get("input_tokens", 0)
            self.avoided_output += info.get("output_tokens", 0)
            self.avoided_cost += c or 0.0
            return
        self.fresh += 1
        self.input += info.get("input_tokens", 0)
        self.output += info.get("output_tokens", 0)
        self.cache_read += _int(info.get("cache_read_tokens"))
        self.cache_write += _int(info.get("cache_write_tokens"))
        if c is None:
            self.unpriced.add(info.get("model", "?"))
        else:
            self.cost += c

    def as_dict(self) -> dict:
        return {"calls_billed": self.fresh, "calls_from_cache": self.cached,
                "input_tokens": self.input, "output_tokens": self.output,
                "cache_read_tokens": self.cache_read, "cache_write_tokens": self.cache_write,
                "cost_usd": round(self.cost, 4), "models_without_price": sorted(self.unpriced),
                "cache_avoided": {"input_tokens": self.avoided_input, "output_tokens": self.avoided_output,
                                  "cost_usd": round(self.avoided_cost, 4)}}

    def lines(self, title: str) -> list[str]:
        out = [f"{title}: {self.fresh} call(s) billed, {self.cached} answered from the cache",
               f"  tokens {self.input:,} in / {self.output:,} out"
               + (f"   cost ${self.cost:,.2f}" if not self.unpriced else
                  f"   cost ${self.cost:,.2f} + unpriced ({', '.join(sorted(self.unpriced))}: add it to settings.yaml `prices`)")]
        if self.cache_read or self.cache_write:
            out.append(f"  of the input, {self.cache_read:,} read from the provider's prompt cache and "
                       f"{self.cache_write:,} written to it")
        if self.cached:
            out.append(f"  the cached answers would have used {self.avoided_input:,} in / {self.avoided_output:,} out "
                       f"(about ${self.avoided_cost:,.2f}); not counted above")
        return out


def write_run_usage(run_id: str, section: str, totals: Totals) -> None:
    """Merge this section ('ask' or 'judge') into runs/RUN_ID/usage.json. A second `ask` into the same run id
    replaces the first one's totals; the ledger keeps every call."""
    f = paths.RUNS / run_id / "usage.json"
    data = read_json_or_none(f) if f.exists() else None
    data = data or {}
    data[section] = totals.as_dict()
    write_json(f, data)


def read_ledger() -> list[dict]:
    path = ledger_path()
    return read_csv(path, "utf-8") if path.exists() else []


def aggregate(rows: list[dict], by: str = "purpose") -> list[dict]:
    """Group ledger rows by purpose | model | day | run | status; one dict per group with calls, tokens and cost.
    cost_usd is the sum of the priced calls; unpriced_calls counts the rows with no price."""
    def key(r):
        return {"purpose": r["purpose"], "model": r["model"], "day": r["time_utc"][:10],
                "run": r["run_id"] or "-", "status": r["status"]}[by]
    groups = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                                  "cost_usd": 0.0, "unpriced_calls": 0})
    for r in rows:
        g = groups[key(r)]
        g["calls"] += 1
        g["input_tokens"] += _int(r["input_tokens"])
        g["output_tokens"] += _int(r["output_tokens"])
        g["cache_read_tokens"] += _int(r.get("cache_read_tokens"))
        if r["cost_usd"] == "":
            g["unpriced_calls"] += 1
        else:
            g["cost_usd"] += float(r["cost_usd"])
    return [{by: k, **v} for k, v in sorted(groups.items())]


def report(since: str | None = None, run: str | None = None, by: str = "purpose") -> list[str]:
    """Text lines for `hfal usage`: the ledger added up, with a grand total. since is YYYY-MM-DD (UTC)."""
    rows = read_ledger()
    if since:
        rows = [r for r in rows if r["time_utc"][:10] >= since]
    if run:
        rows = [r for r in rows if r["run_id"] == run]
    if not rows:
        return ["no billed calls in the ledger" + (f" since {since}" if since else "") + (f" for run {run}" if run else "")
                + f" ({ledger_path()})"]
    lines = [f"{by:<44} {'calls':>6} {'input tokens':>14} {'output tokens':>14} {'cost $':>10}"]
    for g in aggregate(rows, by):
        lines.append(f"{str(g[by]):<44} {g['calls']:>6} {g['input_tokens']:>14,} {g['output_tokens']:>14,} "
                     f"{g['cost_usd']:>10,.2f}" + (f"  (+{g['unpriced_calls']} unpriced)" if g["unpriced_calls"] else ""))
    t = aggregate(rows, "status")
    total_cost = sum(g["cost_usd"] for g in t)
    lines.append(f"{'TOTAL':<44} {sum(g['calls'] for g in t):>6} {sum(g['input_tokens'] for g in t):>14,} "
                 f"{sum(g['output_tokens'] for g in t):>14,} {total_cost:>10,.2f}")
    read = sum(g["cache_read_tokens"] for g in t)
    if read:
        lines.append(f"of the input tokens, {read:,} were read from the provider's prompt cache (cheaper)")
    failed = [g for g in t if g["status"] != "ok"]
    if failed:
        lines.append("billed but gave no answer: " + "; ".join(f"{g['calls']} {g['status']} (${g['cost_usd']:,.2f})" for g in failed))
    return lines
