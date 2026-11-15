"""Find map coordinates for every hospital in the hospital table (all 211), once.

Run by hand from the repository root:  uv run python frontend/scripts/geocode-hospitals.py

Reads data/hospitals.csv (street, city, zip; git-ignored) and sends only street, city, state and zip, under a
row number (no hospital name or id), to the US Census Bureau's free batch geocoder. Writes
frontend/scripts/hospital-locations.csv (hospital_id, latitude, longitude, source, match). Add-only: a hospital
already in that file is never looked up again, so a coordinate fixed by hand stays fixed. Prints counts only.
"""

import csv
import io
import sys
from pathlib import Path

import httpx
import truststore

truststore.inject_into_ssl()

REPO = Path(__file__).resolve().parents[2]
HOSPITALS = REPO / "data" / "hospitals.csv"
OUT = Path(__file__).resolve().parent / "hospital-locations.csv"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
FIELDS = ["hospital_id", "latitude", "longitude", "source", "match"]
# New York State, with a margin: a match outside this box is treated as no match.
NY_BOX = (40.4, 45.1, -79.9, -71.7)


def main():
    with HOSPITALS.open(encoding="utf-8-sig", newline="") as handle:
        hospitals = list(csv.DictReader(handle))
    done = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8", newline="") as handle:
            done = {row["hospital_id"]: row for row in csv.DictReader(handle)}
    todo = [row for row in hospitals if row["hospital_id"].strip() not in done]
    print(f"{len(hospitals)} hospitals; {len(done)} already located; looking up {len(todo)}")
    if not todo:
        return

    # Row numbers stand in for hospital ids in what is sent.
    upload = io.StringIO()
    writer = csv.writer(upload)
    for number, row in enumerate(todo):
        writer.writerow([number, row["address"].strip(), row["city"].strip(), "NY", row["zip"].strip()[:5]])
    response = httpx.post(
        CENSUS_URL,
        data={"benchmark": "Public_AR_Current"},
        files={"addressFile": ("addresses.csv", upload.getvalue(), "text/csv")},
        headers={"User-Agent": "hfal-monitor/0.1"},
        timeout=300,
    )
    response.raise_for_status()

    found = {}
    counts = {"Match": 0, "No_Match": 0, "Tie": 0, "outside NY": 0}
    for record in csv.reader(io.StringIO(response.text)):
        if len(record) < 3:
            continue
        number, status = int(record[0]), record[2]
        if status != "Match":
            counts[status] = counts.get(status, 0) + 1
            continue
        lon, lat = (float(x) for x in record[5].split(","))
        if not (NY_BOX[0] <= lat <= NY_BOX[1] and NY_BOX[2] <= lon <= NY_BOX[3]):
            counts["outside NY"] += 1
            continue
        counts["Match"] += 1
        found[number] = {"latitude": f"{lat:.6f}", "longitude": f"{lon:.6f}", "source": "census", "match": record[3]}

    for number, row in enumerate(todo):
        if number in found:
            done[row["hospital_id"].strip()] = {"hospital_id": row["hospital_id"].strip(), **found[number]}
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for hospital_id in sorted(done, key=lambda x: int(x) if x.isdigit() else 0):
            writer.writerow(done[hospital_id])
    exact = sum(1 for item in found.values() if item["match"] == "Exact")
    print(f"Census: {counts}; exact {exact}, approximate {len(found) - exact}")
    print(f"{len(done)} of {len(hospitals)} hospitals now located; {len(hospitals) - len(done)} still without coordinates")


if __name__ == "__main__":
    sys.exit(main())
