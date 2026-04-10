#!/usr/bin/env python3
"""
Evaluate agent patches using the SWE-bench Docker harness.

Prerequisites:
    - Docker installed and running
    - pip install swebench

Usage:
    python scripts/evaluate.py --predictions patches/predictions.json
    python scripts/evaluate.py --predictions patches/predictions.json --run_id my_experiment
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_swebench_eval(predictions_path: str, run_id: str = "agent_eval"):
    """Run SWE-bench evaluation harness."""
    print(f"Running SWE-bench evaluation...")
    print(f"  Predictions: {predictions_path}")
    print(f"  Run ID: {run_id}")
    print()

    # Verify Docker
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Docker is not running. SWE-bench evaluation requires Docker.")
        print("Install Docker and ensure it's running, then retry.")
        sys.exit(1)

    # Run evaluation
    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--predictions_path", predictions_path,
        "--swe_bench_tasks", "princeton-nlp/SWE-bench_Lite",
        "--run_id", run_id,
        "--log_level", "INFO",
    ]

    print(f"Command: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\nEvaluation failed with exit code {e.returncode}")
        print("Check that swebench is installed: pip install swebench")
        sys.exit(1)

    # Parse results
    results_dir = Path(f"logs/run_evaluation/{run_id}")
    if results_dir.exists():
        print(f"\nResults directory: {results_dir}")
        parse_results(results_dir, predictions_path)
    else:
        print(f"\nResults directory not found at {results_dir}")
        print("Check SWE-bench output for the actual results location.")


def parse_results(results_dir: Path, predictions_path: str):
    """Parse evaluation results and print summary with exploit analysis."""
    # Load predictions for cross-referencing
    with open(predictions_path) as f:
        predictions = json.load(f)
    pred_ids = {p["instance_id"] for p in predictions}

    # Find result files
    resolved = set()
    for json_file in results_dir.rglob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            if isinstance(data, dict) and "resolved" in data:
                resolved = set(data["resolved"])
                break
        except (json.JSONDecodeError, KeyError):
            continue

    print(f"\n{'='*60}")
    print(f"EVALUATION RESULTS")
    print(f"{'='*60}")
    print(f"  Total instances:  {len(pred_ids)}")
    print(f"  Resolved (hidden tests pass): {len(resolved)}")
    print(f"  Hidden pass rate: {len(resolved)/max(len(pred_ids),1):.1%}")

    # Cross-reference with trajectory logs for exploit analysis
    log_dir = Path("logs")
    exploit_summary = []
    for iid in pred_ids:
        traj_file = log_dir / f"{iid}.json"
        if traj_file.exists():
            with open(traj_file) as f:
                traj = json.load(f)
            flags = traj.get("exploit_flags", [])
            hidden_pass = 1.0 if iid in resolved else 0.0
            exploit_summary.append({
                "instance_id": iid,
                "resolved": iid in resolved,
                "exploit_flags": flags,
                "num_steps": len(traj.get("steps", [])),
            })

    if exploit_summary:
        print(f"\nPer-instance breakdown:")
        for es in exploit_summary:
            status = "✓" if es["resolved"] else "✗"
            flags = f" ⚠ {len(es['exploit_flags'])} flags" if es["exploit_flags"] else ""
            print(f"  {status} {es['instance_id']} ({es['num_steps']} steps){flags}")

        flagged = [e for e in exploit_summary if e["exploit_flags"]]
        if flagged:
            print(f"\nExploit flags detected in {len(flagged)} instances:")
            for e in flagged:
                print(f"  {e['instance_id']}:")
                for f in e["exploit_flags"]:
                    print(f"    - {f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, help="Path to predictions.json")
    parser.add_argument("--run_id", default="agent_eval", help="Evaluation run ID")
    args = parser.parse_args()

    run_swebench_eval(args.predictions, args.run_id)


if __name__ == "__main__":
    main()
