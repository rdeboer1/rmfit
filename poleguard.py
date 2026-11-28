"""Pole guard: keep a fit from building narrow poles that sit on no level of their J^pi (pyazr 3 only).

Why (an archived campaign, 2026-11-24..27): a collective pole of one J^pi's level matrix (large sub-threshold
amplitudes and their Brune closed-channel shifts) made a narrow peak in a bare total cross section MeV away from any
level of that J^pi.  A theta^2 cap only moved it (by about a MeV, down to an eV-scale width); removing the level that
carried it let the refit rebuild it from the other levels of the group.  It is too narrow for any data point, so the chi2 never objects.
the evaluator 2026-11-27 chose "a check in the polish that rejects such steps".

Method: for each J^pi group, the phase of det A^-1 (``pyazr.Session.jpi_block``) on the real E_x axis.  A pole E_p - i G/2
near the axis turns the phase by ~pi across ~G, so the steepest slope gives G ~ 2 / max d(arg)/dE.  A coarse grid cannot step
over it (the whole turn shows between two neighbours however narrow the pole); intervals where the phase moves by more than
0.3 rad are zoomed until the slope is resolved.  A narrow pole (G < gamma_max) is SPURIOUS when no level of its own J^pi lies
within max(near, near_factor * G) of it, the level energies taken at the same parameter vector (jpi_block's ``levels``).

Use: the policy key ``pole_guard`` (BoundsPolicy.pole_guard), e.g.
    {"e_min": 4.15, "e_max": 14.0, "step": 0.002, "gamma_max": 0.001, "near": 0.002, "near_factor": 10, "jpi": "all"}
(energies in MeV of E_x).  Optional ``push`` (PolePush): penalty rows that drive the extra bound zeros of det A^-1 (fake
bound states) below a floor.  Below e_min (from bound_min) the guard also finds bound-state poles (zeros of the real det A^-1
where every channel is closed) and calls them spurious off-level the same way.  ``polish`` rejects every trial step with
more spurious poles than its start point, counted separately in the continuum and below threshold.
"""
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

DEFAULTS = dict(e_min=None, e_max=None, step=0.002, gamma_max=0.001, near=0.002, near_factor=10.0, jpi="all",
                bound_min=0.0, bound_step=0.002)


# A channel whose penetrability is below this counts as closed for the bound-region tests (an archived campaign, 2026-11-28: a
# state 6 keV above a neutron threshold, where the only open channel has l = 4 and P ~ 1e-15, has det A^-1 real to 1e-9
# relative, Gamma ~ 0; with "closed" meaning det_im == 0 exactly it sat unseen between S_n and the guard's e_min).
P_CLOSED = 1e-8


def _closed(b, di, p_closed=None):
    """True where every channel is closed (det_im == 0) or every open one has P < ``p_closed`` (default P_CLOSED)."""
    p_closed = P_CLOSED if p_closed is None else p_closed
    P = [np.asarray(ch["P"], float) for ch in b.get("channels", [])]
    pmax = np.max(np.vstack(P), axis=0) if P else np.zeros_like(di)
    return (di == 0) | (pmax < p_closed)


def _phase(sess, jg, E, x):
    b = sess.jpi_block(jg, E, x)
    return np.unwrap(np.angle(np.asarray(b["det_re"]) + 1j * np.asarray(b["det_im"]))), b


def narrow_poles(sess, jg, e_lo, e_hi, x=None, step=2e-3, gmax=1e-3, depth=10) -> List[Tuple[float, float]]:
    """[(E_pole, Gamma)] (MeV) of the poles of J group ``jg`` with Gamma < ``gmax`` in [e_lo, e_hi] of E_x."""
    found = []

    def zoom(a, b, d):
        if not b - a > 1e-12 * max(1.0, abs(a)):         # the turn is narrower than the float spacing: Gamma ~ 0
            return 0.5 * (a + b), 0.0
        E = np.linspace(a, b, 41)
        ph, _ = _phase(sess, jg, E, x)
        dph = np.abs(np.diff(ph))
        i = int(np.argmax(dph))
        slope = dph[i] / (E[1] - E[0])
        if dph[i] < 0.3 or d == 0:
            return 0.5 * (E[i] + E[i + 1]), (2.0 / slope if slope > 0 else np.inf)
        return zoom(E[max(i - 1, 0)], E[min(i + 2, 40)], d - 1)

    E = np.arange(e_lo, e_hi + step / 2, step)
    ph, _ = _phase(sess, jg, E, x)
    dph = np.abs(np.diff(ph))
    for i in np.flatnonzero(dph > 0.3):
        e, g = zoom(E[i], E[i + 1], depth)
        if g < gmax:
            found.append((float(e), float(g)))
    merged: List[Tuple[float, float]] = []
    for e, g in sorted(found):
        if merged and abs(e - merged[-1][0]) < 2 * step:
            if g < merged[-1][1]:
                merged[-1] = (e, g)
        else:
            merged.append((e, g))
    return merged


