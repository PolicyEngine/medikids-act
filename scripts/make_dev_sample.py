"""Write a small sample of the certified dataset, for developing the pipeline.

    python scripts/make_dev_sample.py OUT.h5 [--households 1500] [--seed 0]

The sample keeps whole households and every entity table the engine reads. It
exists so that the pipeline and its checks can be exercised in a few minutes
and a few gigabytes of memory. Numbers from a sample run are never reported.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

LINKS = {
    "household": "person_household_id",
    "tax_unit": "person_tax_unit_id",
    "spm_unit": "person_spm_unit_id",
    "family": "person_family_id",
    "marital_unit": "person_marital_unit_id",
}


def certified_path() -> str:
    """The certified file, which must already be on disk (no surprise download)."""
    from medikids_act.pipeline import require_local_dataset

    return str(require_local_dataset())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out")
    parser.add_argument("--households", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    source = certified_path()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.HDFStore(source, mode="r") as store:
        tables = {key.strip("/"): store[key] for key in store.keys()}  # noqa: SIM118
    household = tables["household"]
    rng = np.random.default_rng(args.seed)
    chosen = rng.choice(household["household_id"].to_numpy(), size=args.households, replace=False)
    person = tables["person"]
    person = person[person["person_household_id"].isin(chosen)]
    sample = {"person": person}
    for entity, link in LINKS.items():
        table = tables[entity]
        sample[entity] = table[table[f"{entity}_id"].isin(person[link].unique())]
    for name, table in tables.items():
        sample.setdefault(name, table)
    with pd.HDFStore(out, mode="w") as store:
        for name, table in sample.items():
            store.put(name, table, format="table")
    print(f"wrote {out}: {len(sample['household'])} households, {len(person)} people")


if __name__ == "__main__":
    main()
