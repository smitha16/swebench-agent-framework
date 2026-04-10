#!/usr/bin/env python3
"""
Download SWE-bench Lite and select 10 diverse instances.
Saves instance metadata and updates the config.
"""

import json
import yaml
import random
from pathlib import Path
from datasets import load_dataset

# 10 hand-picked instances across different repos and difficulty levels.
# These are well-known SWE-bench Lite instances that are commonly used.
# You can replace these with any valid instance IDs.
CURATED_INSTANCE_IDS = [
    "astropy__astropy-12907",
    "django__django-11099",
    "django__django-13230",
    "django__django-14608",
    "matplotlib__matplotlib-23562",
    "pydata__xarray-3364",
    "pytest-dev__pytest-7168",
    "scikit-learn__scikit-learn-13779",
    "sphinx-doc__sphinx-8595",
    "sympy__sympy-18087",
]


def main():
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    print("Downloading SWE-bench Lite...")
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    print(f"  Total instances: {len(ds)}")

    # Index by instance_id
    all_instances = {row["instance_id"]: row for row in ds}

    # Try curated list first, fall back to random selection
    selected_ids = []
    for iid in CURATED_INSTANCE_IDS:
        if iid in all_instances:
            selected_ids.append(iid)

    if len(selected_ids) < 10:
        print(f"  Only {len(selected_ids)} curated instances found, adding random ones...")
        remaining = [k for k in all_instances if k not in selected_ids]
        random.seed(42)
        selected_ids.extend(random.sample(remaining, 10 - len(selected_ids)))

    selected_ids = selected_ids[:10]

    print(f"\nSelected {len(selected_ids)} instances:")
    instances = []
    for iid in selected_ids:
        row = all_instances[iid]
        repo = row["repo"]
        print(f"  {iid} ({repo})")
        instances.append({
            "instance_id": row["instance_id"],
            "repo": row["repo"],
            "base_commit": row["base_commit"],
            "problem_statement": row["problem_statement"],
            "hints_text": row.get("hints_text", ""),
            "patch": row["patch"],  # Gold patch (for reference, not given to agent)
            "test_patch": row.get("test_patch", ""),
        })

    # Save instances
    out_path = data_dir / "selected_instances.json"
    with open(out_path, "w") as f:
        json.dump(instances, f, indent=2)
    print(f"\nSaved to {out_path}")

    # Update config
    config_path = Path("configs/default.yaml")
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["selected_instances"] = selected_ids
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
        print(f"Updated {config_path}")


if __name__ == "__main__":
    main()