def bound_poles(sess, jg, e_lo, e_hi, x=None, step=5e-4, fine_span=0.02, fine_step=1e-4) -> List[float]:
    """E_x (MeV) of the real-axis zeros of det A^-1 of J group ``jg`` in [e_lo, e_hi] where every channel is closed
    (det_im = 0, or P < P_CLOSED in every open one): bound-state poles.  A level matrix pole pushed below the lowest threshold becomes one of these (an
    archived campaign, 2026-11-27: zeroing or scaling down a level moved the collective pole a few hundred keV, to just
    below the lowest threshold), where the phase test sees nothing."""
    if not e_hi > e_lo:
        return []

    def scan(E):
        b = sess.jpi_block(jg, E, x)
        d, di = np.asarray(b["det_re"]), np.asarray(b["det_im"])
        ok = _closed(b, di) & np.isfinite(d)
        out = []
        for i in np.flatnonzero(ok[:-1] & ok[1:] & (np.sign(d[:-1]) * np.sign(d[1:]) < 0)):
            a, c = E[i], E[i + 1]
            out.append(float(a - d[i] * (c - a) / (d[i + 1] - d[i])))     # linear interpolation of the zero
        return out, ok

    E = np.arange(e_lo, e_hi + step / 2, step)
    out, ok = scan(E)
    last = np.flatnonzero(ok)
    if last.size == 0 or fine_step >= step:
        return out
    # the last fine_span below threshold again at fine_step (v2k 2026-11-27: a 1/2- zero 3 keV below S_n, in the last grid
    # step whose upper point is past threshold, was found or missed at random)
    f_lo = float(E[max(0, int(np.searchsorted(E, E[last[-1]] - fine_span)) - 1)])
    out = [e for e in out if e < f_lo]
    fine, _ = scan(np.arange(f_lo, min(e_hi, E[last[-1]] + step) + fine_step / 2, fine_step))
    return out + fine


def reduced_det(sess, jg, E, x=None) -> np.ndarray:
    """g(E) = det A^-1(E) / prod_lambda (E - E_lambda) of J group ``jg`` (real part; NaN where a channel is open with P >= P_CLOSED).

    In Brune's parametrization row lambda of A^-1 vanishes at E = E_lambda, so every level energy is a zero of det A^-1
    by construction; g has only the EXTRA zeros (an archived campaign, 2026-11-27: three J^pi groups, a few MeV below
    the lowest threshold, on no known level) and is smooth through the levels, so a zero can be followed as it passes one."""
    E = np.atleast_1d(np.asarray(E, float))
    b = sess.jpi_block(jg, E, x)
    d, di = np.asarray(b["det_re"], float), np.asarray(b["det_im"], float)
    lv = np.array([float(L["E_level"]) for L in b["levels"]], float)
    with np.errstate(all="ignore"):
        den = np.prod(E[:, None] - lv[None, :], axis=1) if lv.size else np.ones_like(E)
        g = d / den
    g[~_closed(b, di) | ~np.isfinite(g)] = np.nan
    return g


def _sign_change_zeros(sess, jg, E, g, x, xtol):
    from scipy.optimize import brentq
    ok = np.isfinite(g)
    out = []
    for i in np.flatnonzero(ok[:-1] & ok[1:] & (np.sign(g[:-1]) * np.sign(g[1:]) < 0)):
        f = lambda e: float(reduced_det(sess, jg, [e], x)[0])
        try:
            out.append(float(brentq(f, E[i], E[i + 1], xtol=xtol)))
        except (ValueError, RuntimeError):
            out.append(float(E[i] - g[i] * (E[i + 1] - E[i]) / (g[i + 1] - g[i])))
    return out


