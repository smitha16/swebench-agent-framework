#!/usr/bin/env python3
"""
Validate agent patches against SWE-bench gold tests.

For each instance:
1. Apply the agent's patch to the repo
2. Apply the gold test patch (hidden tests the agent never saw)
3. Run the tests
4. Report pass/fail

Usage:
    python scripts/validate.py --instance_id astropy__astropy-12907
    python scripts/validate.py --all
"""

import argparse
import json
import subprocess
import os
import shutil
from pathlib import Path


def run_cmd(cmd, cwd=None, timeout=120):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def validate_instance(instance: dict, patch_dir: str, workspace_root: str) -> dict:
    """Validate one instance: apply agent patch + gold tests, run tests."""
    iid = instance["instance_id"]
    repo = instance["repo"]
    commit = instance["base_commit"]
    test_patch = instance.get("test_patch", "")
    gold_patch = instance.get("patch", "")

    print(f"\n{'='*60}")
    print(f"Validating: {iid}")
    print(f"{'='*60}")

    # Check if agent produced a patch
    patch_file = Path(patch_dir) / f"{iid.replace('/', '__')}.patch"
    if not patch_file.exists():
        print(f"  ✗ No agent patch found")
        return {"instance_id": iid, "status": "no_patch"}

    agent_patch = patch_file.read_text()
    if "(no changes detected)" in agent_patch or "(no output)" in agent_patch:
        print(f"  ✗ Agent made no changes")
        return {"instance_id": iid, "status": "no_changes"}

    # Setup workspace
    workspace = os.path.join(workspace_root, f"validate_{iid.replace('/', '__')}")
    if os.path.exists(workspace):
        shutil.rmtree(workspace)

    print(f"  Cloning {repo}...")
    rc, _, err = run_cmd(f"git clone --quiet https://github.com/{repo}.git {workspace}")
    if rc != 0:
        print(f"  ✗ Clone failed: {err[:200]}")
        return {"instance_id": iid, "status": "clone_failed"}

    run_cmd(f"git checkout -q {commit}", cwd=workspace)

    # Step 1: Apply agent's patch
    print(f"  Applying agent patch...")
    agent_patch_file = os.path.join(workspace, "agent.patch")
    with open(agent_patch_file, "w") as f:
        f.write(agent_patch)
    rc, out, err = run_cmd("git apply --verbose agent.patch", cwd=workspace)
    if rc != 0:
        # Try with less strict mode
        rc, out, err = run_cmd("git apply --reject agent.patch", cwd=workspace)
        if rc != 0:
            print(f"  ✗ Agent patch failed to apply")
            print(f"    {err[:200]}")
            return {"instance_id": iid, "status": "patch_failed"}

    print(f"  ✓ Agent patch applied")

    # Step 2: Apply gold test patch (these are the hidden tests)
    if test_patch:
        print(f"  Applying gold test patch...")
        test_patch_file = os.path.join(workspace, "test.patch")
        with open(test_patch_file, "w") as f:
            f.write(test_patch)
        rc, out, err = run_cmd("git apply --verbose test.patch", cwd=workspace)
        if rc != 0:
            rc, out, err = run_cmd("git apply --reject test.patch", cwd=workspace)
            if rc != 0:
                print(f"  ⚠ Gold test patch failed to apply (conflicts with agent patch?)")
                return {"instance_id": iid, "status": "test_patch_conflict"}
        print(f"  ✓ Gold test patch applied")

    # Step 3: Find and run relevant tests
    # Extract test file paths from the test patch
    test_files = []
    for line in test_patch.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 3:
                path = parts[2].lstrip("a/")
                if "test" in path.lower():
                    test_files.append(path)

    if not test_files:
        print(f"  ⚠ No test files found in gold test patch")
        return {"instance_id": iid, "status": "no_test_files"}

    print(f"  Running tests: {test_files}")

    # Try pytest first, fall back to unittest
    test_paths = " ".join(test_files)
    rc, out, err = run_cmd(
        f"python -m pytest {test_paths} -x --tb=short -q",
        cwd=workspace, timeout=180,
    )

    # Parse results
    passed = "passed" in out and "failed" not in out and rc == 0
    output_summary = out[-500:] if len(out) > 500 else out

    if passed:
        print(f"  ✓ TESTS PASSED — Agent's fix is correct!")
    else:
        print(f"  ✗ TESTS FAILED")
        print(f"    {output_summary[:300]}")

    # Step 4: Also check how gold patch does (for comparison)
    print(f"\n  --- Comparing with gold patch ---")
    run_cmd(f"git checkout -q {commit}", cwd=workspace)
    gold_patch_file = os.path.join(workspace, "gold.patch")
    with open(gold_patch_file, "w") as f:
        f.write(gold_patch)
    run_cmd("git apply gold.patch", cwd=workspace)

    # Re-apply test patch
    if test_patch:
        test_patch_file2 = os.path.join(workspace, "test2.patch")
        with open(test_patch_file2, "w") as f:
            f.write(test_patch)
        run_cmd("git apply test2.patch", cwd=workspace)

    rc_gold, out_gold, _ = run_cmd(
        f"python -m pytest {test_paths} -x --tb=short -q",
        cwd=workspace, timeout=180,
    )
    gold_passed = "passed" in out_gold and "failed" not in out_gold and rc_gold == 0
    print(f"  Gold patch: {'✓ PASSED' if gold_passed else '✗ FAILED'}")

    return {
        "instance_id": iid,
        "status": "validated",
        "agent_passed": passed,
        "gold_passed": gold_passed,
        "agent_output": output_summary[:500],
        "test_files": test_files,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance_id", type=str, help="Validate one instance")
    parser.add_argument("--all", action="store_true", help="Validate all instances")
    parser.add_argument("--instance_file", default="data/selected_instances.json")
    parser.add_argument("--patch_dir", default="patches")
    parser.add_argument("--workspace_root", default="workspaces")
    args = parser.parse_args()

    with open(args.instance_file) as f:
        instances = json.load(f)

    if args.instance_id:
        instances = [i for i in instances if i["instance_id"] == args.instance_id]
        if not instances:
            print(f"Instance {args.instance_id} not found")
            return
    elif not args.all:
        print("Specify --instance_id or --all")
        return

    results = []
    for inst in instances:
        result = validate_instance(inst, args.patch_dir, args.workspace_root)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*60}")

    for r in results:
        iid = r["instance_id"]
        status = r.get("status", "unknown")
        if status == "validated":
            agent = "✓" if r["agent_passed"] else "✗"
            gold = "✓" if r["gold_passed"] else "✗"
            print(f"  {iid}: Agent {agent}  Gold {gold}")
        else:
            print(f"  {iid}: {status}")

    validated = [r for r in results if r.get("status") == "validated"]
    if validated:
        agent_pass = sum(1 for r in validated if r["agent_passed"])
        print(f"\n  Agent pass rate: {agent_pass}/{len(validated)}")
        print(f"  (This is H — hidden test correctness in your reward formula)")

    # Save results
    out_path = Path("logs") / "validation_results.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full results: {out_path}")


if __name__ == "__main__":
    main()