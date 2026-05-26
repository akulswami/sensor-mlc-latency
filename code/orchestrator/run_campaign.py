#!/usr/bin/env python3
"""run_campaign.py
================

Campaign-level driver for the v7.5+ confirmatory latency experiment.
Per pre-reg amendment v7.8 (2026-05-26, Zenodo DOI 10.5281/zenodo.20401819):

- Reads block-order seed from code/analysis/block_order_seed.txt
- Builds 81-block manifest: 9 cells × 9 blocks/cell at 300s each
  - Pipelines: host, mlc, mlc-binary
  - Conditions: idle, i2c-contention, stress
- Shuffles via random.Random(seed) for reproducibility
- Invokes code/orchestrator/run_stress_block.py per block
- Halts on N consecutive failures (default 3)
- Writes campaign_manifest.json with seed, ordering, and per-block results

Usage:
    python3 code/orchestrator/run_campaign.py --campaign-id confirmatory-2026-05-26
    python3 code/orchestrator/run_campaign.py --btest      # 3-block smoke test
"""

import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_FILE = REPO_ROOT / "code" / "analysis" / "block_order_seed.txt"
ORCHESTRATOR = REPO_ROOT / "code" / "orchestrator" / "run_stress_block.py"

PIPELINES = ["host", "mlc", "mlc-binary"]
CONDITIONS = ["idle", "i2c-contention", "stress"]
BLOCKS_PER_CELL = 9          # 9 cells × 9 blocks = 81 blocks (v7.8 Change 2)
BLOCK_DURATION_SEC = 300     # 300s per block (v7.8 Change 2)
CONSECUTIVE_FAILURE_LIMIT = 3  # halt after 3 in a row


def load_seed():
    with open(SEED_FILE) as f:
        return int(f.read().strip())


def build_manifest(seed, btest=False):
    """Return list of dicts representing the block-order manifest.

    For btest mode, returns exactly 3 blocks — one per pipeline, with
    conditions deterministically chosen for coverage (idle, i2c-contention,
    stress in pipeline order). This ensures the smoke test exercises all
    three pipeline binaries before committing to the 7.5-hour campaign.

    For full mode, returns 81 blocks (9 cells × 9 blocks per cell),
    shuffled via random.Random(seed) for reproducibility.
    """
    if btest:
        # Deterministic btest: one block per pipeline, conditions cycling
        # to also cover all 3 stress conditions.
        blocks = []
        for i, pipeline in enumerate(PIPELINES):
            blocks.append({
                "pipeline": pipeline,
                "condition": CONDITIONS[i],
                "block_in_cell": 0,
                "block_id": i + 1,
            })
        return blocks

    # Full campaign: build 9 cells × BLOCKS_PER_CELL each, then shuffle.
    blocks = []
    for pipeline in PIPELINES:
        for condition in CONDITIONS:
            for block_in_cell in range(BLOCKS_PER_CELL):
                blocks.append({
                    "pipeline": pipeline,
                    "condition": condition,
                    "block_in_cell": block_in_cell,
                })
    rng = random.Random(seed)
    rng.shuffle(blocks)

    # Assign block_id: 1-indexed within the campaign
    for i, b in enumerate(blocks, start=1):
        b["block_id"] = i
    return blocks