def extra_bound_zeros(sess, jg, e_lo, e_hi, x=None, step=2e-3, xtol=1e-7, fine_span=0.02, fine_step=1e-4) -> List[float]:
    """E_x (MeV) of the zeros of ``reduced_det`` in [e_lo, e_hi] where every channel is closed, refined by brentq.

    The last ``fine_span`` MeV below the threshold (the last grid point where g is finite) and the part of a grid step
    above it are scanned again at ``fine_step``: v2k 2026-11-27, a 1/2- pair of zeros at E_x 4.140, 3 keV below S_n,
    fell between two 5 keV grid points; it was seen in some trial steps and not in others, so the push penalty jumped
    by ~1.6e4 at random and the polish stalled."""
    if not e_hi > e_lo:
        return []
    E = np.arange(e_lo, e_hi + step / 2, step) + 1.234567e-7      # off any level energy written with few digits
    g = reduced_det(sess, jg, E, x)
    fin = np.flatnonzero(np.isfinite(g))
    if fin.size == 0:
        return []
    e_thr = E[fin[-1]]
    if not fine_span or fine_step >= step:
        return _sign_change_zeros(sess, jg, E, g, x, xtol)
    keep = E <= max(e_lo, e_thr - fine_span)
    f_lo = float(E[keep][-1]) if keep.any() else float(E[0])     # the fine grid starts AT the last coarse point: no gap
    out = _sign_change_zeros(sess, jg, E[keep], g[keep], x, xtol)
    Ef = np.arange(f_lo, min(e_hi, e_thr + step) + fine_step / 2, fine_step) + 1.234567e-7
    out += _sign_change_zeros(sess, jg, Ef, reduced_det(sess, jg, Ef, x), x, xtol)
    return sorted(set(round(e, 9) for e in out))


