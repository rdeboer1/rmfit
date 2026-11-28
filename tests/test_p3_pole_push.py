#!/usr/bin/env python3
"""Pole push (rmfit.poleguard.PolePush, pole_guard["push"]; 2026-11-27, at the evaluator's request).
Fixture fixtures_p3/relvector_p12c/ngcov.azr (12C+p, format 3; one level per J^pi, so no extra bound zero).  Checks:
  (a) reduced_det vanishes nowhere at a level energy (the forced zeros of det A^-1 are divided out) and is NaN above
      the lowest threshold;
  (b) with no extra zero at the start, the push has no rows and polish equals polish without it;
  (c) with a stub zero E(x) = -1 + x_c (one parameter), the push row is (E - target)/tau and its Jacobian matches the
      implicit derivative -(dg/dx)/(dg/dE) = 1/tau in that column (the derivative code path, end to end);
  (d), (d'') the guard's bound test modes under a push; (e) channels with P < P_CLOSED count as closed."""
import os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
os.environ.setdefault("OMP_NUM_THREADS", "1")
from rmfit.backend import PYAZR3 as _PYAZR3  # noqa: E402
if not _PYAZR3:
    print("SKIP: a pyazr 3 test (Session.jpi_block)")
    sys.exit(77)
from _fixtures import fixture  # noqa: E402
import numpy as np
from rmfit.engine import SingleSession
from rmfit.local import BoundsPolicy, polish
from rmfit import poleguard
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        failures.append(name)


