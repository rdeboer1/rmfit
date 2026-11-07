"""``PYTHONPATH=~/R-matrix python3 -m rmfit.cli <campaign_dir> <command> [options]``

Commands (all idempotent and resumable from the ledger):

  init --base <azr> [--sav <sav>] [--nshards N] [--flags JSON] [--policy JSON] [--search JSON] [--objective JSON] [--cov-reference NPZ]   register the base model, verify the baseline (a relvector covariance's model is fixed at the seed's, cov_reference.npz), write run_crc_rmfit
  status [--json]                                               STATUS.md / a compact JSON summary
  polish [--nfev N] [--shifts-free] [--refreeze-every N]        warm-start continuation of the incumbent
  round [--jpi 5/2+ 3/2- ...] [--rounds N] [--top-k K]          sign round(s); touch <dir>/STOP to end the loop after the current round
  crossover --donor CID [--donor-dir DIR]                       basin crossover: the donor's sign pattern per channel/group/all, all polished
  levelscan [--ex E ...] [--top K] [--gamma keV] [--refit N]    residual-driven level search: template screen of every J^pi at the residual peaks
  relocate --level 9/2+#1 --ex 8.4654 [--window keV]           move an existing level and re-polish with its energy confined near --ex
  verify <cid>                                                  re-score a ledger candidate on a fresh single session
  export [--path file.azr]                                      bake the incumbent for the GUI
  log "text"                                                    append a note to the readme
  engine                                                        the campaign's pinned engine vs the one this process imports (2026-11-07)
  spec check|render|derive [--spec spec.json]                   fit specification vs the .azr / campaign.json; SPEC.md; derived init config
  audit [--azr file] [--no-target-energies]                     pre-flight checks of the model and data -> AUDIT.md (no engine session)
  decisions                                                     pending entries of DECISIONS.md
  decide <id> "<choice>" [--by who] [--note ...]                answer one

Engine pin (2026-11-07): ``init`` records the imported engine (AZURE2_ROOT, _azure2 .so md5, commit) in
campaign.json; every evaluating command refuses to run on another engine unless RMFIT_ALLOW_ENGINE_CHANGE=1.
status/report/log/engine only warn.
"""
READ_ONLY_CMDS = {"status", "report", "log", "engine", "spec", "audit", "decisions", "decide"}

import argparse
import json
import os
import sys


