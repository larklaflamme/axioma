#!/usr/bin/env python3
"""
Merge T6 sweep results + downstream manifest into unified manifest.tex.
Copy to bridge directory.
"""
import json, os, numpy as np, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, "results")

d = np.load(os.path.join(RESULTS, "t06_sweep.npz"))
C_cut = d["C_cut"]
growth = float(d["growth"])
lam = d["lam"]
vs = d["vs"]
lambdas_500 = lam[-1]
condition_500 = lambdas_500[0] / max(lambdas_500[-1], 1e-300)

with open(os.path.join(RESULTS, "manifest.json")) as f:
    doc = json.load(f)
downstream = {r["key"]: r for r in doc["results"]}

manu_cutoffs = np.array([22, 25, 30, 35, 45, 50, 60, 75, 100,
                         120, 150, 200, 250, 300, 350, 400, 450, 500], dtype=float)

lines = [
    "% Auto-generated manifest -- unified pipeline",
    "% All bridge manuscript values resolved from analyses",
    ""
]

for fk, c in zip(manu_cutoffs, C_cut):
    lines.append("\\newcommand{\\TsixC" + str(int(fk)) + "}{" + f"{c:.6e}" + "}")

lines.append("\\newcommand{\\Tsixgrowth}{" + f"{growth:.2e}" + "}")
lines.append("\\newcommand{\\Tsixcondition}{" + f"{condition_500:.2e}" + "}")
lines.append("\\newcommand{\\Tsixlambdaone}{" + f"{lambdas_500[0]:.4e}" + "}")
lines.append("\\newcommand{\\Tsixlambdafive}{" + f"{lambdas_500[-1]:.4e}" + "}")

vd = vs[-1, :, -1]
lines.append("\\newcommand{\\TsixvdlnMc}{" + f"{vd[0]:+.6f}" + "}")
lines.append("\\newcommand{\\Tsixvdq}{" + f"{vd[1]:+.6f}" + "}")
lines.append("\\newcommand{\\Tsixvdchieff}{" + f"{vd[2]:+.6f}" + "}")
lines.append("\\newcommand{\\TsixvdLt}{" + f"{vd[3]:+.6f}" + "}")
lines.append("\\newcommand{\\TsixvdlnDL}{" + f"{vd[4]:+.6f}" + "}")

for key, rec in sorted(downstream.items()):
    if rec["value"] is None:
        continue
    k = key.replace(".", "_")
    v = rec["value"]
    if isinstance(v, float):
        if abs(v) < 1e-3 or abs(v) > 1e4:
            lines.append("\\newcommand{\\" + k + "}{" + f"{v:.4e}" + "}")
        else:
            lines.append("\\newcommand{\\" + k + "}{" + f"{v:.4f}" + "}")
    else:
        lines.append("\\newcommand{\\" + k + "}{" + str(v) + "}")

tex_path = os.path.join(RESULTS, "manifest.tex")
with open(tex_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"Wrote {tex_path}")

bridge_dir = "/home/ubuntu/docs/arxiv/bridge"
if os.path.isdir(bridge_dir):
    shutil.copy2(tex_path, os.path.join(bridge_dir, "manifest.tex"))
    fig_src = os.path.join(RESULTS, "figures")
    bridge_fig = os.path.join(bridge_dir, "figures")
    os.makedirs(bridge_fig, exist_ok=True)
    for fn in os.listdir(fig_src):
        if fn.endswith(".png"):
            shutil.copy2(os.path.join(fig_src, fn), os.path.join(bridge_fig, fn))
    print(f"Copied figures + manifest to {bridge_dir}/")