def main():
    src = fixture("relvector_p12c")
    tmp = tempfile.mkdtemp(prefix="p3polepush_")
    try:
        os.symlink(os.path.join(src, "data"), os.path.join(tmp, "data"))
        for d in ("output", "checks"):
            os.makedirs(os.path.join(tmp, d))
        shutil.copy(os.path.join(src, "ngcov.azr"), os.path.join(tmp, "ngcov.azr"))
        azr = os.path.join(tmp, "ngcov.azr")
        push_cfg = {"floor": -5.0, "margin": 2.0, "tau": 0.1}
        cfg = {"step": 0.002, "gamma_max": 0.01, "bound_min": -7.0, "push": push_cfg}
        with SingleSession(azr, cwd=tmp, flags=dict(use_brune=True), name="polepush") as ev:
            x0 = np.array(ev.x0, float)
            g = poleguard.PoleGuard(ev, cfg, log=print)
            gv = g.vector(x0)
            # (a)
            fin, nan_above = True, True
            for jg in g.groups:
                lv = [float(L["E_level"]) for L in g.sess.jpi_block(jg, [0.0], gv)["levels"]]
                v = poleguard.reduced_det(g.sess, jg, np.array(lv) + 1e-9, gv)
                b = g.sess.jpi_block(jg, np.array(lv), gv)
                fin &= bool(np.all(np.isfinite(v) | (np.asarray(b["det_im"]) != 0)))
                nan_above &= bool(np.isnan(poleguard.reduced_det(g.sess, jg, [8.0], gv)[0]))
            check("(a) reduced_det finite at the level energies where channels are closed", fin)
            check("(a) reduced_det NaN where a channel is open", nan_above)
            # (e) P_CLOSED (v2m 2026-11-28): just above the lowest threshold, where the open channel's P < 1e-8 (here a
            # proton on 12C, Coulomb), the reduced determinant is the real part, finite; where P >= 1e-8, NaN
            jg1 = sorted(g.groups)[0]
            b0 = g.sess.jpi_block(jg1, [8.0], gv)
            thr = min(float(c["threshold"]) for c in b0["channels"] if float(c["threshold"]) > -50)
            E1 = np.array([thr + 0.002, 8.0])
            b1 = g.sess.jpi_block(jg1, E1, gv)
            pmax = np.max(np.vstack([np.asarray(c["P"], float) for c in b1["channels"]]), axis=0)
            v1 = poleguard.reduced_det(g.sess, jg1, E1, gv)
            check("(e) P < P_CLOSED just above threshold: reduced_det finite there, NaN where P is large",
                  pmax[0] < poleguard.P_CLOSED and np.isfinite(v1[0]) and pmax[1] >= poleguard.P_CLOSED and np.isnan(v1[1]),
                  (thr, pmax.tolist(), v1.tolist()))
            # (b)
            p = poleguard.PolePush(g, push_cfg, x0, x0.size, log=print)
            r, J = p.rows(x0, jac=True)
            check("(b) no extra zero -> only zero spare rows, one per J^pi", r.size == len(g.groups) and not r.any() and J.shape == (len(g.groups), x0.size) and not J.any(), (r.size, J.shape))
            g.close()
            f0 = polish(ev, x0, policy=BoundsPolicy(pole_guard={k: v for k, v in cfg.items() if k != "push"}), max_nfev=6)
            lines = []
            f1 = polish(ev, x0, policy=BoundsPolicy(pole_guard=cfg), max_nfev=6, log=lines.append)
            check("(b) push on = push off when there is nothing to push", abs(f0.objective - f1.objective) < 1e-9 * max(1, abs(f0.objective))
                  and np.allclose(f0.x, f1.x), (f0.objective, f1.objective))
            check("(b) the log has the push's start and end lines", any("pole push:" in l for l in lines)
                  and any("pole push at the end" in l for l in lines), lines)
            # (c) stub: one extra zero at E = -1 + x[c] in the first group, g(E) = E - (-1 + x[c])
            g = poleguard.PoleGuard(ev, cfg)
            i, c = g.map[0]
            jg0 = sorted(g.groups)[0]
            orig_rd, orig_ez = poleguard.reduced_det, poleguard.extra_bound_zeros
            def rd(sess, jg, E, x=None):
                return np.atleast_1d(np.asarray(E, float)) - (-1.0 + float(x[i]))
            def ez(sess, jg, lo, hi, x=None, step=2e-3, xtol=1e-7):
                e = -1.0 + float(x[i])
                return [e] if (jg == jg0 and lo <= e <= hi) else []
            poleguard.reduced_det, poleguard.extra_bound_zeros = rd, ez
            try:
                p = poleguard.PolePush(g, push_cfg, x0, x0.size)
                if c not in [j for _, j in p.cols[jg0]]:
                    p.cols[jg0] = p.cols[jg0] + [(i, c)]
                r, J = p.rows(x0, jac=True)
                e = -1.0 + x0[c]
                check("(c) one slot + one spare for the stub zero, one spare for each other J^pi", r.size == len(g.groups) + 1, r.size)
                check("(c) the row is (E - target)/tau", abs(r[0] - (e - p.target) / p.tau) < 1e-9 and r[1] == 0, (r, e))
                check("(c) dE/dx = 1 -> Jacobian 1/tau in that column only", abs(J[0, c] - 1 / p.tau) < 1e-4 * (1 / p.tau)
                      and np.count_nonzero(J[0]) == 1 and not J[1].any(), (J[0, c], np.count_nonzero(J[0])))
                # (c') constant force F: r = sqrt(2 F (E - target)), dr/dx = F / r
                pf = poleguard.PolePush(g, dict(push_cfg, force=50.0), x0, x0.size)
                if c not in [j for _, j in pf.cols[jg0]]:
                    pf.cols[jg0] = pf.cols[jg0] + [(i, c)]
                rf, Jf = pf.rows(x0, jac=True)
                want_r = np.sqrt(2 * 50.0 * (e - pf.target))
                check("(c') force row is sqrt(2 F (E - target))", abs(rf[0] - want_r) < 1e-9, (rf[0], want_r))
                check("(c') force Jacobian F / r", abs(Jf[0, c] - 50.0 / want_r) < 1e-4 * (50.0 / want_r), (Jf[0, c], 50.0 / want_r))
                h = 1e-5
                v = x0.copy(); v[c] += h; rp, _ = pf.rows(v); v[c] -= 2 * h; rm, _ = pf.rows(v)
                check("(c') force Jacobian = finite difference of the row", abs((rp[0] - rm[0]) / (2 * h) - Jf[0, c]) < 1e-4 * abs(Jf[0, c]))
            finally:
                poleguard.reduced_det, poleguard.extra_bound_zeros = orig_rd, orig_ez
            # (d) a bound pole is one with Gamma = 0 wherever it sits (v2k: 7/2+ at 4.151 > e_min); with the push on the
            # guard tests the continuum count only
            start = [("1/2+", 3.0, 0.0, 0.87)]
            new_bound = start + [("7/2+", g.e_min + 0.001, 0.0, 8.47)]
            new_cont = start + [("7/2+", g.e_min + 0.5, 1e-6, 8.47)]
            check("(d) counts: a Gamma = 0 pole above e_min is bound", g.counts(new_bound) == (0, 2), g.counts(new_bound))
            check("(d) bound test on: a new bound pole is worse", g.worse(new_bound, start))
            g.bound_test = False
            check("(d) bound test off: a new bound pole is not worse, a new continuum one is",
                  (not g.worse(new_bound, start)) and g.worse(new_cont, start))
            # (d'') "continuum" (the default under a push, v2m 2026-11-28): a new Gamma = 0 pole at E >= e_min is worse
            # (the push cannot see it: det A^-1 is complex there), a new bound zero below e_min is the push's
            g.bound_test = "continuum"
            below = start + [("3/2-", g.e_min - 2.0, 0.0, 4.55)]
            check("(d'') continuum: a new Gamma = 0 pole above e_min is worse, one below e_min is not, a continuum one is",
                  g.worse(new_bound, start) and (not g.worse(below, start)) and g.worse(new_cont, start))
            pol = BoundsPolicy(pole_guard=cfg)
            lines = []
            polish(ev, x0, policy=pol, max_nfev=2, log=lines.append)
            check("(d'') polish under a push runs (local.py guard_bound default)",
                  any("pole push:" in l for l in lines))
            g.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if not failures else f"FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
