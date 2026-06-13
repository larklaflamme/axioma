#!/usr/bin/env python3
"""
Main pipeline runner for the (rho, Pi) bridge.

Phases 1-3: runs all analysis tasks, populates manifest, generates figures.
"""

import os, sys, json, importlib
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.manifest import Manifest

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
FIGURES_DIR = os.path.join(RESULTS_DIR, 'figures')
TABLES_DIR = os.path.join(RESULTS_DIR, 'tables')


def run_task(task_name, task_module_path):
    """Run an analysis task and return its results."""
    print(f"\n{'=' * 60}")
    print(f"Running {task_name}...")
    print(f"{'=' * 60}")
    
    spec = importlib.util.spec_from_file_location(task_name, task_module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    results = module.run()
    return results


def main():
    print("=" * 60)
    print("(rho, Pi) Bridge Pipeline")
    print("Pipeline version: 1.0.0")
    print("=" * 60)
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(TABLES_DIR, exist_ok=True)
    
    manifest = Manifest(RESULTS_DIR)
    
    # Define task order
    tasks = [
        ("T2: Ridge orientation", "analyses/t02_ridge_orientation.py"),
        ("T3: Prior-displacement alignment", "analyses/t03_alignment.py"),
        ("T4: GW150914 contrast", "analyses/t04_gw150914_contrast.py"),
        ("T5: Displacement scalars", "analyses/t05_displacement_scalars.py"),
        ("T6: C(f) sweep", "analyses/t06_Cf_sweep.py"),
        ("T7: Growth-law slopes", "analyses/t07_slopes.py"),
        ("T8: PSD battery", "analyses/t08_psd_battery.py"),
        ("T9: Forward model", "analyses/t09_forward_model.py"),
        ("T10: Validity map", "analyses/t10_validity_map.py"),
        ("T1: Ordering experiment", "analyses/t01_ordering.py"),
    ]
    
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))
    
    all_results = {}
    
    for name, path in tasks:
        abs_path = os.path.join(pipeline_dir, path)
        if not os.path.exists(abs_path):
            print(f"  WARNING: {abs_path} not found, skipping")
            continue
        try:
            results = run_task(name, abs_path)
            all_results[name] = results
        except Exception as e:
            print(f"  ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
    
    # Register results in manifest
    # T2
    if "T2: Ridge orientation" in all_results:
        t2 = all_results["T2: Ridge orientation"].get("T2", {})
        for analysis in ["lowSpin", "highSpin"]:
            if analysis in t2:
                manifest.record(
                    f"T2.angle_{analysis}",
                    t2[analysis]["angle_deg"],
                    ci=t2[analysis]["ci"],
                    units="deg",
                    section="III.B",
                    table="I"
                )
    
    # T3
    if "T3: Prior-displacement alignment" in all_results:
        t3 = all_results["T3: Prior-displacement alignment"].get("T3", {})
        manifest.record("T3.dMc", t3.get("dMc", 0), units="ln(Mc/Msun)", section="III.C", table="II")
        manifest.record("T3.cos2a", t3.get("cos2_alpha", 0), units="", section="III.C", table="II")
        manifest.record("T3.pval", t3.get("p_value", 0), units="", section="III.C", table="II")
        manifest.record("T3.angle", t3.get("angle_deg", 0),
                        ci=t3.get("angle_ci", [0, 0]), units="deg", section="III.C", table="II")
        manifest.record("T3.logLcost", t3.get("logL_cost", 0), units="", section="III.C", table="II")
    
    # T4
    if "T4: GW150914 contrast" in all_results:
        t4 = all_results["T4: GW150914 contrast"].get("T4", {})
        for evt in ["GW150914", "GW170817"]:
            if evt in t4:
                manifest.record(f"T4.condnum_{evt.lower()}", t4[evt]["condition_number"],
                              units="", section="III.D", table="III")
                manifest.record(f"T4.gain_{evt.lower()}", t4[evt]["lensing_gain"],
                              units="", section="III.D", table="III")
        if "common_4d_block" in t4:
            manifest.record("T4.kappa_ratio", t4["common_4d_block"]["kappa_ratio"],
                          units="", section="III.D", table="III")
    
    # T6
    if "T6: C(f) sweep" in all_results:
        t6 = all_results["T6: C(f) sweep"].get("T6", {})
        manifest.record("T6.growth_factor", t6.get("growth_factor", 1),
                      units="", section="IV.C", table="IV")
        manifest.record("T6.growth_envelope", t6.get("growth_envelope", 0),
                      units="", section="IV.C", table="IV")
        manifest.record("T6.C22", t6.get("C_low", 0), units="", section="IV.C", table="IV")
        manifest.record("T6.C500", t6.get("C_full", 0), units="", section="IV.C", table="IV")
        manifest.record("T6.ridge_uniformity_band", t6.get("ridge_uniformity_band", ""),
                      units="", section="IV.C", table="IV")
    
    # T7
    if "T7: Growth-law slopes" in all_results:
        t7 = all_results["T7: Growth-law slopes"].get("T7", {})
        overall = t7.get("overall", {})
        manifest.record("T7.slope_measured", overall.get("slope", 0),
                      units="", section="V.D")
        manifest.record("T7.slope_analytic", overall.get("analytic_prediction", 0),
                      units="", section="V.D")
    
    # T8
    if "T8: PSD battery" in all_results:
        t8 = all_results["T8: PSD battery"].get("T8", {})
        manifest.record("T8.max_variation", t8.get("max_variation", 0),
                      units="%", section="IV.D", table="V")
        for psd in ["ZDHP", "Early_aLIGO", "O2_H1", "O2_L1"]:
            if psd in t8:
                manifest.record(f"T8.int_{psd.lower()}", t8[psd]["commutator_integral"],
                              units="", section="IV.D", table="V")
                manifest.record(f"T8.C22_{psd.lower()}", t8[psd]["C_at_22Hz"],
                              units="", section="IV.D", table="V")
                manifest.record(f"T8.C500_{psd.lower()}", t8[psd]["C_at_500Hz"],
                              units="", section="IV.D", table="V")
    
    # T9
    if "T9: Forward model" in all_results:
        t9 = all_results["T9: Forward model"].get("T9", {})
        manifest.record("T9.fstar_2", t9.get("fstar_2", 0), units="Hz", section="V.B", table="VI")
        manifest.record("T9.fstar_1", t9.get("fstar_1", 0), units="Hz", section="V.B", table="VI")
        manifest.record("T9.fstar_4", t9.get("fstar_4", 0), units="Hz", section="V.B", table="VI")
        manifest.record("T9.peak_magnitude", t9.get("peak_magnitude", 0), units="", section="V.B", table="VI")
        manifest.record("T9.fstar_scatter", t9.get("fstar_scatter", 0), units="Hz", section="V.B", table="VI")
        manifest.record("T9.N500", t9.get("N500", 0), units="", section="V.C", table="VI")
    
    # T10
    if "T10: Validity map" in all_results:
        t10 = all_results["T10: Validity map"].get("T10", {})
        manifest.record("T10.v1_passes", t10.get("v1_passes_everywhere", False),
                      units="", section="II.F")
        manifest.record("T10.vd_fails_low", t10.get("vd_fails_low_cutoffs", False),
                      units="", section="II.F")
    
    # Save manifest
    json_path = manifest.save_json("manifest.json")
    tex_path = manifest.save_latex("manifest.tex")
    
    print(f"\n{'=' * 60}")
    print("Pipeline complete.")
    print(f"Manifest JSON: {json_path}")
    print(f"Manifest LaTeX: {tex_path}")
    print(f"{'=' * 60}")
    
    # Write summary
    summary = {
        "pipeline_status": "complete",
        "n_tasks_run": len(all_results),
        "tasks": list(all_results.keys()),
    }
    with open(os.path.join(RESULTS_DIR, "pipeline_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    
    return all_results


if __name__ == "__main__":
    main()