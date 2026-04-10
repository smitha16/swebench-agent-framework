#!/usr/bin/env python3
"""
Run the coding agent on a single SWE-bench instance.

Usage:
    python run_single.py --instance_id django__django-11099
    python run_single.py --instance_file data/selected_instances.json --index 0
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from agent import CodingAgent, TrajectoryLogger, ExploitDetector


def setup_workspace(instance: dict, workspace_root: str) -> str:
    """Clone the repo at the correct commit and return workspace path."""
    iid = instance["instance_id"]
    repo = instance["repo"]
    commit = instance["base_commit"]
    workspace = os.path.join(workspace_root, iid.replace("/", "__"))

    if os.path.exists(workspace):
        print(f"  Workspace exists, cleaning: {workspace}")
        shutil.rmtree(workspace)

    print(f"  Cloning {repo} @ {commit[:8]}...")
    repo_url = f"https://github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--quiet", repo_url, workspace],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-q", commit],
        cwd=workspace,
        check=True,
        capture_output=True,
    )

    return workspace


def run_instance(instance: dict, config: dict) -> dict:
    """Run the agent on one instance and return results."""
    iid = instance["instance_id"]
    print(f"\n{'='*60}")
    print(f"Instance: {iid}")
    print(f"{'='*60}")

    # Setup workspace
    workspace_root = config.get("workspace_root", "workspaces")
    workspace = setup_workspace(instance, workspace_root)

    # Initialize logger
    logger = TrajectoryLogger(
        instance_id=iid,
        model=config["model_name"],
        log_dir=config.get("log_dir", "logs"),
    )

    # Initialize agent
    agent = CodingAgent(
        base_url=config["base_url"],
        api_key=config["api_key"],
        model=config["model_name"],
        workspace=workspace,
        logger=logger,
        max_steps=config.get("max_steps", 30),
        temperature=config.get("temperature", 0.2),
    )

    # Run
    issue_text = instance["problem_statement"]
    patch = agent.run(issue_text)

    # Detect exploits
    detector = ExploitDetector()
    flags = detector.analyze(logger)
    if flags:
        print(f"  ⚠ Exploit flags: {flags}")
    else:
        print(f"  ✓ No exploit flags detected")

    # Save trajectory
    log_path = logger.save()
    print(f"  Trajectory saved: {log_path}")

    # Save patch
    patch_dir = Path(config.get("patch_dir", "patches"))
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_file = patch_dir / f"{iid.replace('/', '__')}.patch"
    with open(patch_file, "w") as f:
        f.write(patch)
    print(f"  Patch saved: {patch_file}")

    return {
        "instance_id": iid,
        "model": config["model_name"],
        "patch": patch,
        "exploit_flags": flags,
        "num_steps": len(logger.trajectory.steps),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance_id", type=str, help="Single instance ID")
    parser.add_argument("--instance_file", type=str, default="data/selected_instances.json")
    parser.add_argument("--index", type=int, default=0, help="Index in instance file")
    args = parser.parse_args()

    # Load config from env
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

    # Load instance
    if args.instance_id:
        with open(args.instance_file) as f:
            instances = json.load(f)
        instance = next(
            (i for i in instances if i["instance_id"] == args.instance_id), None
        )
        if not instance:
            print(f"Instance {args.instance_id} not found in {args.instance_file}")
            return
    else:
        with open(args.instance_file) as f:
            instances = json.load(f)
        instance = instances[args.index]

    result = run_instance(instance, config)
    print(f"\nResult: {json.dumps(result, indent=2, default=str)}")


if __name__ == "__main__":
    main()
