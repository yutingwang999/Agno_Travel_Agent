# Australian place list: sources and licences

`australia.tsv` is the destination guard's place list (`harden-workflow-guardrails`, design decision 6): every accepted destination name, the canonical lowercase English name it maps to, and where the name came from. It is generated; do not edit it by hand. Rebuild it with:

```powershell
python scripts/build_places.py
```

## Sources

| File | Content | Source and licence |
| --- | --- | --- |
| `raw/cities1000.txt` (not in git) | Every place with a population of at least 1,000; the build uses the Australian rows (`country code = AU`) and only their primary name and ASCII name | [GeoNames](https://www.geonames.org/), `cities1000.zip` from <https://download.geonames.org/export/dump/cities1000.zip>, licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Downloaded 2026-10-31; the extracted file is dated 2026-10-30 |
| `states.tsv` | States and territories, with their abbreviations | Written by hand for this project |
| `destinations.tsv` | Tourist destinations that are not towns (Uluru, Great Ocean Road, Great Barrier Reef, Kangaroo Island, …) and common other names (Ayers Rock, Fraser Island) | Written by hand for this project |
| `chinese.tsv` | One Chinese name for each major city, state and destination, in Simplified script and its Traditional-script form (悉尼, 墨尔本 / 墨爾本, 黄金海岸 / 黃金海岸, …) | Written by hand for this project |

The place list contains place names from GeoNames (CC BY 4.0). Attribution: "Contains data from GeoNames (https://www.geonames.org/), licensed under CC BY 4.0. Modified: only Australian places are used, names are lowercased, and the list is combined with hand-kept lists written for this project."

## How the list is built

- GeoNames alternate names are not used: they include romanisations from other languages ("part" and "pet" for Perth, "gold" for Gold Coast) that would let non-place input through.
- A name in a hand-kept list overrides a GeoNames name. Among GeoNames places with the same name, the most populous one gives the canonical name (both Perths map to `perth` anyway).
- The country name itself ("Australia", 澳大利亚, 澳洲) is not in the list: a request for "Australia" is too vague to plan, and is rejected with `destination_out_of_scope`.
- Lookup (`app.workflow.places.canonical_destination`) lowercases the destination, collapses whitespace, and, when the full name is not found, drops trailing state, territory or country qualifiers ("Perth, WA, Australia" → `perth`).

## Known limits

- Places under 1,000 people that are not in a hand-kept list are rejected (roadmap items 3 and 4 can replace the list).
- Bare "维多利亚" is not listed (it also names places outside Australia); "维多利亚州" is.
- Each place has one Chinese name (in Simplified and Traditional script); other translations of the same place are not listed, so a request using one is rejected.

## Updating

Download a newer `cities1000.zip`, extract `cities1000.txt` to `raw/`, run the build, update the download date above, and review the diff of `australia.tsv` before committing.