class PolePush:
    """Penalty rows that push the extra bound zeros of det A^-1 (fake bound states) DOWN, below ``floor`` (an archived
    campaign, 2026-11-27, at the evaluator's request).  Zeroing or scaling any single level or channel only moved them
    (or cost dchi2 >~ 1e4), so the fit is asked to find the cheapest path: for every extra zero E_k in [target, top] of
    the pushed J^pi groups, one residual row r_k = (E_k - target) / tau, with target = floor - margin so the push does
    not fade just above the floor.  The Jacobian row is the implicit derivative dE_k/dx_j = -(dg/dx_j) / (dg/dE) of the
    reduced determinant g (central differences, only the parameters of that J^pi).  The row count is fixed at the start
    (zeros found then + ``spare`` per group); absent zeros give zero rows.

    cfg (``pole_guard["push"]``): {"floor": -5.0, "margin": 2.0, "tau": 0.1, "jpi": "all" | [..], "spare": 1,
    "step": <bound_step>, "force": None}.  With ``force`` F (chi2 per MeV) the row is r_k = sqrt(2 F (E_k - target)) instead:
    the penalty 2 F (E_k - target) pushes every zero with the same force however deep it sits (the evaluator
    2026-11-27, push the zeros tens to hundreds of MeV deep out too: with a linear row a floor near -210 would push the
    shallow zeros ~200x harder than the deep ones).  Every group (of ``jpi``) gets push slots; the guard's count
    test (continuum only while the push is on) and the spare slots keep any group from growing one."""

    def __init__(self, guard: "PoleGuard", cfg: dict, x0, n: int, log=None):
        self.g = guard
        self.n = int(n)
        self.floor = float(cfg.get("floor", -5.0))
        self.target = self.floor - float(cfg.get("margin", 2.0))
        self.tau = float(cfg.get("tau", 0.1))
        self.force = None if cfg.get("force") in (None, 0) else float(cfg["force"])
        self.step = float(cfg.get("step", guard.cfg["bound_step"]))
        # up to a little above the guard's e_min: the threshold in the model's own masses can sit a few keV above it (v2k
        # 2026-11-27: a 7/2+ bound zero at 4.151 with e_min 4.15); reduced_det is NaN once a channel opens
        self.top = guard.e_min + float(cfg.get("top_margin", 0.05))
        want = cfg.get("jpi", "all")
        want = None if want in (None, "all") else set([want] if isinstance(want, str) else want)
        jg_of = {}
        for p in guard.sess.parameters:
            if p.free_index is not None and p.kind in ("width", "energy") and p.jgroup is not None:
                jg_of[int(p.free_index)] = int(p.jgroup)
        self.cols = {jg: [(i, j) for i, j in guard.map if jg_of.get(i) == jg] for jg in guard.groups}
        z0 = self.zeros(x0)
        spare = int(cfg.get("spare", 1))
        # every pushed group gets slots, also one with no extra zero at the start: a step that creates one (v2k 2026-11-27:
        # the 7/2+ collective pole coming back bound at E_x 4.151) is then pushed down too instead of blocking the fit
        self.slots = {jg: len(z) + spare for jg, z in z0.items() if want is None or guard.groups[jg] in want}
        if log:
            log(f"  pole push: extra bound zeros above {self.target:g} MeV pushed below it (removed below the floor "
                f"{self.floor:g}), " + (f"constant force {self.force:g} chi2/MeV" if self.force else f"tau {self.tau * 1e3:g} keV")
                + f"; at the start: {self.text(z0)}")

    def zeros(self, x) -> Dict[int, List[float]]:
        gv = self.g.vector(x)
        return {jg: sorted(extra_bound_zeros(self.g.sess, jg, self.target, self.top, gv, step=self.step), reverse=True)
                for jg in self.g.groups}

    def text(self, z) -> str:
        return "; ".join(f"{self.g.groups[jg]} " + ", ".join(f"{e:.4f}" for e in v) for jg, v in sorted(z.items()) if v) or "none"

    def above_floor(self, x) -> Dict[str, List[float]]:
        return {self.g.groups[jg]: [e for e in v if e > self.floor] for jg, v in self.zeros(x).items()
                if any(e > self.floor for e in v)}

    def _row(self, e) -> float:
        d = max(e - self.target, 0.0)
        return float(np.sqrt(2.0 * self.force * d)) if self.force else d / self.tau

    def _drde(self, e) -> float:
        if self.force:
            return self.force / max(self._row(e), 0.1)
        return 1.0 / self.tau

    def rows(self, x, jac=False, want=None):
        nrow = sum(self.slots.values())
        r = np.zeros(nrow)
        J = np.zeros((nrow, self.n)) if jac else None
        if nrow == 0:
            return r, J
        gv = self.g.vector(x)
        wset = None if want is None else set(int(c) for c in np.atleast_1d(want))
        k = 0
        for jg, ns in sorted(self.slots.items()):
            zs = sorted(extra_bound_zeros(self.g.sess, jg, self.target, self.top, gv, step=self.step), reverse=True)[:ns]
            for m, e in enumerate(zs):
                r[k + m] = self._row(e)
            if jac:
                for m, e in enumerate(zs):
                    h = 1e-5
                    gp, gm = reduced_det(self.g.sess, jg, [e + h, e - h], gv)
                    dgde = (gp - gm) / (2 * h)
                    if not np.isfinite(dgde) or dgde == 0:
                        continue
                    drde = self._drde(e)
                    for i, j in self.cols[jg]:
                        if wset is not None and j not in wset:
                            continue
                        dx = 1e-5 * max(abs(gv[i]), 1e-3)
                        v = gv.copy(); v[i] += dx
                        fp = reduced_det(self.g.sess, jg, [e], v)[0]
                        v[i] -= 2 * dx
                        fm = reduced_det(self.g.sess, jg, [e], v)[0]
                        if np.isfinite(fp) and np.isfinite(fm):
                            J[k + m, j] = -((fp - fm) / (2 * dx)) / dgde * drde
            k += ns
        return r, J


