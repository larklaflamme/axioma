#!/usr/bin/env python3
"""
run_consolidated.py — Consolidated pipeline that accumulates manifest records
across all analyses, avoiding subprocess-based overwrite.
"""

import sys, os, json, time, subprocess
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, "results")
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

def load_existing_manifest():
    """Load existing manifest records, keyed by key."""
    path = os.path.join(RESULTS, "manifest.json")
    if os.path.exists(path):
        with open(path) as f:
            doc = json.load(f)
        records = {r["key"]: r for r in doc.get("results", [])}
        print(f"Loaded {len(records)} existing records")
        return records
    return {}

def run_script_in_process(name):
    """Run an analysis script by importing it as a module."""
    path = os.path.join(BASE, "analyses", name)
    mod_name = name.replace(".py", "")
    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "run"):
        return mod.run()

def merge_manifests(accumulated):
    """Write a single unified manifest.tex + manifest.json from all records."""
    records_list = list(accumulated.values())
    doc = {
        "metadata": {
            "generated_at": time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()),
            "note": "Consolidated from all pipeline analyses"
        },
        "results": records_list
    }
    
    # Write JSON
    json_path = os.path.join(RESULTS, "manifest.json")
    with open(json_path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"Wrote {json_path} ({len(records_list)} total records)")
    
    # Write LaTeX
    lines = [
        "% Auto-generated manifest -- consolidated pipeline",
        f"% {time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime())}",
        "% All bridge manuscript values resolved from analyses",
        ""
    ]
    for rec in records_list:
        key = rec["key"].replace(".", "_")
        val = rec["value"]
        if val is None:
            continue
        if isinstance(val, float):
            if abs(val) < 1e-3 or abs(val) > 1e4:
                tex_val = f"{val:.4e}"
            else:
                tex_val = f"{val:.4f}"
            if rec.get("ci") and rec["ci"][0] is not None:
                lo, hi = rec["ci"]
                tex_val = f"{tex_val}^{{+{hi:.4f}}}_{{-{lo:.4f}}}"
        elif isinstance(val, str):
            tex_val = val.replace("_", "\\_")
        else:
            tex_val = str(val)
        macro = f"\\newcommand{{\\{key}}}{{{tex_val}}}"
        lines.append(macro)
    
    tex_path = os.path.join(RESULTS, "manifest.tex")
    with open(tex_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {tex_path} ({len(records_list)} macros)")


if __name__ == "__main__":
    t0 = time.time()
    accumulated = load_existing_manifest()
    
    print("=" * 60)
    print("CONSOLIDATED PIPELINE")
    print("=" * 60)
    
    # Phase 1: T6 — Fisher sweep
    print("\n--- Phase 1: T6 Fisher sweep ---")
    from analyses.t06_fisher_sweep import run as run_t6
    run_t6()
    
    # Load T6 records from manifest
    with open(os.path.join(RESULTS, "manifest.json")) as f:
        t6_doc = json.load(f)
    for r in t6_doc["results"]:
        accumulated[r["key"]] = r
    print(f"T6: {len(t6_doc['results'])} records added")
    
    # Phase 2: T5/T7/T8/T9 — Downstream
    print("\n--- Phase 2: T5/T7/T8/T9 downstream ---")
    from analyses.t05_t07_t08_t09 import run as run_t5
    run_t5()
    
    with open(os.path.join(RESULTS, "manifest.json")) as f:
        t5_doc = json.load(f)
    for r in t5_doc["results"]:
        accumulated[r["key"]] = r
    print(f"T5: {len(t5_doc['results'])} records added")
    
    # Merge and write final manifest
    print("\n--- Merging manifests ---")
    merge_manifests(accumulated)
    
    # Generate figures
    print("\n--- Generating figures ---")
    subprocess.run(
        [sys.executable, "generate_figures.py"],
        cwd=BASE, capture_output=True, text=True, timeout=120
    )
    
    t1 = time.time()
    print(f"\n{'='*60}")
    print(f"Consolidated pipeline finished in {t1-t0:.1f}s")
    print(f"Total manifest records: {len(accumulated)}")
    
    # Summary
    print(f"\n{'='*60}")
    print("KEY FINDINGS")
    print(f"{'='*60}")
    for key in sorted(accumulated.keys()):
        val = accumulated[key]["value"]
        if val is not None:
            if isinstance(val, float) and abs(val) > 1e-10:
                print(f"  {key:35s} = {val:.6e}" if abs(val) < 1e-3 or abs(val) > 1e4 
                      else f"  {key:35s} = {val:.6f}")
            elif isinstance(val, (int, float)):
                print(f"  {key:35s} = {val}")