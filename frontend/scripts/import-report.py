#!/usr/bin/env python3
"""Convert the HFAL results HTML report into the mock dataset used by the app."""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LABEL_TO_CODE = {
    "Application posted online": "application_posted",
    "Plain-language summary posted": "pls_posted",
    "Full policy posted": "policy_statement_posted",
    "Documents agree with each other": "consistent_across_docs",
    "Service area drawn by the state's rules": "psa_2007_compliant",
    "No deadline to apply": "no_time_limit",
    "No test of savings or property": "no_asset_checks",
    "Immigration status not a barrier": "no_immigration_barrier",
    "Full state application form": "uniform_app_complete",
    "Contact for help on the application": "app_contact_info",
    "Income and discount table on the application": "app_income_discount_tables",
    "Current poverty figures on the application": "app_fpl_year_current",
    "Help for incomes up to 400% of the poverty level": "app_max_fpl_pct",
    "Monthly payments capped at 5% of income": "app_installment_cap",
    "Service area in the summary": "pls_psa_described",
    "How to apply, in the summary": "pls_means_of_applying",
    "Income levels in the summary": "pls_income_levels",
    "Application in patients' languages": "application_languages",
}
APPLICATION_CODES = {
    "application_posted",
    "uniform_app_complete",
    "app_contact_info",
    "app_income_discount_tables",
    "app_fpl_year_current",
    "app_max_fpl_pct",
    "app_installment_cap",
    "application_languages",
}
# Matched against CMS NPPES location records; unmatched specialty facilities were cross-checked
# against their official location pages and OpenStreetMap. Coordinates are address geocodes.
HOSPITAL_ADDRESSES = {
    "Arnot Ogden Medical Center": ("600 Roe Avenue", "Elmira", "14905", 42.1001845, -76.8272709),
    "BronxCare Hospital Center": ("1650 Grand Concourse", "Bronx", "10457", 40.8434894, -73.9105735),
    "Brooklyn Hospital Center - Downtown Campus": ("121 DeKalb Avenue", "Brooklyn", "11201", 40.6905444, -73.9779328),
    "Garnet Health Medical Center": ("707 East Main Street", "Middletown", "10940", 41.4423094, -74.3683176),
    "Good Samaritan Hospital of Suffern": ("255 Lafayette Avenue", "Suffern", "10901", 41.1108492, -74.1344493),
    "Highland Hospital": ("1000 South Avenue", "Rochester", "14620", 43.1355245, -77.6062510),
    "Ira Davenport Memorial Hospital": ("7571 State Route 54", "Bath", "14810", 42.3743642, -77.2782477),
    "Maimonides Medical Center": ("4802 10th Avenue", "Brooklyn", "11219", 40.6394203, -73.9981068),
    "Medina Memorial Hospital": ("200 Ohio Street", "Medina", "14103", 43.2239021, -78.3976414),
    "Mercy Hospital": ("1000 North Village Avenue", "Rockville Centre", "11570", 40.6871910, -73.6308730),
    "Mount Sinai - Behavioral Health Center": ("45 Rivington Street", "New York", "10002", 40.7208124, -73.9910887),
    "Mount Sinai West": ("1000 Tenth Avenue", "New York", "10019", 40.7697129, -73.9869074),
    "NYU Langone Hospital - Suffolk (formerly Long Island Community Hospital)": ("101 Hospital Road", "Patchogue", "11772", 40.7802502, -72.9764211),
    "NYU Langone Hospital-Brooklyn": ("150 55th Street", "Brooklyn", "11220", 40.6466733, -74.0209065),
    "NYU Langone Orthopedic Hospital": ("301 East 17th Street", "New York", "10003", 40.7343943, -73.9829914),
    "North Shore University Hospital": ("300 Community Drive", "Manhasset", "11030", 40.7752137, -73.7010277),
    "Richmond University Medical Center": ("355 Bard Avenue", "Staten Island", "10310", 40.6361272, -74.1055112),
    "Samaritan Medical Center": ("830 Washington Street", "Watertown", "13601", 43.9647796, -75.9144352),
    "St. Joseph's Hospital": ("555 Saint Josephs Boulevard", "Elmira", "14901", 42.0913403, -76.7972447),
    "Strong Memorial Hospital": ("601 Elmwood Avenue", "Rochester", "14642", 43.1229300, -77.6253832),
}


class Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []


