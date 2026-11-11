"""rmfit uq -- uncertainty quantification as the standard last stage of a campaign (DESIGN.md Phase 4, 2026-11-10).

export -> saturation check -> Laplace covariance at the mode -> NUTS chains -> convergence gates -> linear vs sampled band.
Everything engine-side is pyazr: ``pyazr.sampling`` (NUTS, R-hat, ESS, ``AzurePosterior`` = exp(-objective/2) with the
engine's adjoint gradient and its Gauss-Newton Laplace covariance), ``pyazr.bands`` (linear propagation sigma^2 = g^T C g on
an extrapolation grid).  This module only orders them, holds what must be held, gates the result and writes it down.

Stages (resumable; state in ``<dir>/uq/uq_state.json``, every product under ``<dir>/uq/``):

  EXPORT      the campaign's incumbent baked to ``uq/<name>.azr`` + ``.sav`` (fresh-session verified, ``Campaign.export``);
              a bare ``.azr`` + ``.sav`` pair can be given instead (``python3 -m rmfit.uq <azr> <sav>``).
  SETUP       one session: the mode x, names, kinds, chi2, N.  Park's J = 1 - sum gamma^2 dS/dE of every level from a Park
              session on the exported file (the two bases read the same physical widths): a level with J < j_saturated is
              SATURATED -- its widths sit at the channel-radius ceiling and the data do not set them; the Brune Hessian is
              singular along them (Brune_vs_Park_Claude_eval/10-24-26_correlation) -- so its parameters are HELD at the mode.
              Levels with J in (j_saturated, 0.9) and two particle channels are listed: Park would decorrelate them, which
              matters for emcee and not for NUTS with a dense metric (11-06-26_nuts).  Norms are sampled unless
              ``sample_norms`` is false.  Then the Laplace covariance C of the sampled block (J^T J + penalty Hessian + priors)^-1.
  SAMPLE      ``chains`` NUTS chains from mode + ``start_jitter_sd`` x Laplace sd, inverse metric C (adapted in warm-up),
              ``target_accept`` 0.9 (the 11-06 run had 2.4 % divergences at 0.8), checkpoints every 50 iterations per chain.
  GATES       split R-hat <= rhat_max, min bulk ESS >= ess_min, divergent fraction <= divergent_max_frac, E-BFMI >= bfmi_min.
              A failed gate re-runs SAMPLE with ``extend_factor`` x the draws and warm-up, ``max_attempts`` times; after that
              the stage reports FAIL (the drive queues a wait decision ``uq-gates``).
  BANDS       on the spec's ``uq.bands`` grids (or the model's own energy-scan <segmentsTest> entries, one per
              entrance/exit/observable, at most ``bands_max``): the LINEAR band from C restricted to the free R-matrix block
              (``pyazr.bands.uncertainty_bands`` in an extrapolation session with the campaign's flags -- NOT
              ``extrapolation_bands``, which opens the session with pyazr's default flags), the same scaled by sqrt(chi2/nu)
              (Birge; reported, not adopted), and the SAMPLED band: ``band_draws`` posterior draws evaluated on the grids,
              percentiles 2.5 / 16 / 50 / 84 / 97.5.  Per grid: a .dat table, a figure, and the comparison at the lowest
              energy (sampled half-width / linear sigma, median offset in sigma).
  REPORT      ``UQ.md``.

Spec section ``uq`` (all optional; ``enabled`` makes the drive run the stage after its last cycle)::

    "uq": {"enabled": true, "chains": 4, "warmup": 1000, "draws": 2000, "target_accept": 0.9, "j_saturated": 0.01,
           "sample_norms": true, "priors": {"<engine parameter name>": [mean, sigma]}, "temper": 1.0,
           "bands": [{"entrance": 2, "exit": -1, "e_min": 0.01, "e_max": 3.0, "e_step": 0.01, "observable": "total-capture",
                      "quantity": "sfactor", "label": "3He(a,g)7Be"}],
           "rhat_max": 1.01, "ess_min": 400, "divergent_max_frac": 0.01, "bfmi_min": 0.3, "max_attempts": 2}

What is NOT done here: a change of parametrization (the chains run in the campaign's basis; ``parametrization: park`` in the
spec is the campaign's choice, made before the fit), error inflation (the Birge-scaled linear band is printed beside the
plain one; adopting it is the evaluator's), priors on R-matrix parameters beyond ``uq.priors`` (the objective's norm
penalties are inside the posterior already), and anything about which data sets are in (the spec decided that).
"""
import glob
import json
import os
import sys
import time
from typing import Callable, Dict, List, Optional

import numpy as np

DEFAULTS = dict(enabled=False, j_saturated=0.01, sample_norms=True, chains=4, warmup=1000, draws=2000, target_accept=0.9,
                max_tree_depth=10, start_jitter_sd=0.1, seed=11, temper=1.0, priors=None,
                rhat_max=1.01, ess_min=400, divergent_max_frac=0.01, bfmi_min=0.3, max_attempts=2, extend_factor=2.0,
                band_draws=400, bands=None, bands_max=6, grid_min_points=10, figures=True)
RMATRIX_KINDS = ("energy", "width")
STAGES = ["EXPORT", "SETUP", "SAMPLE", "GATES", "BANDS", "REPORT"]


def config(spec_uq: Optional[dict]) -> dict:
    cfg = dict(DEFAULTS)
    for k, v in (spec_uq or {}).items():
        cfg[k] = v
    cfg["chains"] = max(2, int(cfg["chains"]))
    return cfg


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def _child(fn, *args, **kw):
    """Run ``fn(*args, **kw)`` in a fresh spawned process (one engine session per interpreter) and return its result."""
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    with ctx.Pool(1) as pool:
        return pool.apply(fn, args, kw)


def _session_flags(flags: dict) -> dict:
    return {k: v for k, v in dict(flags or {}).items() if k in ("use_brune", "use_park", "ignore_externals", "use_long_wavelength")}


# ---------------------------------------------------------------------------------------------------------------------
# SETUP (children)

