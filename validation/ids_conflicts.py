"""Static analysis of the original IDS: finds specifications whose requirements
cannot be satisfied at the same time by one entity.  The IDS file is read,
never modified.

Two specifications A and B conflict for an entity when the entity is applicable
to both (same entity + predefined type, no further applicability filters) and
* both require the same attribute with different fixed values, or
* both require a partOf relation of the same relation type to entities that
  exclude each other (different entity or different predefined type), where
  the relation admits only one parent (IfcRelContainedInSpatialStructure,
  IfcRelAggregates).

    python validation/ids_conflicts.py [--ids input/Branschutmaningen_2026.ids]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from itertools import combinations
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import repo_path  # noqa: E402

NS = {"ids": "http://standards.buildingsmart.org/IDS", "xs": "http://www.w3.org/2001/XMLSchema"}
SINGLE_PARENT = {"IFCRELCONTAINEDINSPATIALSTRUCTURE", "IFCRELAGGREGATES"}


def _simple(el: Optional[ET.Element]) -> Optional[str]:
    if el is None:
        return None
    sv = el.find("ids:simpleValue", NS)
    if sv is not None:
        return sv.text
    enums = [e.get("value") for e in el.iter("{%s}enumeration" % NS["xs"])]
    return "|".join(enums) if enums else None


def parse(path: str) -> List[Dict]:
    root = ET.parse(path).getroot()
    specs = []
    for sp in root.find("ids:specifications", NS):
        app = sp.find("ids:applicability", NS)
        ent = app.find("ids:entity", NS)
        key = (_simple(ent.find("ids:name", NS)), _simple(ent.find("ids:predefinedType", NS)))
        extra_app = [c.tag.split("}")[1] for c in app if c.tag.split("}")[1] != "entity"]
        attrs, partofs = {}, []
        for req in sp.find("ids:requirements", NS):
            tag = req.tag.split("}")[1]
            if tag == "attribute":
                name = _simple(req.find("ids:name", NS))
                val = _simple(req.find("ids:value", NS))
                if val is not None and "|" not in val:
                    attrs[name] = val
            elif tag == "partOf":
                pe = req.find("ids:entity", NS)
                partofs.append((req.get("relation"), _simple(pe.find("ids:name", NS)),
                                _simple(pe.find("ids:predefinedType", NS))))
        specs.append({"name": sp.get("name"), "applicability": key, "extra_applicability": extra_app,
                      "attributes": attrs, "partof": partofs})
    return specs


def find_conflicts(specs: List[Dict]) -> List[Dict]:
    out = []
    for a, b in combinations(specs, 2):
        if a["applicability"] != b["applicability"] or a["extra_applicability"] or b["extra_applicability"]:
            continue
        reasons = []
        for k in set(a["attributes"]) & set(b["attributes"]):
            if a["attributes"][k] != b["attributes"][k]:
                reasons.append("attribute %s: %r vs %r" % (k, a["attributes"][k], b["attributes"][k]))
        for ra in a["partof"]:
            for rb in b["partof"]:
                if ra[0] == rb[0] and ra[0] in SINGLE_PARENT and (ra[1], ra[2]) != (rb[1], rb[2]):
                    if ra[1] == rb[1] and (ra[2] is None or rb[2] is None):
                        continue  # one is a generalisation of the other
                    reasons.append("%s parent %s.%s vs %s.%s" % (ra[0], ra[1], ra[2], rb[1], rb[2]))
        if reasons:
            out.append({"spec_a": a["name"], "spec_b": b["name"], "applicability": "%s.%s" % a["applicability"],
                        "reasons": reasons})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=repo_path("input/Branschutmaningen_2026.ids"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    conflicts = find_conflicts(parse(args.ids))
    text = json.dumps(conflicts, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return conflicts


if __name__ == "__main__":
    main()