def run_one_block(block, campaign_id, btest):
    """Invoke run_stress_block.py for one block. Return dict with exit_code, wall_sec."""
    cmd = [
        sys.executable, str(ORCHESTRATOR),
        "--block-id", f"{campaign_id}-b{block['block_id']:03d}",
        "--pipeline", block["pipeline"],
        "--condition", block["condition"],
        "--duration", str(BLOCK_DURATION_SEC),
    ]
    if btest:
        cmd.append("--btest")

    t0 = time.monotonic()
    print(f"\n{'='*70}")
    print(f"[campaign] Block {block['block_id']}/{block.get('total','?')}: "
          f"{block['pipeline']} / {block['condition']} (block_in_cell={block['block_in_cell']})")
    print(f"[campaign] Command: {' '.join(cmd)}")
    print(f"{'='*70}")
    try:
        result = subprocess.run(cmd, check=False)
        exit_code = result.returncode
    except KeyboardInterrupt:
        # Operator interrupt — propagate up
        raise
    except Exception as e:
        print(f"[campaign] Subprocess raised exception: {e}")
        exit_code = -1

    wall_sec = time.monotonic() - t0
    return {
        "block_id": block["block_id"],
        "pipeline": block["pipeline"],
        "condition": block["condition"],
        "block_in_cell": block["block_in_cell"],
        "exit_code": exit_code,
        "wall_sec": wall_sec,
        "finished_at": datetime.now().isoformat(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign-id", required=True,
                    help="Campaign identifier (e.g., 'confirmatory-2026-05-26')")
    ap.add_argument("--btest", action="store_true",
                    help="Smoke-test mode: 3 blocks at 30s each via --btest")
    args = ap.parse_args()

    seed = load_seed()
    print(f"[campaign] Seed: {seed} (from {SEED_FILE.relative_to(REPO_ROOT)})")
    print(f"[campaign] Campaign ID: {args.campaign_id}")
    if args.btest:
        print(f"[campaign] *** BTEST MODE *** — 3 blocks at 30s each")

    manifest = build_manifest(seed, btest=args.btest)
    print(f"[campaign] Planned {len(manifest)} blocks")
    for b in manifest[:5]:
        print(f"  block {b['block_id']:3d}: {b['pipeline']:10s} {b['condition']:15s} "
              f"(block_in_cell={b['block_in_cell']})")
    if len(manifest) > 5:
        print(f"  ... and {len(manifest)-5} more")

    # Annotate each block with its total for log output
    for b in manifest:
        b["total"] = len(manifest)

    # Run the campaign
    results = []
    consecutive_failures = 0
    halted_early = False
    halt_reason = None

    campaign_start = time.monotonic()
    for block in manifest:
        result = run_one_block(block, args.campaign_id, args.btest)
        results.append(result)

        if result["exit_code"] == 0:
            print(f"[campaign] Block {result['block_id']} OK in {result['wall_sec']:.1f}s")
            consecutive_failures = 0
        else:
            print(f"[campaign] Block {result['block_id']} FAILED "
                  f"(exit={result['exit_code']}, {result['wall_sec']:.1f}s). "
                  f"Consecutive failures: {consecutive_failures + 1}/{CONSECUTIVE_FAILURE_LIMIT}")
            consecutive_failures += 1
            if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                halted_early = True
                halt_reason = f"{CONSECUTIVE_FAILURE_LIMIT} consecutive block failures"
                break

    campaign_wall = time.monotonic() - campaign_start

    # Write campaign manifest
    out_dir = REPO_ROOT / "data" / "training" / args.campaign_id
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_out = {
        "campaign_id": args.campaign_id,
        "btest": args.btest,
        "seed": seed,
        "seed_source": "code/analysis/block_order_seed.txt",
        "planned_blocks": len(manifest),
        "completed_blocks": len(results),
        "halted_early": halted_early,
        "halt_reason": halt_reason,
        "campaign_wall_sec": campaign_wall,
        "block_duration_sec": 30 if args.btest else BLOCK_DURATION_SEC,
        "pipelines": PIPELINES,
        "conditions": CONDITIONS,
        "blocks_per_cell": 1 if args.btest else BLOCKS_PER_CELL,
        "consecutive_failure_limit": CONSECUTIVE_FAILURE_LIMIT,
        "started_at": datetime.fromtimestamp(time.time() - campaign_wall).isoformat(),
        "finished_at": datetime.now().isoformat(),
        "results": results,
    }
    manifest_path = out_dir / "campaign_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest_out, f, indent=2)
    print(f"\n[campaign] Manifest written: {manifest_path}")

    # Summary
    n_ok = sum(1 for r in results if r["exit_code"] == 0)
    n_fail = sum(1 for r in results if r["exit_code"] != 0)
    print(f"\n[campaign] Summary:")
    print(f"  Planned:    {len(manifest)} blocks")
    print(f"  Completed:  {len(results)} blocks")
    print(f"  OK:         {n_ok}")
    print(f"  Failed:     {n_fail}")
    print(f"  Wall time:  {campaign_wall:.1f}s ({campaign_wall/60:.1f} min)")
    print(f"  Halted:     {'YES — ' + halt_reason if halted_early else 'NO'}")

    return 0 if not halted_early else 1


if __name__ == "__main__":
    sys.exit(main())
