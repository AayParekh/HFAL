import csv
import json


from hfal import judge, paths

DOC = ("Financial assistance is available to patients up to 400% FPL. Call 555-0100 for help with the application. "
       "This policy is available in Spanish.")


def setup(tmp_path, monkeypatch, sets=None, window=10**6):
    sets = sets or {"d1": "dev", "e1": "eval"}
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs"),
                      ("CACHE", "cache"), ("GOLDEN", "golden")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    cfg = {"model": {"name": "m"}, "judge": {"name": "j", "max_output_tokens": 10}, "prompt_version": "t",
           "context_window_tokens": window, "max_input_share": 0.8, "chars_per_token": 3}
    monkeypatch.setattr(paths, "settings", lambda: cfg)
    monkeypatch.setattr(paths, "criteria", lambda: [
        {"id": "c_phone", "question": "Is a phone number listed?", "yes_means": "a phone number is listed"},
        {"id": "c_tables", "question": "Are discount tables included?", "yes_means": "tables included"},
        {"id": "c_ok", "question": "Is the policy posted?", "yes_means": "posted"}])
    (tmp_path / "hospitals.csv").write_text("hospital_id,name,city,system,set,landing_url,url_source,verified_at,note\n" +
        "".join(f"{h},Invented Hospital {h},X,,{s},,,,\n" for h, s in sets.items()))
    (tmp_path / "golden").mkdir()
    rows = [(h, c, lab) for h in sets for c, lab in [("c_phone", "NO"), ("c_tables", "YES"), ("c_ok", "YES")]]
    (tmp_path / "golden" / "golden.csv").write_text("hospital_id,criterion_id,label\n" + "".join(f"{h},{c},{l}\n" for h, c, l in rows))
    run = tmp_path / "runs" / "run1"
    run.mkdir(parents=True)
    for h in sets:
        (tmp_path / "text" / h).mkdir(parents=True)
        (tmp_path / "text" / h / "aaaa1111.json").write_text(json.dumps(
            {"sha8": "aaaa1111", "source_url": "https://h.org/fap.pdf", "label": "", "needs_ocr": False, "pages": [DOC]}))
        (tmp_path / "raw" / h / "2026-01-01").mkdir(parents=True)
        (tmp_path / "raw" / h / "2026-01-01" / "manifest.json").write_text(json.dumps(
            [{"url": "https://h.org/fap.pdf", "status": "ok", "sha8": "aaaa1111", "ext": "pdf"}]))
        (run / f"{h}.json").write_text(json.dumps({"hospital_id": h, "run_id": "run1", "documents": [{"sha8": "aaaa1111"}],
            "answers": [
                dict(criterion_id="c_phone", answer="YES", quote="Call 555-0100 for help with the application",
                     source_doc="aaaa1111", page=1, reason="a phone number is given", quote_verified=True),
                dict(criterion_id="c_tables", answer="NOT_FOUND", quote="", source_doc="", page=None,
                     reason="no tables in the documents", quote_verified=False),
                dict(criterion_id="c_ok", answer="YES", quote="up to 400% FPL", source_doc="aaaa1111", page=1,
                     reason="posted", quote_verified=True)]}))


class Judge:
    """Stands in for the model: records the prompt, returns canned findings."""

    def __init__(self, findings):
        self.prompts, self.findings = [], findings

    def __call__(self, system, user, cfg, schema=None, tag=None):
        self.prompts.append(user)
        assert schema is judge.JUDGE_SCHEMA
        return {"findings": self.findings}, {"input_tokens": 100, "output_tokens": 10, "cached": False, "model": "j"}


F_PHONE = dict(criterion_id="c_phone", bucket="documents_support_model", who_is_right="model",
               explanation="The application page lists a phone number.", evidence_quote="Call 555-0100 for help",
               source_doc="aaaa1111", page=1)
F_TABLES = dict(criterion_id="c_tables", bucket="doc_not_found", who_is_right="cannot_tell",
                explanation="No document with tables was collected.", evidence_quote="", source_doc="", page=None)


