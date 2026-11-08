#!/usr/bin/env python3
"""rmfit drive end to end on the 13N model (queue, ~30-60 min, 3 shards): build phase (audit, reproduce against a copied
chiSquared.out, spec, anchor, seeds, pairs, candidates, init) then the loop with tiny budgets, legs repeated until DONE /
WAITING / STOP; pending wait decisions are answered by the test ('accept' / 'continue') so the whole machine is exercised.
Run:  python3 rmfit/tests/test_drive_13n.py   (tests/_queue_drive/run_crc_drive_test submits it)"""
import json, os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
os.environ.setdefault("OMP_NUM_THREADS", "1")
from rmfit import AZURE2_ROOT
from rmfit import drive as dv
from pyazr import AzrModel

FAILS = []


def check(name, ok, info=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  -- {info}" if info and not ok else ""))
    sys.stdout.flush()
    if not ok:
        FAILS.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="rmfit_drive13n_")
    src = os.path.join(AZURE2_ROOT, "tests", "13N")
    shutil.copytree(os.path.join(src, "data"), os.path.join(tmp, "data"))
    os.makedirs(os.path.join(tmp, "output"))
    if os.path.exists(os.path.join(src, "output", "chiSquared.out")):
        shutil.copy2(os.path.join(src, "output", "chiSquared.out"), os.path.join(tmp, "output", "chiSquared.out"))
    mdl = AzrModel.from_file(os.path.join(src, "13N.azr"))
    mdl.set_segment_norm("meyer_84", vary=True, sys_error=5.0)
    mdl.set_output_dir(os.path.join(tmp, "output"))
    base = mdl.write(os.path.join(tmp, "13N.azr"))
    spec = {"reaction": "12C+p", "compound_nucleus": "13N", "campaign": "drive-13n", "owners": ["test"], "parametrization": "brune",
            "engine": {"flags": {"use_long_wavelength": True, "ignore_externals": False}}, "nshards": 3,
            "model": {"fit_window": {"Ex_MeV": [1.9, 4.5]}},
            "bounds": {"bg_energy": 15.0, "e_window": 0.5},
            "search": {"top_k": 3, "pairs_per_group": 2, "stage1_nfev": 20, "stage2_nfev": 30, "union_nfev": 30},
            "data_sets": [{"file": "meyer_84", "role": "free", "norm": {"nominal": 1.0, "fixed": False, "prior_sigma": 0.05}}],
            "budget": {"polish_nfev": 30, "polish_rounds_max": 2, "sign_rounds_max": 2, "level_tests_max": 1, "level_nfev": 40,
                       "pinned_nfev": 25, "dataset_off_max": 1, "dataset_off_nfev": 30, "cycles_max": 1, "grid_check": False, "figures": 1},
            "stop_rules": {"polish_gain_rel_min": 5e-4, "sign_rounds_without_accept": 2, "level_adds_marginal_in_a_row": 2},
            "pre_authorized": {"adopt_level": False, "flip_adopt": True, "shifts_free": False},
            "standing_decisions": [{"date": "2026-11-08", "who": "test", "text": "fixture"}]}
    json.dump(spec, open(os.path.join(tmp, "spec.json"), "w"), indent=1)
    json.dump(dict(candidates=[dict(energy=3.0, jpi=None, energy_fixed=True, channels=[dict(pair=1, L=0, S=0.5, gamma=20000.0)],
                                    source="test", hypothesis="fixture: a level at 3.0 MeV, J^pi scanned")]),
              open(os.path.join(tmp, "candidates.json"), "w"), indent=1)
    t0 = time.time()
    answers = {"reproduce-mismatch": "accept", "audit-high": "accepted", "spec-high": "accepted", "review-high": "continue",
               "adopt-level": "reject"}
    status, legs = None, 0
    while legs < 12:
        legs += 1
        d = dv.Driver(tmp, base=base, local=True)
        status = d.run()
        print(f"   leg {legs}: {status} at {d.state['state']} ({(time.time()-t0)/60:.1f} min)")
        if status in ("DONE", "STOP", "ERROR"):
            break
        if status == "WAITING":
            pend = d.decisions.pending()
            for p in pend:
                key = next((k for k in answers if p["slug"].startswith(k)), None)
                if key is None:
                    print("   unexpected decision", p.id, p["slug"], p.get("question"))
                    break
                d.decisions.answer(p.id, answers[key], by="test")
                print(f"   answered {p.id} {p['slug']}: {answers[key]}")
            else:
                continue
            break
    st = json.load(open(os.path.join(tmp, "drive_state.json")))
    done = [h["state"] for h in st["history"]]
    print("   states run:", done)
    print("   message:", st.get("message"))
    check("the drive ended DONE", status == "DONE", f"{status} at {st['state']}: {st.get('message')}")
    check("build phase reached INIT (campaign.json)", os.path.exists(os.path.join(tmp, "campaign.json")))
    check("working copy and job script written", os.path.exists(os.path.join(tmp, "13N_drive.azr")) and os.path.exists(os.path.join(tmp, "run_crc_drive")))
    for s in ("TIGHTEN", "SIGN", "STRUCTURE_ADD", "DATASET_OFF", "REVIEW", "EXPORT", "CYCLE"):
        check(f"state {s} ran", s in done)
    check("REVIEW.md and export exist", os.path.exists(os.path.join(tmp, "REVIEW.md")) and any(f.endswith(".sav") for f in os.listdir(tmp)))
    check("DRIVE.md written", os.path.exists(os.path.join(tmp, "DRIVE.md")))
    rep = st.get("reproduce")
    check("REPRODUCE compared against chiSquared.out", rep is not None and rep.get("nref", 0) > 0, str(rep))
    print(f"   total {(time.time()-t0)/60:.1f} min in {legs} legs; dir {tmp}")
    if FAILS:
        print(f"FAILED {len(FAILS)}: {', '.join(FAILS)}")
        sys.exit(1)
    shutil.rmtree(tmp, ignore_errors=True)
    print("all drive 13N checks passed")


if __name__ == "__main__":
    main()