def _setup_mode(azr, sav, flags):
    """Mode vector and bookkeeping from one data-mode session."""
    from pyazr import azure2
    cwd = os.path.dirname(azr)
    with azure2(azr, cwd=cwd, **_session_flags(flags)) as m:
        x = np.asarray(m.load_sav(sav), float) if sav else np.asarray(m.params_rwa, float)
        free = sorted((p for p in m.parameters if not p.fixed), key=lambda p: p.free_index)
        names = [p.name for p in free]
        kinds = [p.kind for p in free]
        level_of = [(p.jgroup, p.level) if p.kind in RMATRIX_KINDS else None for p in free]
        obj = float(m.objective(x))
        chi2, _ = m.chi2_and_grad(x)
        r, _ = m.residual_jacobian(x)
        pen = m.penalties(x)
        pen = {k: (float(np.sum(v)) if hasattr(v, "__len__") else float(v)) for k, v in pen.items()}
        lv = []
        for key, ps in m.parameters.by_physical_level().items():
            npart = len({(q.pair, q.L, q.S) for q in ps if q.kind == "width" and not q.fixed and q.radiation_type == "P"})
            lv.append(dict(label=str(key), jgroup=int(getattr(key, "jgroup", ps[0].jgroup)), level=int(getattr(key, "level", ps[0].level)),
                           energy=float(key.energy if getattr(key, "energy", None) is not None else (ps[0].level_energy if ps[0].level_energy is not None else np.nan)),
                           names=[q.name for q in ps if not q.fixed], nfree=sum(1 for q in ps if not q.fixed), n_particle_channels=npart))
    return dict(x=x.tolist(), names=names, kinds=kinds, level_of=level_of, objective=obj, chi2=float(chi2), npts=int(r.size),
                penalties=pen, levels=lv)


def _park_J(azr, x_full, kinds, flags):
    """Park's J of every physical level from a Park session on the SAME file.  The .azr's level parameters are physical
    (basis-free), so the Park session takes them from the file; the norms, shifts and other non-R-matrix parameters come
    from the Brune session's vector (a .sav is basis-tagged and refused across bases).  The Park objective must then
    equal the Brune one."""
    from pyazr import azure2
    fl = _session_flags(flags)
    fl.pop("use_brune", None)
    fl["use_park"] = True
    cwd = os.path.dirname(azr)
    with azure2(azr, cwd=cwd, **fl) as P:
        xP = np.asarray(P.params_rwa, float)
        xB = np.asarray(x_full, float)
        if xP.size != xB.size:
            raise ValueError(f"Park session has {xP.size} free parameters, the Brune session {xB.size}")
        for j, k in enumerate(kinds):
            if k not in RMATRIX_KINDS:
                xP[j] = xB[j]
        J = np.asarray(P.park_norms(xP), float)
        keys = [str(k) for k in P.physical_levels()]
        oP = float(P.objective(xP))
    return dict(J=J.tolist(), levels=keys, objective_park=oP)


def _laplace(azr, flags, idx, x_full, priors, temper, workdir):
    """Gauss-Newton Laplace covariance of the sampled block at the mode (AzurePosterior.laplace_covariance)."""
    from pyazr.sampling import AzurePosterior
    T = AzurePosterior(azr, flags=_session_flags(flags), sample=list(idx), x_template=np.asarray(x_full, float),
                       priors=priors or None, temper=float(temper), workdir=None)
    th = T.x0
    lp, g = T(th)
    t0 = time.time()
    C = T.laplace_covariance(th)
    C = 0.5 * (C + C.T)
    ev = np.linalg.eigvalsh(C)
    return dict(C=C, theta0=th, logp=float(lp), grad_norm=float(np.linalg.norm(g)), eig_min=float(ev.min()), eig_max=float(ev.max()),
                seconds=time.time() - t0)


# ---------------------------------------------------------------------------------------------------------------------
# SAMPLE

class Checkpoint:
    """nuts() callback: progress every 100 iterations, every position and stat to ``<dir>/ckpt_<pid>.npz`` every 50."""

    def __init__(self, outdir, n_warmup, tag):
        self.dir, self.nw, self.tag = outdir, int(n_warmup), tag
        self.t0, self.q, self.st, self.buf = None, [], [], []

    def __call__(self, it, q, st):
        if self.t0 is None:
            self.t0 = time.time()
        self.buf.append(st)
        self.q.append(np.array(q, float))
        self.st.append([st["accept"], st["n_leapfrog"], st["depth"], st["divergent"], st["energy"]])
        if (it + 1) % 50 == 0:
            np.savez(os.path.join(self.dir, f"ckpt_{self.tag}_{os.getpid()}.npz"), q=np.array(self.q), st=np.array(self.st), nw=self.nw)
        if (it + 1) % 100 == 0:
            b, self.buf = self.buf, []
            print(f"[chain pid {os.getpid()}] it {it+1} {'warm' if it < self.nw else 'draw'}: depth {np.mean([s['depth'] for s in b]):.1f} "
                  f"leapfrog {np.mean([s['n_leapfrog'] for s in b]):.1f} accept {np.mean([s['accept'] for s in b]):.3f} "
                  f"div {int(sum(s['divergent'] for s in b))}  {time.time()-self.t0:.0f} s", flush=True)


