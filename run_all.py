#!/usr/bin/env python3
"""
Run the coding agent on all selected SWE-bench instances and produce
a predictions.json file compatible with SWE-bench evaluation.

Usage:
    python run_all.py
    python run_all.py --instance_file data/selected_instances.json
"""

import argparse
import json
import os
import traceback
from pathlib import Path

from run_single import run_instance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance_file", default="data/selected_instances.json")
    parser.add_argument("--resume", action="store_true", help="Skip already-patched instances")
    args = parser.parse_args()

    config = {
        "base_url": os.environ.get("AGENT_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.environ.get("AGENT_API_KEY", ""),
        "model_name": os.environ.get("AGENT_MODEL", "gpt-4o"),
        "max_steps": int(os.environ.get("AGENT_MAX_STEPS", "30")),
        "temperature": float(os.environ.get("AGENT_TEMPERATURE", "0.2")),
        "workspace_root": "workspaces",
        "log_dir": "logs",
        "patch_dir": "patches",
    }

    if not config["api_key"]:
        print("ERROR: Set AGENT_API_KEY environment variable")
        return

    with open(args.instance_file) as f:
        instances = json.load(f)

    print(f"Running agent on {len(instances)} instances")
    print(f"Model: {config['model_name']}")
    print(f"Max steps: {config['max_steps']}")

    results = []
    predictions = {}  # SWE-bench format: {instance_id: {"model_patch": ..., "model_name_or_path": ...}}

    patch_dir = Path(config["patch_dir"])
    for i, instance in enumerate(instances):
        iid = instance["instance_id"]
        patch_file = patch_dir / f"{iid.replace('/', '__')}.patch"

        if args.resume and patch_file.exists():
            print(f"\n[{i+1}/{len(instances)}] Skipping {iid} (patch exists)")
            with open(patch_file) as f:
                patch = f.read()
            predictions[iid] = {
                "instance_id": iid,
                "model_patch": patch,
                "model_name_or_path": config["model_name"],
            }
            continue

        print(f"\n[{i+1}/{len(instances)}] Running {iid}...")
        try:
            result = run_instance(instance, config)
            results.append(result)
            predictions[iid] = {
                "instance_id": iid,
                "model_patch": result["patch"],
                "model_name_or_path": config["model_name"],
            }
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            traceback.print_exc()
            predictions[iid] = {
                "instance_id": iid,
                "model_patch": "",
                "model_name_or_path": config["model_name"],
            }

    # Save predictions in SWE-bench format
    pred_path = patch_dir / "predictions.json"
    pred_list = list(predictions.values())
    with open(pred_path, "w") as f:
        json.dump(pred_list, f, indent=2)
    print(f"\n{'='*60}")
    print(f"Predictions saved: {pred_path}")

    # Summary
    print(f"\nSummary:")
    print(f"  Total instances: {len(instances)}")
    print(f"  Completed: {len(results)}")
    total_flags = sum(len(r.get("exploit_flags", [])) for r in results)
    print(f"  Total exploit flags: {total_flags}")

    # Save summary
    summary_path = Path("logs") / "run_summary.json"
    summary_path.parent.mkdir(exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Summary: {summary_path}")

    print(f"\nNext step: evaluate with SWE-bench harness:")
    print(f"  python scripts/evaluate.py --predictions {pred_path}")


if __name__ == "__main__":
    main()