class ReportParser(HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__()
        self.root = Node("root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def descendants(node, tag=None):
    for child in node.children:
        if isinstance(child, Node):
            if tag is None or child.tag == tag:
                yield child
            yield from descendants(child, tag)


def text(node, skip=()):
    return "".join(
        child if isinstance(child, str) else ("" if child.tag in skip else text(child, skip))
        for child in node.children
    ).strip()


def direct_cells(row):
    return [child for child in row.children if isinstance(child, Node) and child.tag == "td"]


def report_locations(root):
    locations = {}
    for row in descendants(root, "tr"):
        cells = direct_cells(row)
        if not cells:
            continue
        hospital_link = next(
            (
                anchor for anchor in descendants(cells[0], "a")
                if re.fullmatch(r"#h\d+", anchor.attrs.get("href", ""))
            ),
            None,
        )
        if hospital_link is None:
            continue
        pfi = hospital_link.attrs["href"][2:]
        city_node = next(
            (
                node for node in descendants(cells[0], "div")
                if {"small", "muted"}.issubset(node.attrs.get("class", "").split())
            ),
            None,
        )
        if city_node is None:
            raise SystemExit(f"No city listed in report summary for {pfi}")
        locations[pfi] = text(city_node)
    return locations


def report_languages(root):
    languages = {}
    for table in descendants(root, "table"):
        rows = list(descendants(table, "tr"))
        header = next(
            (
                [text(child).lower() for child in row.children if isinstance(child, Node) and child.tag == "th"]
                for row in rows
                if any(isinstance(child, Node) and child.tag == "th" for child in row.children)
            ),
            [],
        )
        if "languages" not in header:
            continue
        language_index = header.index("languages")
        for row in rows:
            cells = direct_cells(row)
            if len(cells) <= language_index:
                continue
            hospital_link = next(
                (
                    anchor for anchor in descendants(cells[0], "a")
                    if re.fullmatch(r"#h\d+", anchor.attrs.get("href", ""))
                ),
                None,
            )
            if hospital_link is None:
                continue
            names = [name.strip() for name in text(cells[language_index]).split(";") if name.strip()]
            languages[hospital_link.attrs["href"][2:]] = [
                {"doc_type": "application", "language_code": name}
                for name in names
            ]
        break
    return languages


def merge_records(existing, incoming, key):
    incoming_by_key = {record[key]: record for record in incoming}
    existing_keys = {record[key] for record in existing}
    merged = [incoming_by_key.get(record[key], record) for record in existing]
    merged.extend(record for record in incoming if record[key] not in existing_keys)
    return merged


def assessment_key(assessment):
    scope = assessment["scope"]
    return (
        assessment["audit_round"],
        assessment["criterion_code"],
        scope["type"],
        scope["id"],
    )


def merge_assessments(existing, incoming, package_ids, pfis, replaced_document_ids):
    incoming_by_key = {assessment_key(record): record for record in incoming}
    merged = []
    used_keys = set()
    for record in existing:
        is_updated = (
            record["scope"]["id"] in package_ids | pfis
            or record["evidence_document_id"] in replaced_document_ids
        )
        key = assessment_key(record)
        if not is_updated:
            merged.append(record)
        elif key in incoming_by_key:
            merged.append(incoming_by_key[key])
            used_keys.add(key)
    merged.extend(record for key, record in incoming_by_key.items() if key not in used_keys)
    return merged


def merge_report(existing, incoming):
    incoming_pfis = {facility["pfi"] for facility in incoming["facilities"]}
    incoming_package_ids = {facility["package_id"] for facility in incoming["facilities"]}
    incoming_document_ids = {document["document_id"] for document in incoming["documents"]}
    old_facilities = {facility["pfi"]: facility for facility in existing["facilities"]}
    old_document_ids = {
        document["document_id"] for document in existing["documents"]
        if document["package_id"] in incoming_package_ids
    }

    for facility in incoming["facilities"]:
        old = old_facilities.get(facility["pfi"])
        if old is None:
            continue
        for field in ("address", "zip", "county", "ocn", "ccn", "system_id", "phone", "coordinates"):
            if not facility[field]:
                facility[field] = old.get(field)

    return {
        **existing,
        **incoming,
        "systems": existing["systems"],
        "operators": existing["operators"],
        "criteria": incoming["criteria"],
        "facilities": merge_records(existing["facilities"], incoming["facilities"], "pfi"),
        "packages": merge_records(existing["packages"], incoming["packages"], "package_id"),
        "documents": merge_records(
            [
                record for record in existing["documents"]
                if record["package_id"] not in incoming_package_ids
                or record["document_id"] in incoming_document_ids
            ],
            incoming["documents"],
            "document_id",
        ),
        "facility_psa": [
            record for record in existing["facility_psa"] if record["facility_pfi"] not in incoming_pfis
        ] + incoming["facility_psa"],
        "assessments": merge_assessments(
            existing["assessments"],
            incoming["assessments"],
            incoming_package_ids,
            incoming_pfis,
            old_document_ids,
        ),
        "grade_results": merge_records(existing["grade_results"], incoming["grade_results"], "package_id"),
    }


def document_type(code, url):
    if code in APPLICATION_CODES:
        return "application"
    if code == "pls_posted" or code.startswith("pls_"):
        return "pls"
    if code == "policy_statement_posted":
        return "policy_statement"
    url = (url or "").lower()
    if "application" in url or "uniform" in url:
        return "application"
    if "summary" in url:
        return "pls"
    return "policy_statement"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/import-report.py /path/to/report.html")
    source = Path(sys.argv[1])
    parser = ReportParser()
    parser.feed(source.read_text())
    hospitals = [
        node for node in descendants(parser.root, "details")
        if re.fullmatch(r"h\d+", node.attrs.get("id", ""))
    ]
    if not hospitals:
        raise SystemExit("No hospital records found in report")
    hospital_ids = [hospital.attrs["id"][1:] for hospital in hospitals]
    if len(hospital_ids) != len(set(hospital_ids)):
        raise SystemExit("Report contains duplicate hospital IDs")

    base = json.loads((ROOT / "src/api/mock/data/generated.json").read_text())
    destination = ROOT / "src/api/mock/data/report.json"
    existing = json.loads(destination.read_text()) if destination.exists() else None
    facilities, packages, documents, assessments, grade_results = [], [], [], [], []
    seen_documents = {}
    audit_round = "2026-11"
    generated_date = re.search(r"\bgenerated\s+(\d{4}-\d{2}-\d{2})\b", text(parser.root))
    if not generated_date:
        raise SystemExit("Could not find the report generation date")
    report_date = generated_date.group(1)
    locations = report_locations(parser.root)
    languages_by_pfi = report_languages(parser.root)

    for hospital in hospitals:
        pfi = hospital.attrs["id"][1:]
        package_id = f"report-{pfi}"
        summary = next(descendants(hospital, "summary"))
        match = re.search(
            r"^(.*?)\s*·\s*([ABCDF])\s*·\s*(graded|provisional)\s*·\s*(\d+) not met,\s*(\d+) open$",
            text(summary),
        )
        if not match:
            raise SystemExit(f"Could not parse published summary for {pfi}: {text(summary)!r}")
        name, grade, status, not_met, open_count = match.groups()
        address = HOSPITAL_ADDRESSES.get(name.strip())
        street, zip_code, latitude, longitude = ("", "", None, None) if address is None else (
            address[0], address[2], address[3], address[4],
        )
        city = locations.get(pfi)
        if not city:
            raise SystemExit(f"No city is configured for hospital {pfi} ({name.strip()})")
        links = list(descendants(hospital, "a"))
        landing_url = links[0].attrs.get("href") if links else None
        facilities.append({
            "pfi": pfi, "name": name.strip(), "address": street,
            "city": city, "county": "",
            "state": "NY", "zip": zip_code, "ocn": "", "ccn": "", "system_id": None,
            "package_id": package_id, "phone": None,
            "coordinates": [latitude, longitude] if latitude is not None and longitude is not None else None,
        })
        packages.append({
            "package_id": package_id, "owner_system_id": None, "landing_url": landing_url,
            "languages": languages_by_pfi.get(pfi, []),
        })

        table = next(descendants(hospital, "table"))
        for row in descendants(table, "tr"):
            cells = direct_cells(row)
            if len(cells) < 2:
                continue
            label = "".join(child for child in cells[0].children if isinstance(child, str)).strip()
            code = LABEL_TO_CODE.get(label)
            if not code:
                continue
            result_cell = cells[1]
            status_node = next(
                (
                    child for child in result_cell.children
                    if isinstance(child, Node)
                    and child.tag == "div"
                    and (
                        set(child.attrs.get("class", "").split()) & {"met", "notmet", "open"}
                        or text(child).startswith(("YES", "NO", "OPEN", "UNCLEAR", "NOT_FOUND"))
                    )
                ),
                None,
            )
            fallback_status = next(
                (child for child in result_cell.children if isinstance(child, Node) and child.tag == "div"),
                None,
            )
            result_text = text(status_node or fallback_status) if status_node or fallback_status else ""
            status_classes = set(status_node.attrs.get("class", "").split()) if status_node else set()
            if "open" in status_classes or result_text.startswith(("OPEN", "UNCLEAR", "NOT_FOUND")):
                result = "needs_review"
            elif "notmet" in status_classes or result_text.startswith("NO"):
                result = "fail"
            elif "met" in status_classes or result_text.startswith("YES"):
                result = "pass"
            else:
                raise SystemExit(f"Unknown result for {pfi} / {label}: {result_text!r}")

            divs = [
                child for child in result_cell.children
                if isinstance(child, Node) and child.tag == "div"
            ]
            rationale = next(
                (text(child) for child in divs if child is not status_node and text(child)),
                None,
            )
            quote_node = next(
                (child for child in result_cell.children if isinstance(child, Node) and child.tag == "blockquote"),
                None,
            )
            quote = text(quote_node, ("a", "span")) if quote_node else None
            if quote:
                quote = re.sub(r"\s*document\s*$", "", quote).strip().strip("“”\"") or None
            evidence_url = next(
                (
                    anchor.attrs.get("href")
                    for anchor in descendants(quote_node, "a")
                    if anchor.attrs.get("href")
                ),
                None,
            ) if quote_node else None

            document_id = None
            if evidence_url:
                key = (package_id, evidence_url)
                if key not in seen_documents:
                    document_id = f"{package_id}-doc-{sum(doc['package_id'] == package_id for doc in documents) + 1}"
                    seen_documents[key] = document_id
                    documents.append({
                        "document_id": document_id, "package_id": package_id,
                        "doc_type": document_type(code, evidence_url), "url": evidence_url,
                        "retrieved_at": report_date, "archive_path": None,
                        "is_uniform_app": False, "pages_missing": None, "fpl_year_stated": None,
                        "fpl_region": None, "facts": [],
                    })
                else:
                    document_id = seen_documents[key]

            criterion = next((item for item in base["criteria"] if item["code"] == code), None)
            if code == "psa_2007_compliant":
                scope = {"type": "facility", "id": pfi}
            elif criterion and criterion["evaluates"] == "document" and document_id:
                scope = {"type": "document", "id": document_id}
            else:
                scope = {"type": "package", "id": package_id}
            assessments.append({
                "audit_round": audit_round, "criterion_code": code, "scope": scope,
                "result": result, "measured_value": None,
                "evidence_document_id": document_id, "evidence_quote": quote,
                "is_judgment_call": False, "rationale": rationale,
                "reviewer": None, "reviewed_at": None,
            })

        grade_results.append({
            "package_id": package_id, "audit_round": audit_round,
            "rubric_version": "report-v5", "grade": grade,
            "noncompliant_count": int(not_met), "auto_fail": False, "computed": False,
            "note": "Published report grade; evaluation statuses are preserved from the report.",
            "report_status": status, "open_count": int(open_count),
        })

    criteria = base["criteria"] + [{
        "code": "application_languages", "section": "application", "evaluates": "document",
        "value_type": "boolean",
        "rule": "Supplemental report outcome; not included in the published grade",
        "is_auto_fail": False, "excluded_from_grade": True,
    }]
    incoming = {
        "audit_round": audit_round, "rubric_version": "report-v5", "criteria": criteria,
        "systems": [], "operators": [], "facilities": facilities, "packages": packages,
        "documents": documents, "facility_psa": [], "assessments": assessments,
        "grade_results": grade_results,
    }
    existing_pfis = {facility["pfi"] for facility in existing["facilities"]} if existing else set()
    output = merge_report(existing, incoming) if existing else incoming
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    distribution = {grade: sum(item["grade"] == grade for item in grade_results) for grade in "ABCDF"}
    statuses = {status: sum(item["report_status"] == status for item in grade_results) for status in ("graded", "provisional")}
    new_count = len(set(hospital_ids) - existing_pfis) if existing else len(facilities)
    print(
        f"Updated {len(facilities) - new_count} existing hospitals and added {new_count} new hospitals; "
        f"dataset now has {len(output['facilities'])} hospitals and {len(output['assessments'])} criterion results at {destination}"
    )
    print(f"Incoming published grades: {distribution}; report statuses: {statuses}")


if __name__ == "__main__":
    main()
