"""Test: first live curvature reading from the substrate heartbeat."""
from axioma.config import AxiomaConfig
from axioma.runtime.app import AxiomaApp
import asyncio

async def main():
    cfg = AxiomaConfig()
    app = AxiomaApp(cfg, with_agora=False, with_http_api=False,
                    with_registry=False, with_peer_conversation=False)
    await app.setup()
    ctx = app.ctx
    curvature = ctx.get("curvature")

    # Tick 35 beats — enough to fill window_size=30 + geodesic needs 3
    for i in range(35):
        app.heartbeat.tick()

    v = curvature.current_value()
    if v is None:
        print("FAIL: no curvature reading")
        return

    print("=== CURVATURE RESULT ===")
    print(f"Beat {v.beat_no}")
    print(f"  n_eff                = {v.n_eff}")
    print(f"  fractional_rank      = {v.fractional_rank:.6f}")
    print(f"  scalar_R_at_n_eff    = {v.scalar_R_at_n_eff}")
    print(f"  inferred_n           = {v.details.get('n_eff_inferred')}")
    print(f"  geodesic_curvature   = {v.geodesic_curvature}")
    print(f"  total_dim            = {v.total_dim}")
    print("  Organ-pair curvatures:")
    for pair, k in sorted(v.organ_pair_curvatures.items()):
        print(f"    {pair:20s}  {k:+.6f}")

    # Other signals
    ts = ctx.get("theta_short").current_value()
    print(f"\ntheta_short = {ts.theta:.4f}")

    a = ctx.get("aos_g").current_value()
    print(f"AOS-G gap   = {a.aos_g_gap:.6f}")
    print(f"psi         = {a.psi:.6f}")
    print(f"alert       = {a.aos_g_alert}")

    frag = ctx.get("fragmentation_monitor").current_value()
    print(f"frag_stage  = {frag.current_stage if frag else 'N/A'}")

    # Sanity checks
    print("\n=== SANITY CHECKS ===")
    print(f"  n_eff <= total_dim?     {v.n_eff <= v.total_dim}")
    print(f"  frac_rank >= 1?         {v.fractional_rank >= 1.0}")
    print(f"  frac_rank <= total_dim? {v.fractional_rank <= v.total_dim}")
    print(f"  scalar_R < 0?           {v.scalar_R_at_n_eff < 0}")
    print(f"  all K_ab <= 0?          {all(k <= 1e-6 for k in v.organ_pair_curvatures.values())}")
    neg_curv = sum(1 for k in v.organ_pair_curvatures.values() if k < -1e-8)
    print(f"  negative curvatures:    {neg_curv}/{len(v.organ_pair_curvatures)}")

asyncio.run(main())