def _run_chains(azr, flags, idx, x_full, priors, temper, C, theta0, cfg, outdir, nprocs, threads, tag, log):
    from pyazr.sampling import AzurePosterior, sample
    os.environ["OMP_NUM_THREADS"] = str(int(threads))
    T = AzurePosterior(azr, flags=_session_flags(flags), sample=list(idx), x_template=np.asarray(x_full, float),
                       priors=priors or None, temper=float(temper), workdir=os.path.join(outdir, "work"))
    sd = np.sqrt(np.clip(np.diag(C), 0, None))
    rng = np.random.default_rng(int(cfg["seed"]))
    nch = int(cfg["chains"])
    x0 = np.asarray(theta0, float) + float(cfg["start_jitter_sd"]) * sd * rng.standard_normal((nch, len(theta0)))
    for f in glob.glob(os.path.join(outdir, f"ckpt_{tag}_*.npz")):
        os.remove(f)
    log(f"uq SAMPLE {tag}: {nch} chains x ({cfg['warmup']} warm-up + {cfg['draws']} draws), {len(theta0)} parameters, "
        f"target_accept {cfg['target_accept']}, {nprocs} processes x {threads} threads")
    t0 = time.time()
    r = sample(T, x0, n_chains=nch, nprocs=int(nprocs), seed=int(cfg["seed"]) + 100, n_warmup=int(cfg["warmup"]), n_draws=int(cfg["draws"]),
               inv_metric=np.asarray(C), target_accept=float(cfg["target_accept"]), max_tree_depth=int(cfg["max_tree_depth"]),
               callback=Checkpoint(outdir, cfg["warmup"], tag))
    np.savez(os.path.join(outdir, f"chains_{tag}.npz"), samples=r.samples, logp=r.logp, step_size=r.step_size,
             **{f"stat_{k}": v for k, v in r.stats.items()}, **{f"warm_{k}": v for k, v in r.warmup.items()}, seconds=r.seconds)
    log(f"uq SAMPLE {tag}: done in {(time.time()-t0)/3600:.2f} h; {r.summary().splitlines()[-2]}")
    return r


def _chains_from_checkpoints(outdir, tag, n_warmup, n_draws):
    """Assemble a chains_<tag>.npz from per-chain checkpoints when every chain reached warm-up + draws (a killed job)."""
    ck = [np.load(f) for f in sorted(glob.glob(os.path.join(outdir, f"ckpt_{tag}_*.npz")))]
    need = int(n_warmup) + int(n_draws)
    if not ck or any(c["q"].shape[0] < need for c in ck):
        return None
    nw = int(ck[0]["nw"])
    X = np.stack([c["q"][nw:need] for c in ck]); ST = np.stack([c["st"][nw:need] for c in ck]); WS = np.stack([c["st"][:nw] for c in ck])
    out = dict(samples=X, logp=np.zeros(X.shape[:2]), step_size=np.zeros(X.shape[0]),
               stat_accept=ST[:, :, 0], stat_n_leapfrog=ST[:, :, 1], stat_depth=ST[:, :, 2], stat_divergent=ST[:, :, 3], stat_energy=ST[:, :, 4],
               warm_n_leapfrog=WS[:, :, 1], seconds=0.0)
    np.savez(os.path.join(outdir, f"chains_{tag}.npz"), **out)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# GATES

def gates(chains: dict, C: np.ndarray, cfg: dict) -> dict:
    from pyazr.sampling import ess, split_rhat
    X = np.asarray(chains["samples"], float)
    rhat, e = split_rhat(X), ess(X)
    div = np.asarray(chains["stat_divergent"], float)
    en = np.asarray(chains["stat_energy"], float)
    bfmi = [float(np.sum(np.diff(c) ** 2) / max(np.sum((c - c.mean()) ** 2), 1e-300)) for c in en]
    sdS = X.reshape(-1, X.shape[2]).std(0)
    sdL = np.sqrt(np.clip(np.diag(C), 0, None))
    ratio = sdS / np.where(sdL > 0, sdL, np.inf)
    out = dict(chains=int(X.shape[0]), draws=int(X.shape[1]), dim=int(X.shape[2]),
               rhat_max=float(rhat.max()), rhat_argmax=int(rhat.argmax()), ess_min=float(e.min()), ess_argmin=int(e.argmin()),
               ess_median=float(np.median(e)), divergent=int(div.sum()), divergent_frac=float(div.mean()), bfmi_min=float(min(bfmi)),
               grad_per_draw=float(np.asarray(chains["stat_n_leapfrog"], float).mean()),
               mean_tree_depth=float(np.asarray(chains["stat_depth"], float).mean()),
               sd_ratio_min=float(ratio.min()), sd_ratio_median=float(np.median(ratio)), sd_ratio_max=float(ratio.max()),
               rhat=rhat.tolist(), ess=e.tolist(), sd_sampled=sdS.tolist(), sd_laplace=sdL.tolist(),
               mean_shift_sd=(np.abs(X.reshape(-1, X.shape[2]).mean(0) - np.asarray(chains.get("theta0", X.reshape(-1, X.shape[2]).mean(0)))) / np.where(sdS > 0, sdS, np.inf)).tolist())
    fails = []
    if out["rhat_max"] > float(cfg["rhat_max"]):
        fails.append(f"split R-hat {out['rhat_max']:.3f} > {cfg['rhat_max']}")
    if out["ess_min"] < float(cfg["ess_min"]):
        fails.append(f"min ESS {out['ess_min']:.0f} < {cfg['ess_min']}")
    if out["divergent_frac"] > float(cfg["divergent_max_frac"]):
        fails.append(f"divergent {100*out['divergent_frac']:.2f} % > {100*float(cfg['divergent_max_frac']):.1f} %")
    if out["bfmi_min"] < float(cfg["bfmi_min"]):
        fails.append(f"E-BFMI {out['bfmi_min']:.2f} < {cfg['bfmi_min']}")
    out["fails"] = fails
    out["passed"] = not fails
    return out


# ---------------------------------------------------------------------------------------------------------------------
# BANDS (child)

def _select_grids(m, cfg):
    """Spec grids, else the model's own energy-scan <segmentsTest> entries (one per entrance/exit/observable)."""
    if cfg.get("bands"):
        return [dict(g) for g in cfg["bands"]], None
    chosen, seen = [], set()
    for s in m.extrapolations:
        if not s.active or s.energy_step <= 0:
            continue
        npts = (s.energy_max - s.energy_min) / s.energy_step + 1
        if npts < int(cfg["grid_min_points"]):
            continue
        k = (s.entrance_key, s.exit_key, s.observable)
        if k in seen:
            continue
        seen.add(k)
        chosen.append(dict(key=int(s.key), entrance=int(s.entrance_key), exit=int(s.exit_key), e_min=float(s.energy_min), e_max=float(s.energy_max),
                           e_step=float(s.energy_step), observable=s.observable, quantity=("sfactor" if s.exit_key == -1 or s.observable != "differential" else "cross"),
                           label=f"{s.name} {s.observable}"))
        if len(chosen) >= int(cfg["bands_max"]):
            break
    return chosen, [g["key"] for g in chosen]


