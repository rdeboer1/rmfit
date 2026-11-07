#!/usr/bin/env python3
"""bake separates a near-degenerate BROAD same-J^pi pair before writing (2026-10-10), with the real engine on 13N.
broad: a free 1/2+ added 5 keV above the FIXED 20 MeV 1/2+ background level (5 MeV wide), then put 0.3 keV from it in the vector
  -> the broader member's energy is fixed, so the new (broad, ~MeV) one moves to 2.5 keV; the file reads back with every key
narrow: a free 1/2+ added 5 keV above the 2.3682 MeV 1/2+ (34 keV), put 0.3 keV from it; at 2.37 MeV the engine's Brune
  transform caps an L=0 width near ~45 keV, so the pair is narrow -> refused; the written file merges, bake raises as before
  cost cap 1e-9    -> bake raises instead of separating
Run: python3 rmfit/tests/test_bake_separate_13n.py   (a few minutes)"""
import os, sys, shutil, tempfile, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
sys.path.insert(0, "/users/rdeboer1/AZURE2")
import numpy as np
from pyazr import AzrModel
from rmfit.engine import SingleSession, bake
from rmfit.model import single_variant
AZ = "/users/rdeboer1/AZURE2"
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        failures.append(name)


E_REF = dict(broad=20.0, narrow=2.3682)


def build(tmp, tag, gamma_ev):
    mdl = AzrModel.from_file(os.path.join(AZ, "tests", "13N", "13N.azr"))
    mdl.add_level(0.5, 1, E_REF[tag] + 0.005, [dict(pair=1, L=0, S=0.5, gamma=gamma_ev, fixed=False)], level_fixed=False)
    mdl.set_output_dir(os.path.join(tmp, "output"))
    return mdl.write(os.path.join(tmp, f"13N_{tag}.azr"))


def vector(base, tmp, tag):
    with SingleSession(single_variant(base, f"v_{tag}", tmp), cwd=tmp, flags={}, name=f"v_{tag}") as ev:
        x = np.array(ev.x0, float); keys = list(ev.keys)
        j = [i for i, k in enumerate(keys) if k.kind == "energy" and k.level.startswith("1/2+") and abs(x[i] - E_REF[tag] - 0.005) < 1e-6]
        assert len(j) == 1, ([str(k) for k in keys], x)
        x[j[0]] = E_REF[tag] + 0.0003
        return x, keys, j[0]


def main():
    tmp = tempfile.mkdtemp(prefix="rmfit_sep_")
    shutil.copytree(os.path.join(AZ, "tests", "13N", "data"), os.path.join(tmp, "data")); os.makedirs(os.path.join(tmp, "output"))
    # broad
    base = build(tmp, "broad", 1.0e6); x, keys, j = vector(base, tmp, "broad")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            azr, sav, sc = bake(base, x, keys, os.path.join(tmp, "baked_broad.azr"), {}, workdir=tmp)
    finally:
        out = buf.getvalue(); print("   " + out.strip().replace("\n", "\n   "))
    check("broad pair: bake reports the separation", "separated near-degenerate" in out, out)
    es = sorted({round(l.energy, 7) for l in AzrModel.from_file(azr).levels if l.active and l.jpi == "1/2+" and 19 < l.energy < 21})
    check("broad pair: written 1/2+ levels 2.5 keV apart", len(es) == 2 and abs((es[1] - es[0]) * 1e3 - 2.5) < 1e-3, str(es))
    check("broad pair: the fixed-energy background level did not move", abs(es[0] - 20.0) < 1e-6, str(es))
    check("broad pair: bake verified the written model (no merge)", np.isfinite(sc.objective), str(sc))
    # cost cap
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bake(base, x, keys, os.path.join(tmp, "baked_cap.azr"), {}, workdir=tmp, separate_max_cost=1e-9)
        check("cost cap: bake refuses an expensive separation", False, "no exception")
    except ValueError as e:
        check("cost cap: bake refuses an expensive separation", "would cost" in str(e), str(e))
    # narrow
    base = build(tmp, "narrow", 3.0e3); x, keys, j = vector(base, tmp, "narrow")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            bake(base, x, keys, os.path.join(tmp, "baked_narrow.azr"), {}, workdir=tmp)
        check("narrow pair: bake still fails (merge on read)", False, "no exception")
    except (ValueError, RuntimeError) as e:     # the existing key-set check after the write raises RuntimeError
        check("narrow pair: bake still fails (merge on read)", "different free-parameter set" in str(e), str(e))
        check("narrow pair: the refusal is reported", "NOT separated" in buf.getvalue(), buf.getvalue())
    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if not failures else f"FAILED: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
