"""H4 deterministic year-stratified dev/holdout split.

Rules:
- every year contributes >=1 holdout doc when it has >=1 sanction doc
- target ~20% holdout per year (ceil), chosen by lowest sha256(boe_id)
- fully deterministic — same input => same split
"""
import hashlib
import json
import math
from pathlib import Path


def stratified_split(ids_by_year):
    dev, holdout = {}, {}
    for year, ids in sorted(ids_by_year.items()):
        ranked = sorted(ids, key=lambda b: hashlib.sha256(b.encode()).hexdigest())
        k = max(1, math.ceil(len(ranked) * 0.2)) if ranked else 0
        holdout[year] = ranked[:k]
        dev[year] = ranked[k:]
    return dev, holdout


if __name__ == "__main__":
    import sys
    manifest = Path(sys.argv[1])
    stage_dir = Path(sys.argv[2])
    by_year = {}
    for ln in manifest.read_text(encoding="utf-8").splitlines():
        for it in json.loads(ln).get("items", []):
            if it.get("sanction_like"):
                by_year.setdefault(it["boe_id"][6:10], []).append(it["boe_id"])
    for y, ids in by_year.items():
        by_year[y] = sorted({b for b in ids if (stage_dir / f"{b}.xml").exists()})
    dev, holdout = stratified_split(by_year)
    for y in sorted(by_year):
        print(f"{y}: total={len(by_year[y])} dev={len(dev[y])} holdout={len(holdout[y])}")
    out = Path("data/runtime/h4_split.json")
    out.write_text(json.dumps({"dev": dev, "holdout": holdout}, indent=2))
    print("->", out)