def _bands(azr, flags, kinds, x_full, C_full, samples_full, cfg, outdir):
    """Linear (Laplace) and sampled bands on the grids; returns per-grid tables (c.m. MeV, values)."""
    from pyazr import azure2
    from pyazr.bands import trimmed_model, uncertainty_bands, rmatrix_columns
    cwd = os.path.dirname(azr)
    fl = _session_flags(flags)
    with azure2(azr, cwd=cwd, **fl) as m0:
        grids, keys = _select_grids(m0, cfg)
    if not grids:
        return dict(grids=[], note="no energy-scan grid in <segmentsTest> and no uq.bands in the spec")
    # pyazr 2.10.0 trimmed_model copies the EC cache into a workdir it has not created (FileNotFoundError when the main
    # run left an intEC.dat): give it an existing one.  Engine follow-up noted in DESIGN.md.
    workdir = os.path.join(cwd, "output", "bands", "uq")
    os.makedirs(workdir, exist_ok=True)
    if keys is not None:
        tmp, workdir = trimmed_model(azr, keys=keys, cwd=cwd, workdir=workdir)
    else:
        specs = [dict(entrance=g["entrance"], exit=g["exit"], e_min=g["e_min"], e_max=g["e_max"], e_step=g["e_step"], observable=g.get("observable", "total-capture"))
                 for g in grids]
        tmp, workdir = trimmed_model(azr, grids=specs, cwd=cwd, workdir=workdir)
    rm_idx = [j for j, k in enumerate(kinds) if k in RMATRIX_KINDS]
    x_full = np.asarray(x_full, float)
    out = dict(grids=[], tmp=tmp)
    try:
        with azure2(tmp, cwd=cwd, **fl) as m:
            m.extrap_mode()
            cols = rmatrix_columns(m)
            if len(cols) != len(rm_idx):
                raise RuntimeError(f"extrapolation session has {len(cols)} free R-matrix parameters, the data-mode vector {len(rm_idx)}")
            xr = x_full[rm_idx]
            Cr = np.asarray(C_full, float)[np.ix_(rm_idx, rm_idx)]
            n = len(grids)
            by_q = {}
            for i, g in enumerate(grids):
                by_q.setdefault(g.get("quantity", "sfactor"), []).append(i + 1)
            lin = {}
            for q, ks in by_q.items():
                lin.update({(k, q): b for k, b in uncertainty_bands(m, keys=ks, params=xr, covariance=Cr, quantity=q).items()})
            S = np.asarray(samples_full, float)
            vals = {q: [] for q in by_q}
            for d in range(S.shape[0]):
                xs = S[d][rm_idx]
                for q in by_q:
                    v = m.calculate_sfactor_rwa(xs) if q == "sfactor" else m.calculate_rwa(xs)
                    vals[q].append([np.asarray(v[k - 1], float) for k in by_q[q]])
            for q, ks in by_q.items():
                for j, k in enumerate(ks):
                    g = grids[k - 1]
                    b = lin[(k, q)]
                    A = np.stack([vals[q][d][j] for d in range(S.shape[0])])
                    pct = np.percentile(A, [2.5, 16, 50, 84, 97.5], axis=0)
                    tab = np.column_stack([b.energy, b.value, b.sigma, pct[2], pct[1], pct[3], pct[0], pct[4]])
                    name = f"uq_band_{k}_{(g.get('label') or 'grid').replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace(',', '')}"
                    path = os.path.join(outdir, name + ".dat")
                    np.savetxt(path, tab, header=f"{g.get('label','')}: {q}; columns E_cm(MeV) best sigma_linear median p16 p84 p2.5 p97.5 "
                                                 f"({S.shape[0]} posterior draws; linear = Laplace covariance)", fmt="%.6e")
                    half = 0.5 * (pct[3] - pct[1])
                    rel = half / np.where(np.abs(pct[2]) > 0, np.abs(pct[2]), np.inf)
                    out["grids"].append(dict(key=int(k), label=g.get("label", ""), quantity=q, npts=int(b.energy.size), table=path,
                                             e_cm=b.energy.tolist(), best=b.value.tolist(), sigma_lin=b.sigma.tolist(),
                                             median=pct[2].tolist(), p16=pct[1].tolist(), p84=pct[3].tolist(), p025=pct[0].tolist(), p975=pct[4].tolist(),
                                             rel_lin_min=float(b.relative.min()), rel_lin_max=float(b.relative.max()),
                                             rel_sampled_min=float(rel.min()), rel_sampled_max=float(rel.max()),
                                             ratio_half_to_lin=(half / np.where(b.sigma > 0, b.sigma, np.inf)).tolist(),
                                             median_offset_sd=((pct[2] - b.value) / np.where(b.sigma > 0, b.sigma, np.inf)).tolist()))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def _figure(g, path, chi2nu):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    E = np.asarray(g["e_cm"]); best = np.asarray(g["best"]); s = np.asarray(g["sigma_lin"])
    fig, ax = plt.subplots(2, 1, figsize=(6.5, 6), sharex=True, gridspec_kw=dict(height_ratios=[3, 1.4]))
    ax[0].fill_between(E, np.asarray(g["p025"]), np.asarray(g["p975"]), color="C0", alpha=0.15, label="sampled 95 %")
    ax[0].fill_between(E, np.asarray(g["p16"]), np.asarray(g["p84"]), color="C0", alpha=0.35, label="sampled 68 %")
    ax[0].plot(E, best - s, "C3--", lw=0.9, label="linear 1 sigma"); ax[0].plot(E, best + s, "C3--", lw=0.9)
    ax[0].plot(E, best, "k-", lw=1.0, label="best fit"); ax[0].plot(E, np.asarray(g["median"]), "C0-", lw=0.8, label="sampled median")
    ax[0].set_ylabel("S (MeV b)" if g["quantity"] == "sfactor" else "sigma (b)")
    if g["quantity"] != "sfactor":
        ax[0].set_yscale("log")
    ax[0].set_title(f"{g['label']}: linear (Laplace) vs sampled band", fontsize=10); ax[0].legend(fontsize=8, ncol=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        ax[1].plot(E, 100 * s / np.abs(best), "C3--", label="linear")
        ax[1].plot(E, 100 * s / np.abs(best) * np.sqrt(chi2nu), "C3:", label=f"linear x sqrt(chi2/nu = {chi2nu:.2f})")
        ax[1].plot(E, 100 * 0.5 * (np.asarray(g["p84"]) - np.asarray(g["p16"])) / np.abs(np.asarray(g["median"])), "C0-", label="sampled (p84-p16)/2")
    ax[1].set_ylabel("rel. unc. (%)"); ax[1].set_xlabel("E c.m. (MeV)"); ax[1].legend(fontsize=8); ax[1].set_ylim(bottom=0)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


# ---------------------------------------------------------------------------------------------------------------------
# the stage

class UQ:
    def __init__(self, directory, cfg: dict, log: Callable = print, azr=None, sav=None, flags=None, campaign=None, nprocs=None, threads=None):
        self.dir = os.path.abspath(directory)
        self.out = os.path.join(self.dir, "uq")
        os.makedirs(self.out, exist_ok=True)
        self.cfg = cfg
        self.log = log
        self.campaign = campaign
        self.azr, self.sav, self.flags = azr, sav, dict(flags or (campaign.flags if campaign is not None else {}))
        self.nprocs = int(nprocs or cfg["chains"])
        self.threads = int(threads or 1)
        self.state_path = os.path.join(self.out, "uq_state.json")
        self.state = json.load(open(self.state_path)) if os.path.exists(self.state_path) else dict(stages={}, attempt=0, started=_now(), cfg=cfg)
        self.state["cfg"] = cfg

    def save(self):
        with open(self.state_path, "w") as fh:
            json.dump(self.state, fh, indent=1, default=float)

    def done(self, stage):
        return stage in self.state["stages"]

    def mark(self, stage, **info):
        self.state["stages"][stage] = dict(when=_now(), **info)
        self.save()

    # -- stages ---------------------------------------------------------------------------------------------------
    def s_export(self):
        if self.done("EXPORT"):
            st = self.state["stages"]["EXPORT"]
            self.azr, self.sav = st["azr"], st["sav"]
            return
        if self.campaign is not None:
            name = os.path.splitext(os.path.basename(self.campaign.base_azr))[0]
            path = os.path.join(self.out, name + ".azr")
            azr, sav, sc = self.campaign.export(path=path, note="uq export")
            self.azr, self.sav = azr, sav
            self.log(f"uq EXPORT: {os.path.basename(azr)} objective {sc.objective:.3f}")
            obj = float(sc.objective)
        else:
            if not (self.azr and os.path.exists(self.azr)):
                raise FileNotFoundError(f"uq: no campaign and no .azr ({self.azr})")
            obj = None
        # the stage's sessions write under uq/output, never into the campaign's or the fit's output directory; the data
        # files (relative paths in the .azr) are reached through links to the source directory's entries, as AzurePosterior does
        from pyazr import AzrModel
        src_dir = os.path.dirname(os.path.abspath(self.campaign.base_azr if self.campaign is not None else self.azr))
        for e in os.listdir(src_dir):
            if e in ("output", "checks", "uq") or e.endswith(".azr") or e.endswith(".sav"):
                continue
            dst = os.path.join(self.out, e)
            if not os.path.lexists(dst):
                os.symlink(os.path.join(src_dir, e), dst)
        mdl = AzrModel.from_file(self.azr)
        os.makedirs(os.path.join(self.out, "output"), exist_ok=True)
        mdl.set_output_dir(os.path.join(self.out, "output"))
        local = os.path.join(self.out, os.path.basename(self.azr))
        mdl.write(local)
        if self.sav and os.path.abspath(os.path.join(self.out, os.path.basename(self.sav))) != os.path.abspath(self.sav):
            import shutil
            shutil.copy2(self.sav, os.path.join(self.out, os.path.basename(self.sav)))
            self.sav = os.path.join(self.out, os.path.basename(self.sav))
        self.azr = local
        self.mark("EXPORT", azr=self.azr, sav=self.sav, objective=obj)

    def s_setup(self):
        if self.done("SETUP"):
            return
        cfg = self.cfg
        t0 = time.time()
        md = _child(_setup_mode, self.azr, self.sav, self.flags)
        pk = _child(_park_J, self.azr, md["x"], md["kinds"], self.flags)
        self.log(f"uq SETUP: objective {md['objective']:.3f} (chi2 {md['chi2']:.3f}, N {md['npts']}, {len(md['names'])} free); Park session "
                 f"{pk['objective_park']:.3f} (rel {abs(pk['objective_park']-md['objective'])/max(md['objective'],1e-300):.1e})")
        J = dict(zip(pk["levels"], pk["J"]))
        names, kinds = md["names"], md["kinds"]
        held, sat, twoch = set(), [], []
        for lv in md["levels"]:
            j = J.get(lv["label"])
            if j is None:
                continue
            lv["J"] = float(j)
            if j < float(cfg["j_saturated"]):
                sat.append(lv)
                held |= set(lv["names"])
            elif j < 0.9 and (lv.get("n_particle_channels") or 0) >= 2:
                twoch.append(lv)
        if not cfg["sample_norms"]:
            held |= {n for n, k in zip(names, kinds) if k not in RMATRIX_KINDS}
        idx = [i for i, n in enumerate(names) if n not in held]
        self.log(f"uq SETUP: {len(sat)} saturated level(s) (J < {cfg['j_saturated']}) held: "
                 + (", ".join(f"{lv['label']} J {lv['J']:.1e} ({lv['nfree']} par)" for lv in sat) or "none")
                 + f"; {len(twoch)} level(s) with J in ({cfg['j_saturated']}, 0.9) and >= 2 particle channels (Park would decorrelate): "
                 + (", ".join(f"{lv['label']} J {lv['J']:.2f}" for lv in twoch) or "none")
                 + f"; sampling {len(idx)} of {len(names)} free ({'norms sampled' if cfg['sample_norms'] else 'norms held'})")
        priors = {k: tuple(v) for k, v in (cfg.get("priors") or {}).items()}
        lap = _child(_laplace, self.azr, self.flags, idx, md["x"], priors, cfg["temper"], self.out)
        self.log(f"uq SETUP: Laplace covariance of {len(idx)} parameters in {lap['seconds']:.0f} s; eigenvalues {lap['eig_min']:.3e} .. {lap['eig_max']:.3e}; "
                 f"|grad log p| at the mode {lap['grad_norm']:.3e}")
        if lap["eig_min"] <= 0:
            self.log("uq SETUP: WARNING the Laplace covariance is not positive definite; the metric starts from its diagonal")
            C = np.diag(np.clip(np.diag(lap["C"]), 1e-12, None))
        else:
            C = lap["C"]
        nu = md["npts"] - len(names)
        np.savez(os.path.join(self.out, "laplace.npz"), C=C, theta0=lap["theta0"], idx=np.array(idx, int), names=np.array(names), kinds=np.array(kinds),
                 x_full=np.array(md["x"], float), J_labels=np.array(pk["levels"]), J=np.array(pk["J"], float))
        self.mark("SETUP", objective=md["objective"], chi2=md["chi2"], npts=md["npts"], nfree=len(names), nu=nu, chi2nu=md["chi2"] / max(nu, 1),
                  n_sampled=len(idx), held=sorted(held), saturated=[dict(label=l["label"], J=l["J"], energy=l["energy"], nfree=l["nfree"]) for l in sat],
                  two_channel=[dict(label=l["label"], J=l["J"], energy=l["energy"]) for l in twoch], eig_min=lap["eig_min"], eig_max=lap["eig_max"],
                  grad_norm=lap["grad_norm"], penalties=md["penalties"], park_objective=pk["objective_park"], minutes=round((time.time() - t0) / 60, 1))

    def _load_setup(self):
        z = np.load(os.path.join(self.out, "laplace.npz"), allow_pickle=False)
        return dict(C=z["C"], theta0=z["theta0"], idx=z["idx"].tolist(), names=z["names"].tolist(), kinds=z["kinds"].tolist(), x_full=z["x_full"])

    def s_sample(self):
        if self.done("SAMPLE"):
            return
        s = self._load_setup()
        cfg = dict(self.cfg)
        att = int(self.state.get("attempt", 0))
        f = float(cfg["extend_factor"]) ** att
        cfg["warmup"] = int(round(cfg["warmup"] * f)); cfg["draws"] = int(round(cfg["draws"] * f)); cfg["seed"] = int(cfg["seed"]) + 1000 * att
        tag = f"a{att}"
        path = os.path.join(self.out, f"chains_{tag}.npz")
        if not os.path.exists(path):
            if _chains_from_checkpoints(self.out, tag, cfg["warmup"], cfg["draws"]) is not None:
                self.log(f"uq SAMPLE {tag}: assembled from the checkpoints of a killed job")
            else:
                priors = {k: tuple(v) for k, v in (cfg.get("priors") or {}).items()}
                _run_chains(self.azr, self.flags, s["idx"], s["x_full"], priors, cfg["temper"], s["C"], s["theta0"], cfg, self.out,
                            self.nprocs, self.threads, tag, self.log)
        z = np.load(path)
        self.mark("SAMPLE", tag=tag, attempt=att, warmup=cfg["warmup"], draws=cfg["draws"], chains=int(z["samples"].shape[0]),
                  seconds=float(z["seconds"]), grad_evaluations=int(np.asarray(z["stat_n_leapfrog"]).sum() + np.asarray(z["warm_n_leapfrog"]).sum()))

    def s_gates(self):
        if self.done("GATES") and self.state["stages"]["GATES"].get("passed"):
            return True
        s = self._load_setup()
        tag = self.state["stages"]["SAMPLE"]["tag"]
        z = np.load(os.path.join(self.out, f"chains_{tag}.npz"))
        ch = {k: z[k] for k in z.files}
        ch["theta0"] = s["theta0"]
        g = gates(ch, s["C"], self.cfg)
        names = [s["names"][i] for i in s["idx"]]
        g["rhat_argmax_name"], g["ess_argmin_name"] = names[g["rhat_argmax"]], names[g["ess_argmin"]]
        lines = [f"uq GATES {tag}: split R-hat max {g['rhat_max']:.3f} ({g['rhat_argmax_name']}), min ESS {g['ess_min']:.0f} ({g['ess_argmin_name']}), "
                 f"median ESS {g['ess_median']:.0f}, divergent {g['divergent']} ({100*g['divergent_frac']:.2f} %), E-BFMI min {g['bfmi_min']:.2f}, "
                 f"{g['grad_per_draw']:.1f} gradients per draw; sd(sampled)/sd(Laplace) {g['sd_ratio_min']:.2f} / {g['sd_ratio_median']:.2f} / {g['sd_ratio_max']:.2f}",
                 "uq GATES: " + ("PASS" if g["passed"] else "FAIL: " + "; ".join(g["fails"]))]
        for ln in lines:
            self.log(ln)
        json.dump(dict(g, names=names), open(os.path.join(self.out, f"gates_{tag}.json"), "w"), indent=1)
        slim = {k: v for k, v in g.items() if not isinstance(v, list)}
        self.mark("GATES", tag=tag, **slim)
        if not g["passed"]:
            att = int(self.state.get("attempt", 0))
            if att + 1 < int(self.cfg["max_attempts"]):
                self.state["attempt"] = att + 1
                self.state["stages"].pop("SAMPLE", None)
                self.state["stages"].pop("GATES", None)
                self.save()
                self.log(f"uq GATES: attempt {att + 2} of {self.cfg['max_attempts']} with {self.cfg['extend_factor']} x the draws and warm-up")
                return None
        return g["passed"]

    def s_bands(self):
        if self.done("BANDS"):
            return
        s = self._load_setup()
        tag = self.state["stages"]["SAMPLE"]["tag"]
        z = np.load(os.path.join(self.out, f"chains_{tag}.npz"))
        X = np.asarray(z["samples"], float)
        n = X.shape[0] * X.shape[1]
        nd = min(int(self.cfg["band_draws"]), n)
        pick = np.linspace(0, n - 1, nd).round().astype(int)
        flat = X.reshape(n, X.shape[2])[pick]
        full = np.repeat(np.asarray(s["x_full"], float)[None], nd, axis=0)
        full[:, s["idx"]] = flat
        C_full = np.zeros((len(s["names"]), len(s["names"])))
        C_full[np.ix_(s["idx"], s["idx"])] = s["C"]
        t0 = time.time()
        b = _child(_bands, self.azr, self.flags, s["kinds"], s["x_full"], C_full, full, self.cfg, self.out)
        chi2nu = float(self.state["stages"]["SETUP"]["chi2nu"])
        rows = []
        for g in b["grids"]:
            if self.cfg.get("figures", True):
                try:
                    _figure(g, os.path.join(self.out, f"uq_band_{g['key']}.png"), chi2nu)
                except Exception as err:  # noqa: BLE001
                    self.log(f"uq BANDS: figure for grid {g['key']} failed ({err})")
            i0 = 0
            rows.append(dict(key=g["key"], label=g["label"], quantity=g["quantity"], npts=g["npts"], table=os.path.basename(g["table"]),
                             e0=g["e_cm"][i0], best0=g["best"][i0], sigma_lin0=g["sigma_lin"][i0], median0=g["median"][i0], p16_0=g["p16"][i0], p84_0=g["p84"][i0],
                             rel_lin0=g["sigma_lin"][i0] / abs(g["best"][i0]) if g["best"][i0] else float("nan"),
                             rel_sampled0=0.5 * (g["p84"][i0] - g["p16"][i0]) / abs(g["median"][i0]) if g["median"][i0] else float("nan"),
                             ratio0=g["ratio_half_to_lin"][i0], offset0=g["median_offset_sd"][i0],
                             ratio_median=float(np.median(g["ratio_half_to_lin"])), ratio_max=float(np.max(g["ratio_half_to_lin"])),
                             offset_max=float(np.max(np.abs(g["median_offset_sd"]))), rel_lin_range=[g["rel_lin_min"], g["rel_lin_max"]],
                             rel_sampled_range=[g["rel_sampled_min"], g["rel_sampled_max"]]))
            self.log(f"uq BANDS {g['label']}: at E {g['e_cm'][0]:.4g} MeV best {g['best'][0]:.5g} +- {g['sigma_lin'][0]:.3g} linear "
                     f"({100*rows[-1]['rel_lin0']:.2f} %), sampled median {g['median'][0]:.5g} [{g['p16'][0]:.5g}, {g['p84'][0]:.5g}] "
                     f"({100*rows[-1]['rel_sampled0']:.2f} %); half-width/linear sigma {rows[-1]['ratio0']:.2f} (median over the grid {rows[-1]['ratio_median']:.2f}, "
                     f"max {rows[-1]['ratio_max']:.2f}); median offset {rows[-1]['offset0']:+.2f} sigma")
        self.mark("BANDS", draws=nd, grids=rows, note=b.get("note", ""), minutes=round((time.time() - t0) / 60, 1))

    def s_report(self):
        st = self.state["stages"]
        cfg = self.cfg
        su, ga, ba, sa = st.get("SETUP", {}), st.get("GATES", {}), st.get("BANDS", {}), st.get("SAMPLE", {})
        L = [f"# rmfit uq -- {os.path.basename(self.dir)} ({_now()})", "",
             f"Model `{os.path.relpath(self.azr, self.dir)}` + `{os.path.basename(self.sav) if self.sav else '-'}`; flags {json.dumps(_session_flags(self.flags))}; "
             f"objective {su.get('objective', float('nan')):.3f} = chi2 {su.get('chi2', float('nan')):.3f} + penalties; N {su.get('npts')}, "
             f"{su.get('nfree')} free, nu {su.get('nu')}, chi2/nu {su.get('chi2nu', float('nan')):.3f}.", "",
             "## Sampled set", "",
             f"- {su.get('n_sampled')} of {su.get('nfree')} free parameters sampled; {'norms sampled' if cfg['sample_norms'] else 'norms held at the fit (conditional posterior)'}.",
             f"- saturated levels held (Park J < {cfg['j_saturated']}): " + (", ".join(f"{l['label']} (J {l['J']:.1e}, {l['nfree']} par)" for l in su.get("saturated", [])) or "none")
             + ".  Their widths sit at the channel-radius ceiling; the data do not set them (azure2-eval skill, saturated poles).",
             f"- levels with J in ({cfg['j_saturated']}, 0.9) and >= 2 particle channels (Park would decorrelate them; irrelevant to NUTS with a dense metric): "
             + (", ".join(f"{l['label']} (J {l['J']:.2f})" for l in su.get("two_channel", [])) or "none") + ".",
             f"- priors beyond the objective's own penalties: {json.dumps(cfg.get('priors') or {})}; temper {cfg['temper']}.",
             f"- Laplace covariance eigenvalues {su.get('eig_min', float('nan')):.3e} .. {su.get('eig_max', float('nan')):.3e}; |grad log p| at the mode {su.get('grad_norm', float('nan')):.2e}.",
             "", "## Chains", "",
             f"- NUTS (pyazr.sampling): {sa.get('chains')} chains x ({sa.get('warmup')} warm-up + {sa.get('draws')} draws), attempt {sa.get('attempt', 0) + 1}, "
             f"target_accept {cfg['target_accept']}, dense metric from the Laplace covariance; {sa.get('grad_evaluations')} gradient evaluations in "
             f"{sa.get('seconds', 0)/3600:.2f} h on {self.nprocs} x {self.threads} slots.",
             f"- gates: split R-hat max {ga.get('rhat_max', float('nan')):.3f} ({ga.get('rhat_argmax_name')}) [<= {cfg['rhat_max']}], min ESS {ga.get('ess_min', float('nan')):.0f} "
             f"({ga.get('ess_argmin_name')}) [>= {cfg['ess_min']}], median ESS {ga.get('ess_median', float('nan')):.0f}, divergent {ga.get('divergent')} "
             f"({100*ga.get('divergent_frac', 0):.2f} % [<= {100*float(cfg['divergent_max_frac']):.1f} %]), E-BFMI min {ga.get('bfmi_min', float('nan')):.2f} [>= {cfg['bfmi_min']}], "
             f"{ga.get('grad_per_draw', float('nan')):.1f} gradients per draw: **{'PASS' if ga.get('passed') else 'FAIL'}**"
             + ("" if ga.get("passed") else " (" + "; ".join(ga.get("fails", [])) + ")") + ".",
             f"- sd(sampled) / sd(Laplace): min {ga.get('sd_ratio_min', float('nan')):.2f}, median {ga.get('sd_ratio_median', float('nan')):.2f}, max {ga.get('sd_ratio_max', float('nan')):.2f} "
             f"(1 = Gaussian posterior; the 7Be calibration run of 2026-11-06 gave 0.67-1.60, median 0.89).",
             "", "## Bands (linear = Laplace covariance on the free R-matrix block; sampled = posterior draws)", ""]
        if ba.get("grids"):
            L += ["| grid | quantity | E_cm (MeV) | best | linear 1 sigma | sampled median [p16, p84] | half-width / linear sigma (at E, median, max) | median offset (sigma) | table |",
                  "|---|---|---:|---:|---:|---|---|---:|---|"]
            for r in ba["grids"]:
                L.append(f"| {r['label']} | {r['quantity']} | {r['e0']:.4g} | {r['best0']:.5g} | {r['sigma_lin0']:.3g} ({100*r['rel_lin0']:.2f} %) | "
                         f"{r['median0']:.5g} [{r['p16_0']:.5g}, {r['p84_0']:.5g}] ({100*r['rel_sampled0']:.2f} %) | {r['ratio0']:.2f}, {r['ratio_median']:.2f}, {r['ratio_max']:.2f} | "
                         f"{r['offset0']:+.2f} | `uq/{r['table']}` |")
            L += ["", f"Birge factor sqrt(chi2/nu) = {np.sqrt(su.get('chi2nu', 1.0)):.3f} (the dotted line of the figures; NOT applied to any number above -- adopting it is the evaluator's call).",
                  f"{ba.get('draws')} draws on the grids; figures `uq/uq_band_<key>.png`."]
        else:
            L += [f"- none: {ba.get('note', 'BANDS did not run')}"]
        L += ["", "## Reading it", "",
              "- A half-width / linear-sigma ratio near 1 and a small median offset say the linear band is adequate there; a ratio well above 1 or an offset "
              "of a sigma says the posterior is skewed or wide along a direction the Jacobian misses (a saturating width, a sign-ambiguous amplitude).",
              "- R-hat above the gate with a small ESS on one parameter names the slow direction (`uq/gates_<tag>.json`, `rhat` / `ess` per parameter).",
              "- Everything here is conditional on the model and the spec's data decisions; it says nothing about either."]
        path = os.path.join(self.dir, "UQ.md")
        with open(path, "w") as fh:
            fh.write("\n".join(L) + "\n")
        self.mark("REPORT", path=path)
        return path

    def run(self, stop_after=None) -> dict:
        self.s_export()
        if stop_after == "EXPORT":
            return self.state
        self.s_setup()
        if stop_after == "SETUP":
            return self.state
        while True:
            self.s_sample()
            ok = self.s_gates()
            if ok is None:
                continue
            break
        if stop_after in ("SAMPLE", "GATES"):
            return self.state
        self.s_bands()
        self.s_report()
        return self.state


def run(campaign=None, directory=None, spec_uq=None, log=print, azr=None, sav=None, flags=None, nprocs=None, threads=None, stop_after=None, reset=False):
    cfg = config(spec_uq)
    d = directory or campaign.dir
    if reset and os.path.exists(os.path.join(d, "uq", "uq_state.json")):
        os.replace(os.path.join(d, "uq", "uq_state.json"), os.path.join(d, "uq", "uq_state.json." + time.strftime("%Y%m%d%H%M%S")))
    u = UQ(d, cfg, log=log, azr=azr, sav=sav, flags=flags, campaign=campaign, nprocs=nprocs, threads=threads)
    return u.run(stop_after=stop_after)


def main(argv=None):
    """``python3 -m rmfit.uq <file.azr> <param.sav> --out <dir> [--flags JSON] [--uq JSON] [--nprocs N] [--threads T] [--stop-after STAGE]``
    for a bare fit (no campaign): the same stage on an archived .azr + .sav pair."""
    import argparse
    ap = argparse.ArgumentParser(prog="rmfit.uq", description=main.__doc__)
    ap.add_argument("azr"); ap.add_argument("sav", nargs="?")
    ap.add_argument("--out", required=True, help="directory for uq/ and UQ.md")
    ap.add_argument("--flags", default="{}", help='JSON, e.g. {"use_brune": true, "ignore_externals": true, "use_long_wavelength": true}')
    ap.add_argument("--uq", default="{}", help="JSON for the uq section (chains, warmup, draws, bands, ...)")
    ap.add_argument("--nprocs", type=int); ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--stop-after", choices=STAGES); ap.add_argument("--reset", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    st = run(directory=a.out, spec_uq=json.loads(a.uq), azr=os.path.abspath(a.azr), sav=os.path.abspath(a.sav) if a.sav else None,
             flags=json.loads(a.flags), nprocs=a.nprocs, threads=a.threads, stop_after=a.stop_after, reset=a.reset)
    g = st["stages"].get("GATES", {})
    print("UQ_STATUS:", "PASS" if g.get("passed") else ("FAIL" if g else "INCOMPLETE"))
    return 0 if g.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