def test_only_disagreements_are_sent_and_no_hospital_name_leaves_the_machine(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    fake = Judge([F_PHONE, F_TABLES])
    monkeypatch.setattr(judge, "call_model", fake)
    out = judge.judge_run("run1")
    assert len(fake.prompts) == 1
    p = fake.prompts[0]
    assert 'criterion_id="c_phone"' in p and 'criterion_id="c_tables"' in p
    assert 'criterion_id="c_ok"' not in p                       # matches are decided by code and never sent
    assert "Golden label: NO" in p and "Checker answer: YES" in p and "Golden label: YES" in p
    assert "Invented Hospital" not in p and "d1" not in p       # no name or id in the prompt
    assert out["summary"]["disagreements judged"] == 2 and out["buckets"] == {"documents_support_model": 1, "doc_not_found": 1}


def test_eval_hospitals_are_refused_and_never_sent(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    fake = Judge([F_PHONE, F_TABLES])
    monkeypatch.setattr(judge, "call_model", fake)
    out = judge.judge_run("run1")
    assert out["summary"]["refused: not a dev hospital"] == 1
    assert len(fake.prompts) == 1                                # only d1
    rows = list(csv.DictReader(open(tmp_path / "runs" / "run1" / "judge.csv", encoding="utf-8-sig")))
    assert {r["hospital_id"] for r in rows} == {"d1"}
    assert not (tmp_path / "runs" / "run1" / "judge" / "e1.json").exists()


def test_judge_evidence_is_verified_by_code(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"})
    invented = {**F_PHONE, "evidence_quote": "A passage the document does not contain at all"}
    monkeypatch.setattr(judge, "call_model", Judge([invented, F_TABLES]))
    judge.judge_run("run1")
    rows = {r["criterion_id"]: r for r in csv.DictReader(open(tmp_path / "runs" / "run1" / "judge.csv", encoding="utf-8-sig"))}
    assert rows["c_phone"]["evidence_verified"] == "False" and rows["c_phone"]["evidence_url"] == ""
    assert rows["c_tables"]["evidence_verified"] == ""           # no quote asked for doc_not_found


def test_verified_evidence_carries_its_document_and_page(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"})
    monkeypatch.setattr(judge, "call_model", Judge([F_PHONE, F_TABLES]))
    judge.judge_run("run1")
    rows = {r["criterion_id"]: r for r in csv.DictReader(open(tmp_path / "runs" / "run1" / "judge.csv", encoding="utf-8-sig"))}
    r = rows["c_phone"]
    assert (r["evidence_verified"], r["evidence_url"], r["evidence_page"]) == ("True", "https://h.org/fap.pdf", "1")
    assert r["golden"] == "NO" and r["model_answer"] == "YES" and r["bucket"] == "documents_support_model"


def test_missing_finding_is_marked_not_dropped(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"})
    monkeypatch.setattr(judge, "call_model", Judge([F_PHONE]))   # the judge forgot c_tables
    judge.judge_run("run1")
    rows = {r["criterion_id"]: r for r in csv.DictReader(open(tmp_path / "runs" / "run1" / "judge.csv", encoding="utf-8-sig"))}
    assert rows["c_tables"]["bucket"] == "judge_gave_no_finding"


def test_human_columns_survive_a_rerun(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"})
    monkeypatch.setattr(judge, "call_model", Judge([F_PHONE, F_TABLES]))
    judge.judge_run("run1")
    path = tmp_path / "runs" / "run1" / "judge.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    rows[0]["human_bucket"], rows[0]["human_note"] = "golden_error", "checked the live page"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=judge.CSV_FIELDS, lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    judge.judge_run("run1")
    again = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert (again[0]["human_bucket"], again[0]["human_note"]) == ("golden_error", "checked the live page")


def test_no_disagreements_means_no_call(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"})
    rec = tmp_path / "runs" / "run1" / "d1.json"
    data = json.loads(rec.read_text())
    data["answers"][0].update(answer="NO", quote="Call 555-0100 for help with the application")   # now matches golden NO
    data["answers"][1].update(answer="YES", quote="up to 400% FPL", source_doc="aaaa1111", page=1, quote_verified=True)
    rec.write_text(json.dumps(data))
    monkeypatch.setattr(judge, "call_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert judge.judge_run("run1")["summary"] == {"no_disagreements": 1}


def test_too_large_prompt_is_skipped_not_truncated(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"}, window=10)
    monkeypatch.setattr(judge, "call_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    out = judge.judge_run("run1")
    assert out["summary"] == {"skipped: too large for one call": 1}


def test_dry_run_makes_no_call_and_writes_nothing(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, sets={"d1": "dev"})
    monkeypatch.setattr(judge, "call_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    out = judge.judge_run("run1", dry_run=True)
    assert out["summary"]["disagreements to judge"] == 2 and out["summary"]["approx input tokens"] > 0
    assert not (tmp_path / "runs" / "run1" / "judge.csv").exists()


def test_schema_objects_are_closed():
    def closed(n):
        if isinstance(n, dict):
            if n.get("type") == "object":
                assert n["additionalProperties"] is False and set(n["required"]) == set(n["properties"])
            for v in n.values():
                closed(v)
        elif isinstance(n, list):
            for v in n:
                closed(v)
    closed(judge.JUDGE_SCHEMA)
    assert set(judge.BUCKETS) == set(judge.JUDGE_SCHEMA["properties"]["findings"]["items"]["properties"]["bucket"]["enum"])
