"""review.py (2026-11-07): the engine-free review of a finished CLI run, on the AZURE2 13N test output.  Seconds."""
import os, sys, tempfile, shutil
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
from rmfit import AZURE2_ROOT
from rmfit import review as rv

SRC = os.path.join(AZURE2_ROOT, "tests", "13N")
FAILS = []


def check(name, ok, info=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  -- {info}" if info and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    azr = os.path.join(SRC, "13N.azr"); odir = os.path.join(SRC, "output")
    # 1. the point table reproduces chiSquared.out (parsing, block assignment and the n*d / n*e convention)
    tab = rv.table_from_output(azr, odir)
    chisq = rv.read_chisq_out(os.path.join(odir, "chiSquared.out"))
    ntot = sum(d["n"] for d in chisq.values()); ctot = sum(d["chi2"] for d in chisq.values())
    check("point count = chiSquared.out Total-N", tab.n == ntot, f"{tab.n} vs {ntot}")
    check("plain chi2 = chiSquared.out total (0.1 %)", abs(tab.chi2.sum() - ctot) / ctot < 1e-3, f"{tab.chi2.sum():.1f} vs {ctot:.1f}")
    per = {k: float(tab.chi2[tab.key == k].sum()) for k in tab.keys()}
    worst = max(abs(per[k] - chisq[k]["chi2"]) / max(chisq[k]["chi2"], 1) for k in per)
    check("per-segment chi2 matches (1e-3)", worst < 1e-3, f"worst rel {worst:.2e}")
    check("angles carried for differential segments", np.isfinite(tab.ang[tab.key == 3]).all() and np.isnan(tab.ang[tab.key == 1]).all())
    # 2. levels from parameters.out: the 1/2+ 2.3682 has G = 34 keV + 480 meV
    lv = rv.levels_from_parameters_out(os.path.join(odir, "parameters.out"))
    l1 = [l for l in lv if l.jpi == "1/2+" and abs(l.energy - 2.3682) < 1e-3]
    check("parameters.out levels parsed", len(lv) >= 6 and len(l1) == 1, str(len(lv)))
    check("1/2+ 2.3682 total width 34.00048 keV", l1 and abs(l1[0].gamma_mev - (34.0e-3 + 480e-9)) < 1e-9, l1 and str(l1[0].gamma_mev))
    # 3. levels from the .azr's physical gamma fields (open channels only)
    la = rv.levels_from_azr(azr)
    check(".azr levels carry widths", la and all(l.gamma_mev is not None for l in la), str(len(la)))
    # 4. the whole review runs and writes REVIEW.md + figures
    tmp = tempfile.mkdtemp(prefix="rmfit_review_")
    try:
        r = rv.review_output(azr, odir, out_dir=tmp, figures=2)
        txt = open(r["path"]).read()
        check("REVIEW.md written with findings", os.path.exists(r["path"]) and sum(r["counts"].values()) > 0 and "## Per-point summary" in txt)
        check("sections present", all(h in txt for h in ("## Normalizations", "## Residual runs", "## Average versus structure",
                                                          "## Zigzag in the calculated curve", "## Levels inside the data range", "## Figures")))
        figs = [f for f in os.listdir(os.path.join(tmp, "figures")) if f.endswith(".png")]
        check("figures written (residual map + 2 data sets)", len(figs) == 3, str(figs))
        codes = {f.code for f in r["findings"]}
        check("the seed's misfit shows as systematic-misfit + residual-run", {"systematic-misfit", "residual-run"} <= codes, str(codes))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 5. synthetic norm-opposite case (10B+a ND5U25: norm 1.32 while the fit is 0.64 x the data)
    n = 40
    ex = np.linspace(8.0, 9.0, n); d = np.full(n, 10.0); e = np.full(n, 0.3); c = 0.64 * d
    tab2 = rv.PointTable(key=np.full(n, 1), name=np.array(["ND5U25"] * n, dtype=object), ecm=ex, ex=ex, ang=np.full(n, np.nan),
                         fit=c, data=d, err=e, norm=np.full(n, 1.32))

    class Seg:
        key = 1; observable = "angle-integrated"; vary_norm = True; norm_error = 9.7; norm_group = "ND5U25"; covariance = None; data_file = "ND5U25.dat"
        entrance_key = 1; exit_key = 2

    class Segs(list):
        def by_key(self, k): return self[0]

    rev = rv.Review(tab2, [], Segs([Seg()])).run(None)
    opp = [f for f in rev.findings if f.code == "norm-opposite"]
    check("norm-opposite fires at norm 1.32 vs n* 0.64", len(opp) == 1 and "0.640" in opp[0].message, [f.line() for f in rev.findings][:3])
    # 6. zigzag: a saw-tooth fit over finely spaced points
    ex = np.linspace(11.40, 11.47, 36); c = 5.0 * (1 + 0.03 * np.where(np.arange(36) % 2, 1, -1)); d = np.full(36, 5.0); e = np.full(36, 0.5)
    tab3 = rv.PointTable(key=np.full(36, 89), name=np.array(["ND_an_t1"] * 36, dtype=object), ecm=ex, ex=ex, ang=np.full(36, np.nan),
                         fit=c, data=d, err=e, norm=np.ones(36))
    rev3 = rv.Review(tab3, [rv.Level("7/2-", 11.435, 606e-6)], None).run(None)
    zz = [f for f in rev3.findings if f.code == "fit-zigzag"]
    check("fit-zigzag fires on a 3 % saw-tooth and names the narrow level", len(zz) == 1 and "7/2- 11.4350" in zz[0].message, [f.line() for f in rev3.findings][:3])
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nPASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