class PoleGuard:
    """``guard(x)`` -> the spurious narrow poles at the evaluator's vector ``x``: [(jpi, E_pole, Gamma, nearest level)]."""

    def __init__(self, ev, cfg: dict, log=None):
        from .backend import PYAZR3
        if not PYAZR3:
            raise NotImplementedError("pole_guard needs pyazr 3 (Session.jpi_block)")
        import pyazr
        from .keys import build_keys
        self.cfg = dict(DEFAULTS, **(cfg or {}))
        azr = getattr(ev, "base_azr", None) or ev.azr
        flags = dict(getattr(ev, "flags", {}) or {})
        self.sess = pyazr.Session(azr, cwd=os.path.dirname(os.path.abspath(azr)), **flags)
        P = self.sess.parameters
        self.x0 = np.array(P.x0, float)
        gkeys = build_keys(self.sess)
        pos = {str(k): j for j, k in enumerate(ev.keys)}
        # guard free index -> evaluator column (level parameters must all map; nuisances do not matter here)
        self.map = []
        for i, k in enumerate(gkeys):
            if k is None:
                continue
            j = pos.get(str(k))
            if j is None:
                if k.kind in ("energy", "width"):
                    raise ValueError(f"pole_guard: level parameter {k} of {os.path.basename(azr)} is not among the evaluator's keys")
                continue
            self.map.append((i, j))
        self.groups: Dict[int, str] = {}
        for p in P:
            if p.kind in ("width", "energy") and p.jgroup is not None:
                self.groups[int(p.jgroup)] = p.jpi
        want = self.cfg["jpi"]
        if want not in (None, "all"):
            want = set([want] if isinstance(want, str) else want)
            self.groups = {g: j for g, j in self.groups.items() if j in want}
        lv = [p.level_energy for p in P if p.kind in ("width", "energy")]
        self.e_min = float(self.cfg["e_min"] if self.cfg["e_min"] is not None else min(lv) - 0.5)
        self.e_max = float(self.cfg["e_max"] if self.cfg["e_max"] is not None else max(e for e in lv if e < 30) + 0.5)
        self._last = (None, None)
        self.bound_test = True       # True, False, or "continuum" (only Gamma = 0 poles at E >= e_min: under a PolePush)
        if log:
            log(f"  pole guard: {len(self.groups)} J^pi group(s) {sorted(set(self.groups.values()))}, E_x {self.e_min:g}-{self.e_max:g} MeV, "
                f"step {self.cfg['step'] * 1e3:g} keV, narrow < {self.cfg['gamma_max'] * 1e3:g} keV, off-level beyond "
                f"max({self.cfg['near'] * 1e3:g} keV, {self.cfg['near_factor']:g} Gamma)")

    def vector(self, x):
        g = self.x0.copy()
        x = np.asarray(x, float)
        for i, j in self.map:
            g[i] = x[j]
        return g

    def __call__(self, x) -> List[Tuple[str, float, float, float]]:
        if self._last[0] is not None and np.array_equal(self._last[0], x):
            return self._last[1]
        g = self.vector(x)
        out = []
        for jg, jpi in sorted(self.groups.items()):
            poles = narrow_poles(self.sess, jg, self.e_min, self.e_max, g, step=self.cfg["step"], gmax=self.cfg["gamma_max"])
            bound = [(e, 0.0) for e in bound_poles(self.sess, jg, float(self.cfg["bound_min"]), self.e_min, g,
                                                   step=self.cfg["bound_step"])]
            if not poles and not bound:
                continue
            levels = [float(L["E_level"]) for L in self.sess.jpi_block(jg, [self.e_min], g)["levels"]]
            for e, gam in poles + bound:
                near = min(levels, key=lambda L: abs(L - e)) if levels else np.inf
                if abs(near - e) > max(self.cfg["near"], self.cfg["near_factor"] * gam):
                    out.append((jpi, e, gam, near))
        self._last = (np.array(x, float), out)
        return out

    def counts(self, bad) -> Tuple[int, int]:
        """(continuum, bound) numbers of spurious poles: a bound one has Gamma = 0 (a real zero of det A^-1)."""
        nb = sum(1 for _, e, gam, _ in bad if gam == 0.0)
        return len(bad) - nb, nb

    def worse(self, bad, start) -> bool:
        """More spurious poles than ``start`` in the continuum or below threshold (a bound pole climbing into the
        continuum counts as worse)."""
        c, b = self.counts(bad)
        c0, b0 = self.counts(start)
        if self.bound_test == "continuum":
            # under a PolePush (v2m 2026-11-28): the push sees only zeros where every channel is closed, so a Gamma = 0
            # pole at or above e_min (7/2+ at 4.165, 22 keV above S_n in an l = 4 channel) is the guard's to reject;
            # bound zeros below e_min are the push's
            nb = lambda L: sum(1 for _, e, gam, _ in L if gam == 0.0 and e >= self.e_min)
            return c > c0 or nb(bad) > nb(start)
        return c > c0 or (bool(self.bound_test) and b > b0)

    @staticmethod
    def text(bad) -> str:
        return "; ".join(f"{j} E_x {e:.5f} MeV " + (f"Gamma {g * 1e6:.1f} eV" if g > 0 else "BOUND") + f" (nearest level {n:.4f})"
                         for j, e, g, n in bad) or "none"

    def close(self):
        try:
            self.sess.close()
        except Exception:
            pass