def _json_arg(text):
    """A JSON option value, or ``@path`` to read it from a file (2026-09-29: csh brace-expands a
    JSON literal passed through a shell variable -- "Missing '}'." -- so long policies go in a file)."""
    if isinstance(text, str) and text.startswith("@"):
        with open(text[1:]) as fh:
            return json.load(fh)
    return json.loads(text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rmfit")
    ap.add_argument("campaign")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--base", required=True)
    p.add_argument("--sav")
    p.add_argument("--nshards", type=int, default=24)
    p.add_argument("--note", default="")
    p.add_argument("--policy", default="{}", help="JSON for BoundsPolicy fields")
    p.add_argument("--search", default="{}", help="JSON for SearchConfig fields")
    p.add_argument("--flags", default=None, help="JSON engine flags (default: the archive flags; CLI-only flags vary per reaction)")
    p.add_argument("--objective", default="{}", help='JSON ObjectiveSpec, e.g. {"dataset_weight": "reduced", "loss": "sivia"}; @file reads it from a file (also --policy/--search/--flags)')
    p.add_argument("--cov-reference", default=None,
                   help="relvector covariance: fix its model at this .npz (another campaign's cov_reference.npz) "
                        "instead of the seed's own (default; 2026-10-25)")
    p.add_argument("--spec", default=None, help="spec.json (rmfit/spec.py): flags/policy/search/objective/nshards derived from it "
                                                "unless given explicitly; copied into the campaign; HIGH disagreements with the .azr refuse init")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("polish")
    p.add_argument("--nfev", type=int, default=200)
    p.add_argument("--candidate", type=int, default=None, help="polish this ledger candidate instead of the best verified one (2026-10-05)")
    p.add_argument("--shifts-free", action="store_true")
    p.add_argument("--tighten", action="store_true", help="walk out-of-cap amplitudes into the theta^2 box in stages")
    p.add_argument("--refreeze-every", type=int, default=0,
                   help="relvector covariance WITHOUT a fixed reference only: re-freeze its model every <= N "
                        "evaluations (default 0 = never, since 2026-10-25: the iteration oscillated on 13C+a)")
    p = sub.add_parser("round")
    p.add_argument("--jpi", nargs="*")
    p.add_argument("--local-release", type=float, default=None,
                   help="MeV: screen + stage-1 polish free every level within +-this of the flipped one, all background "
                        "widths and the norms (2026-10-02); default: the campaign's search config (0 = J^pi group only)")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--top-k", type=int)
    p.add_argument("--note", default="")
    p = sub.add_parser("crossover")
    p.add_argument("--donor", type=int, required=True, help="donor candidate id")
    p.add_argument("--donor-dir", help="another campaign directory holding the donor (same base structure)")
    p.add_argument("--note", default="")
    p = sub.add_parser("levelscan")
    p.add_argument("--ex", type=float, nargs="*", help="candidate excitation energies (MeV); default: from residual runs")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--gamma", default="10", help="template total width (keV), or 'auto' = each cluster's own residual-run "
                                                 "width clamped into --gamma-bounds (2026-09-24)")
    p.add_argument("--gamma-bounds", default="10,1000", help="keV lo,hi clamp for --gamma auto")
    p.add_argument("--seg-match", default=None, help="regex on data-file names: only these segments' residuals make candidates (2026-09-24)")
    p.add_argument("--rank", default="chi2", choices=["chi2", "density"],
                   help="order residual clusters by chi2 (old) or chi2 per MeV of structure (2026-09-24)")
    p.add_argument("--ex-range", default=None, help="lo,hi MeV: drop residual candidates outside before the --top cut")
    p.add_argument("--scales", default="1", help="comma-separated multipliers of --gamma to try")
    p.add_argument("--jpi", nargs="*")
    p.add_argument("--gn-top", type=int, default=20)
    p.add_argument("--max-signs", type=int, default=32)
    p.add_argument("--refit", type=int, default=0, help="refit the best N candidates (run_level_add)")
    p.add_argument("--differential-window", type=float, default=250.0,
                   help="keV half-width: re-rank candidates on the DIFFERENTIAL segments near the candidate "
                        "energy (0 = rank on the total objective, the pre-redesign behaviour)")
    p.add_argument("--grid", default="5,20",
                   help="resonanceWidthMultiplier,pointsPerWidth for the SCREEN variant only; default 5,20 is "
                        "6.7x cheaper than the converged 20,50 for 0.03%%; 'none' keeps the model's setting")
    p.add_argument("--ex-offsets", default="-0.04,0,0.04", help="comma-separated energy offsets (MeV) tried around each candidate")
    p.add_argument("--stage-scales", default="1.2,5",
                   help="two-stage screen: every shape at these --gamma multipliers and offset 0 first; "
                        "'none' evaluates every shape at every scale and offset (16,668 patterns / 4 h on 13C+a)")
    p.add_argument("--refine-top", type=int, default=3, help="shapes per J^pi carried into the all-scales x all-offsets stage")
    p.add_argument("--merge-kev", type=float, default=60.0,
                   help="residual candidates closer than this to a stronger one are not screened separately (0 = screen all)")
    p.add_argument("--note", default="")
    p = sub.add_parser("relocate")
    p.add_argument("--level", required=True, help="level label, e.g. 9/2+#1")
    p.add_argument("--ex", type=float, required=True, help="new excitation energy (MeV)")
    p.add_argument("--window", type=float, default=5.0, help="half window (keV) kept around --ex")
    p.add_argument("--nfev", type=int, default=100)
    p.add_argument("--note", default="")
    p = sub.add_parser("verify")
    p.add_argument("cid", type=int)
    p = sub.add_parser("export")
    p.add_argument("--path")
    p = sub.add_parser("report")
    p = sub.add_parser("structure")
    p.add_argument("what", choices=["add", "remove", "dataset-off"])
    p.add_argument("--candidate", type=int, help="index into candidates.json")
    p.add_argument("--file", help="data-file substring for dataset-off")
    p.add_argument("--jpi", nargs="*", help="J^pi groups to scan (default: the candidate's, or all)")
    p.add_argument("--nfev", type=int, default=150)
    p.add_argument("--local-release", type=float, default=0.0,
                   help="add: MeV half-width of a local-release polish (all J^pi near the candidate + background + norms) "
                        "between the pinned and the global stage; the control gets the same (2026-10-02)")
    p.add_argument("--local-nfev", type=int, default=80)
    p.add_argument("--pinned-nfev", type=int, default=60)
    p.add_argument("--top", type=int, default=3,
                   help="remove: how many of the cheapest-to-remove levels get an honest refit")
    p = sub.add_parser("engine", help="show the pinned engine and the imported one")
    p = sub.add_parser("spec", help="fit specification: check / render / derive")
    p.add_argument("what", choices=["check", "render", "derive"])
    p.add_argument("--spec", default=None, help="path (default <campaign>/spec.json)")
    p.add_argument("--azr", default=None, help="model to check (default the campaign's base model)")
    p = sub.add_parser("audit", help="pre-flight checks -> AUDIT.md")
    p.add_argument("--azr", default=None, help="model (default the campaign's base model)")
    p.add_argument("--no-target-energies", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("decisions", help="pending entries of DECISIONS.md")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("decide", help="answer a DECISIONS.md entry")
    p.add_argument("id")
    p.add_argument("choice")
    p.add_argument("--by", default="")
    p.add_argument("--note", default="")
    p = sub.add_parser("log")
    p.add_argument("text")
    p = sub.add_parser("perturb", help="recovery benchmark: a sibling campaign from a sign-perturbed incumbent")
    p.add_argument("--out", required=True)
    p.add_argument("--flips", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--jitter", type=float, default=0.3, help="relative width jitter (0 = signs only)")
    p.add_argument("--ekick", type=float, default=0.02, help="energy kick in MeV (0 = none)")
    p.add_argument("--polish-nfev", type=int, default=60)
    a = ap.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from rmfit.campaign import Campaign

    if a.cmd == "init":
        c = Campaign.init(a.campaign, a.base, sav=a.sav, nshards=a.nshards, note=a.note,
                          policy=_json_arg(a.policy), search=_json_arg(a.search),
                          flags=(_json_arg(a.flags) if a.flags else None), objective=_json_arg(a.objective),
                          cov_reference=a.cov_reference, spec=a.spec)
        print(open(os.path.join(c.dir, "STATUS.md")).read())
        print("job script:", c.write_job_script())
        return
    c = Campaign(a.campaign, enforce_engine=a.cmd not in READ_ONLY_CMDS)
    try:
        if a.cmd == "spec":
            from rmfit.spec import FitSpec, write_findings_md
            sp = a.spec or os.path.join(c.dir, "spec.json")
            fs = FitSpec.load(sp)
            if a.what == "render":
                out = os.path.join(c.dir, "SPEC.md")
                open(out, "w").write(fs.render_md())
                print("wrote", out)
            elif a.what == "derive":
                print(json.dumps(fs.derive_campaign_cfg(), indent=1))
            else:
                findings = fs.check(a.azr or c.base_azr, campaign_cfg=c.cfg)
                out = os.path.join(c.dir, "SPEC_CHECK.md")
                counts = write_findings_md(out, "Spec check (rmfit spec check)", findings,
                                           [f"spec `{sp}` vs model `{a.azr or c.base_azr}` and campaign.json", ""])
                for f in findings:
                    print(f.line())
                print("wrote", out, counts)
        elif a.cmd == "audit":
            from rmfit.audit import audit_model, write_audit
            azr = a.azr or c.base_azr
            fs = audit_model(azr, campaign_dir=c.dir, campaign_cfg=c.cfg, run_target_energies=not a.no_target_energies)
            if a.json:
                print(json.dumps([f.__dict__ for f in fs], indent=1))
            else:
                for f in sorted(fs, key=lambda f: {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}.get(f.severity, 9)):
                    print(f.line())
            counts = write_audit(fs, os.path.join(c.dir, "AUDIT.md"), azr)
            print("wrote", os.path.join(c.dir, "AUDIT.md"), counts)
            c.note(f"audit: {', '.join(f'{k} {v}' for k, v in counts.items())} (AUDIT.md)")
        elif a.cmd == "decisions":
            items = c.decisions.all() if a.all else c.decisions.pending()
            for d in items:
                print(f"{d.id} [{d['status']}] {d['when']} {d['slug']}: {d.get('question', '')}")
                if d.get("options"):
                    print(f"    options: {d['options']}   default: {d.get('default_if_unanswered', 'wait')}")
                if d.get("answer"):
                    print(f"    answer: {d['answer']} ({d.get('answered_by', '')}, {d.get('answered', '')})")
            if not items:
                print("no pending decisions")
        elif a.cmd == "decide":
            d = c.decisions.answer(a.id, a.choice, by=a.by, note=a.note)
            c.note(f"decision {d.id} ({d['slug']}): {a.choice}" + (f" -- {a.by}" if a.by else "") + (f"; {a.note}" if a.note else ""))
            print(f"{d.id} answered: {a.choice}")
        elif a.cmd == "engine":
            from rmfit import enginepin
            rec = c.cfg.get("engine")
            print("pinned:  ", enginepin.short(rec) if rec else "(none: campaign made before 2026-11-07)")
            print("imported:", enginepin.short(c.engine))
            print("match" if (not rec or rec.get("so_md5") == c.engine.get("so_md5")) else "MISMATCH")
        elif a.cmd == "status":
            st = c.ledger.status()
            if a.json:
                print(json.dumps(st, default=str))
            else:
                c.ledger.write_status_md()
                print(open(os.path.join(c.dir, "STATUS.md")).read())
        elif a.cmd == "polish":
            c.run_polish(max_nfev=a.nfev, shifts_free=(True if a.shifts_free else None), tighten=a.tighten, cid=a.candidate,
                         refreeze_every=a.refreeze_every)
        elif a.cmd == "round":
            if a.top_k:
                c.search.top_k = a.top_k
            if a.local_release is not None:
                c.search.local_release = a.local_release
            stop_file = os.path.join(c.dir, "STOP")
            if os.path.exists(stop_file):
                os.remove(stop_file)
            for i in range(a.rounds):
                st = c.run_sign_round(jpi=a.jpi, note=a.note)
                if st.get("accepted", 0) == 0 and i > 0:
                    c.log("no accepted flips: stopping the round loop")
                    break
                if os.path.exists(stop_file):
                    c.log("STOP file found: stopping the round loop after this round")
                    os.remove(stop_file)
                    break
        elif a.cmd == "crossover":
            c.run_crossover(a.donor, donor_dir=a.donor_dir, note=a.note)
        elif a.cmd == "levelscan":
            grid = None if str(a.grid).lower() == "none" else [float(v) for v in a.grid.split(",")]
            gamma_kev = None if str(a.gamma).lower() == "auto" else float(a.gamma)
            c.run_levelscan(ex=a.ex, top=a.top, gamma_kev=gamma_kev, scales=[float(v) for v in a.scales.split(",")],
                            gamma_bounds_kev=[float(v) for v in a.gamma_bounds.split(",")],
                            seg_match=a.seg_match, rank=a.rank,
                            ex_range=(None if not a.ex_range else [float(v) for v in a.ex_range.split(",")]),
                            jpis=a.jpi, gn_top=a.gn_top, max_signs=a.max_signs, refit=a.refit,
                            ex_offsets=[float(v) for v in a.ex_offsets.split(",")],
                            differential_window_kev=a.differential_window, grid=grid,
                            stage_scales=(None if str(a.stage_scales).lower() == "none"
                                          else [float(v) for v in a.stage_scales.split(",")]),
                            refine_top=a.refine_top, merge_kev=a.merge_kev, note=a.note)
        elif a.cmd == "relocate":
            c.run_relocate(a.level, a.ex, half_window_kev=a.window, max_nfev=a.nfev, note=a.note)
        elif a.cmd == "verify":
            x, keys = c.ledger.load(a.cid)
            cid, sc = c.verify_candidate(x, keys, move=dict(kind="reverify", of=a.cid), parent=a.cid)
            print(f"candidate {a.cid} re-verified as {cid}: {sc.objective:.3f}")
        elif a.cmd == "export":
            c.export(path=a.path)
        elif a.cmd == "report":
            print(open(c.report()).read())
        elif a.cmd == "structure" and a.what == "add":
            from rmfit.structure import LevelCandidate
            bank = json.load(open(os.path.join(c.dir, "candidates.json")))["candidates"]
            spec = dict(bank[a.candidate])
            cand = LevelCandidate(energy=spec["energy"], jpi=spec.get("jpi"), channels=spec.get("channels", []),
                                  source=spec.get("source", ""), note=spec.get("note", ""),
                                  energy_fixed=spec.get("energy_fixed", True))
            st = c.run_level_add(cand, jpis=a.jpi, global_nfev=a.nfev, pinned_nfev=a.pinned_nfev,
                                 local_release=a.local_release, local_nfev=a.local_nfev)
            print(json.dumps(st, default=str, indent=1))
        elif a.cmd == "structure" and a.what == "remove":
            st = c.run_remove(top=a.top, nfev=a.nfev)
            print(json.dumps(st, default=str, indent=1))
        elif a.cmd == "structure" and a.what == "dataset-off":
            st = c.run_dataset_off(a.file, nfev=a.nfev)
            print(json.dumps(st, default=str, indent=1))
        elif a.cmd == "log":
            c.note(a.text)
        elif a.cmd == "perturb":
            st = c.perturb(a.out, n_flips=a.flips, seed=a.seed, jitter=a.jitter, e_kick=a.ekick,
                           polish_nfev=a.polish_nfev)
            print(json.dumps(st, default=str, indent=1))
    finally:
        c.close()
        c.ledger.write_status_md()


if __name__ == "__main__":
    main()
