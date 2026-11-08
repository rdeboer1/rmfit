#!/usr/bin/env python3
"""rmfit drive (2026-11-08), engine-free: the state machine on a 13N copy -- build states that need no engine (PIN_CHECK,
AUDIT, SPEC_CHECK, SCALE_ANCHOR, PAIR_COMPLETENESS, CANDIDATES), login-node refusal of an engine state, STOP_DRIVE, decisions
-> WAITING and their consumption, --state jumps, persistence, DRIVE.md; then the loop phase on a STUB campaign (canned
run_* results) for the counters and stop rules: TIGHTEN convergence, SIGN two-rounds-without-accept, STRUCTURE_ADD hypothesis
requirement / marginal-in-a-row / accept -> SIGN_POST, DATASET_OFF decision with default keep, REVIEW HIGH -> WAITING,
CYCLE -> another pass -> DONE.  Seconds; no network needed (ENSDF failures are tolerated).
Run:  python3 rmfit/tests/test_drive_dry.py"""
import json, os, shutil, sys, tempfile, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
os.environ.pop("JOB_ID", None)
from rmfit import AZURE2_ROOT
from rmfit import drive as dv
from rmfit.spec import Finding
from pyazr import AzrModel

FAILS = []


def check(name, ok, info=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  -- {info}" if info and not ok else ""))
    sys.stdout.flush()
    if not ok:
        FAILS.append(name)


def make_dir(tmp):
    shutil.copytree(os.path.join(AZURE2_ROOT, "tests", "13N", "data"), os.path.join(tmp, "data"))
    os.makedirs(os.path.join(tmp, "output"))
    mdl = AzrModel.from_file(os.path.join(AZURE2_ROOT, "tests", "13N", "13N.azr"))
    mdl.set_segment_norm("meyer_84", vary=True, sys_error=5.0)
    mdl.set_output_dir(os.path.join(tmp, "output"))
    base = mdl.write(os.path.join(tmp, "13N.azr"))
    spec = {"reaction": "12C+p", "compound_nucleus": "13N", "campaign": "drive-test", "owners": ["test"], "parametrization": "brune",
            "engine": {"flags": {"use_long_wavelength": True, "ignore_externals": False}}, "nshards": 3,
            "model": {"fit_window": {"Ex_MeV": [1.9, 4.5]}},
            "data_sets": [{"file": "meyer_84", "role": "anchor", "norm": {"nominal": 1.0, "fixed": True}}],
            "budget": {"polish_nfev": 20, "polish_rounds_max": 3, "sign_rounds_max": 3, "level_tests_max": 3, "dataset_off_max": 1,
                       "cycles_max": 2, "grid_check": False, "figures": 0},
            "stop_rules": {"polish_gain_rel_min": 1e-3, "sign_rounds_without_accept": 2, "level_adds_marginal_in_a_row": 2,
                           "cycle_gain_rel_min": 1e-3},
            "pre_authorized": {"adopt_level": True, "flip_adopt": True, "shifts_free": False},
            "standing_decisions": [{"date": "2026-11-08", "who": "test", "text": "fixture"}]}
    json.dump(spec, open(os.path.join(tmp, "spec.json"), "w"), indent=1)
    return base


class StubCampaign:
    """Enough of Campaign for the loop phase: an objective that falls by a scripted amount per call."""

    def __init__(self, d, decisions):
        self.dir = d
        self.cfg = {"engine": {}, "base_azr": "13N.azr"}
        self.base_azr = os.path.join(d, "13N.azr")
        self.decisions = decisions
        self.obj = 1000.0
        self.calls = []
        self.polish_gains = [50.0, 0.3, 0.0]      # TIGHTEN: converge at round 2 (gain 0.03 % < 0.1 %)
        self.sign_accepts = [1, 0, 0]             # SIGN: accepted, none, none -> stop after round 3
        self.pop_gains = [8.0, 0.0]               # POPULATION: cycle 1 gains 0.8 % (new basin), cycle 2 nothing -> exhausted
        self.add_outcomes = ["marginal", "accept", "worse", "worse"]
        self.dataset_extra = 12.0
        self.review_high = True
        self.ledger = types.SimpleNamespace(write_status_md=lambda: None)

    def incumbent(self):
        return 7, None, self.obj, None

    def close(self):
        pass

    def note(self, text):
        with open(os.path.join(self.dir, "readme"), "a") as fh:
            fh.write(f"\nstub: {text}\n")

    def adopt_structure(self, sid, note=""):
        self.calls.append(("adopt", sid))

    def run_polish(self, max_nfev=200, shifts_free=None, note="", tighten=False, **kw):
        g = self.polish_gains.pop(0) if self.polish_gains else 0.0
        self.obj -= g
        self.calls.append(("polish", tighten, shifts_free))
        return types.SimpleNamespace(status="converged", nfev=max_nfev, objective=self.obj)

    def run_population(self, restarts=4, nfev=600, passes=2, note="", **kw):
        gain = self.pop_gains.pop(0) if self.pop_gains else 0.0
        before = self.obj
        self.obj -= gain
        self.calls.append(("population", restarts, nfev))
        return dict(before=before, after=self.obj, verified=self.obj, restarts=restarts, polishes=restarts + 3,
                    crossover_moves=5, best="restart 1" if gain else "control", improved=gain > 0)

    def run_sign_round(self, jpi=None, note=""):
        acc = self.sign_accepts.pop(0) if self.sign_accepts else 0
        before = self.obj
        self.obj -= 10.0 * acc
        self.calls.append(("sign", acc))
        return dict(proposed=8, improving_screen=2, accepted=acc, before=before, after=self.obj, verified=self.obj)

    def run_level_add(self, cand, jpis=None, global_nfev=150, pinned_nfev=60, note=""):
        out = self.add_outcomes.pop(0) if self.add_outcomes else "worse"
        self.calls.append(("add", cand.energy, out, cand.note))
        if out == "accept":
            self.obj -= 30.0
        return dict(outcome=out, jpi=cand.jpi or "1/2+", delta=-30.0 if out == "accept" else -1.0)

    def dataset_table(self, cid, stage="verified"):
        return [dict(name="bad_set", chi2=900.0, n=10, per_pt=90.0), dict(name="ok_a", chi2=50.0, n=50, per_pt=1.0),
                dict(name="ok_b", chi2=60.0, n=50, per_pt=1.2)]

    def run_dataset_off(self, name, nfev=100, note=""):
        self.calls.append(("off", name))
        return dict(file=name, extra_recovery=50.0, extra_pct=self.dataset_extra)

    def export(self, path=None, note=""):
        self.calls.append(("export",))
        return os.path.join(self.dir, "13N.azr"), os.path.join(self.dir, "13N.sav"), types.SimpleNamespace(objective=self.obj)

    def report(self):
        return os.path.join(self.dir, "REPORT.md")


def stub_review(c, grid_check=False, figures=0, top=20):
    fs = [Finding("HIGH", "broad-level-averages-peaks", "test flag")] if c.review_high else []
    return dict(path=os.path.join(c.dir, "REVIEW.md"), counts={"HIGH": len(fs)}, findings=fs, review=None)


def main():
    tmp = tempfile.mkdtemp(prefix="rmfit_drive_dry_")
    base = make_dir(tmp)
    # -- 1. build states without the engine -------------------------------------------------------------
    d = dv.Driver(tmp, base=base)
    check("fresh state starts at PIN_CHECK", d.state["state"] == "PIN_CHECK")
    for st in ("PIN_CHECK", "AUDIT", "SPEC_CHECK", "SCALE_ANCHOR", "PAIR_COMPLETENESS", "CANDIDATES"):
        d.state["state"] = st
        d.step(st)
        print("     ", st, "->", d.state["history"][-1]["result"], d.state["history"][-1]["note"][:100])
    check("run_crc_drive written by PIN_CHECK", os.path.exists(os.path.join(tmp, "run_crc_drive")))
    check("AUDIT.md written", os.path.exists(os.path.join(tmp, "AUDIT.md")))
    audit_rec = [h for h in d.state["history"] if h["state"] == "AUDIT"][-1]
    check("AUDIT advanced or queued a decision", audit_rec["result"] in ("next", "stay"), audit_rec["note"])
    check("SPEC_CHECK.md written", os.path.exists(os.path.join(tmp, "SPEC_CHECK.md")))
    drv = os.path.join(tmp, "13N_drive.azr")
    check("SCALE_ANCHOR wrote the working copy", os.path.exists(drv) and d.state.get("model") == drv, str(d.state.get("model")))
    if os.path.exists(drv):
        from pyazr.datasets import SegmentSet
        segs = SegmentSet.from_file(drv)
        anchored = [s for s in segs if "meyer_84" in s.data_file]
        check("anchor set's norm fixed in the working copy", anchored and all(not s.vary_norm for s in anchored))
        check("working copy output dir inside the campaign", f"{tmp}/output" in open(drv).read())
    check("candidates.json exists after CANDIDATES", os.path.exists(os.path.join(tmp, "candidates.json")))
    bank = json.load(open(os.path.join(tmp, "candidates.json"))).get("candidates", [])
    check("every ENSDF candidate carries a hypothesis", all(c.get("hypothesis") for c in bank), str(bank[:1]))
    check("DRIVE.md written", os.path.exists(os.path.join(tmp, "DRIVE.md")))
    # persistence
    d2 = dv.Driver(tmp)
    check("state persisted (model, history)", d2.state.get("model") == drv and len(d2.state["history"]) >= 6)
    # -- 2. engine state refuses the login node; STOP_DRIVE; dry-run ----------------------------------------
    d2.state["state"] = "SEED_CHANNELS"
    d2.save()
    status = d2.run()
    check("engine state refused outside a job (STOP)", status == "STOP" and "login" in d2.state.get("message", ""), status + " " + d2.state.get("message", ""))
    d3 = dv.Driver(tmp)
    d3.state["state"] = "PIN_CHECK"
    open(os.path.join(tmp, dv.STOP_FILE), "w").close()
    status = d3.run()
    check("STOP_DRIVE file -> STOP and removed", status == "STOP" and not os.path.exists(os.path.join(tmp, dv.STOP_FILE)))
    lines = []
    d4 = dv.Driver(tmp, log=lines.append)
    d4.run(dry_run=True)
    check("dry-run prints the plan without running", any("TIGHTEN" in l for l in lines) and len(d4.state["history"]) == len(d3.state["history"]))
    # -- 3. decisions: a wait decision blocks, its answer is consumed once --------------------------------------
    d5 = dv.Driver(tmp)
    ans = d5.ask("unit-q", "is this blocking?", ("yes", "no"), default="wait")
    check("ask() with default wait returns None and queues", ans is None and any(x.startswith("D-") for x in d5.waiting_on()))
    d5.state["state"] = "PIN_CHECK"
    status = d5.run()
    check("pending wait decision -> WAITING", status == "WAITING", status)
    did = d5.decisions.pending()[0].id
    d5.decisions.answer(did, "yes", by="test")
    check("answered decision read back once", d5.ask("unit-q", "again?", ("yes", "no")) == "yes")
    check("...and not twice (a new one is queued instead)", d5.ask("unit-q", "again?", ("yes", "no")) is None)
    d5.decisions.answer(d5.decisions.pending()[0].id, "no", by="test")
    d5.ask("unit-q", "x", ("yes", "no"))      # consume it
    ans = d5.ask("nonblocking", "default applies?", ("keep", "drop"), default="keep")
    check("default other than wait is applied and returned", ans == "keep" and not d5.waiting_on())
    # -- 4. loop phase on the stub campaign ----------------------------------------------------------------------
    d6 = dv.Driver(tmp, local=True)
    stub = StubCampaign(tmp, d6.decisions)
    d6._campaign = stub
    dv_review = dv.__dict__.get("review_campaign")
    import rmfit.review as rvmod
    real_review = rvmod.review_campaign
    rvmod.review_campaign = stub_review
    try:
        json.dump(dict(candidates=[dict(energy=3.0, jpi="1/2+", hypothesis="test level A"),
                                   dict(energy=3.2, jpi="3/2-"),                       # no hypothesis: skipped
                                   dict(energy=3.4, jpi="3/2-", hypothesis="test level B"),
                                   dict(energy=3.6, jpi="1/2+", hypothesis="test level C", width_kev=120.0),   # broad: tested first
                                   dict(energy=3.8, jpi="1/2+", hypothesis="test level D")]),
                  open(os.path.join(tmp, "candidates.json"), "w"))
        d6.state["state"] = "TIGHTEN"
        d6.save()                                  # no cycle_start_objective: TIGHTEN must record it (pre-existing campaign)
        status = d6.run()
        hist = [(h["state"], h["result"]) for h in d6.state["history"] if h["cycle"] >= 1][-40:]
        print("      loop history:", [f"{s}:{r}" for s, r in hist])
        polishes = [c for c in stub.calls if c[0] == "polish"]
        check("TIGHTEN: first round tightens, stops when the gain falls below the rule", len(polishes) >= 2 and polishes[0][1] is True
              and sum(1 for c in stub.calls[:3] if c[0] == "polish") == 2, str(polishes))
        signs = [c for c in stub.calls if c[0] == "sign"]
        check("SIGN: three rounds (accept, none, none) then converged", len(signs) >= 3, str(signs))
        check("SHIFTS_FREE skipped (pre_authorized false)", not any(c[0] == "polish" and c[2] is True for c in stub.calls))
        pops = [c for c in stub.calls if c[0] == "population"]
        check("POPULATION ran once in cycle 1 with the default budget (4 restarts, polish_nfev)",
              pops[:1] == [("population", 4, int(d6.budget["polish_nfev"]))], str(pops))
        pop_rec = [h for h in d6.state["history"] if h["state"] == "POPULATION"]
        check("POPULATION round 1 adopted the new basin (0.8 % gain)", pop_rec and "new basin" in pop_rec[0]["note"], str([h["note"] for h in pop_rec]))
        adds = [c for c in stub.calls if c[0] == "add"]
        check("STRUCTURE_ADD skipped the candidate without a hypothesis", all(abs(c[1] - 3.2) > 1e-6 for c in adds), str(adds))
        check("STRUCTURE_ADD stopped after two marginal/worse in a row (budget 3 tests)", len(adds) == 3, str(adds))
        check("STRUCTURE_ADD tested the broad candidate first (width_kev), then bank order", [c[1] for c in adds] == [3.6, 3.0, 3.4], str(adds))
        check("SIGN_POST ran after the accepted level", [s for s, r in hist].count("SIGN_POST") >= 2 or any(
            s == "SIGN_POST" and r == "stay" for s, r in hist), str(hist))
        offs = [c for c in stub.calls if c[0] == "off"]
        check("DATASET_OFF tested the worst set only", offs == [("off", "bad_set")], str(offs))
        dd = [x for x in d6.decisions.all() if x["slug"].startswith("dataset-off")]
        check("dataset-off decision queued with default keep (answered, non-blocking)", dd and dd[0]["status"] == "answered" and dd[0]["answer"] == "keep")
        check("REVIEW HIGH -> WAITING", status == "WAITING" and d6.state["state"] == "REVIEW", f"{status} at {d6.state['state']}")
        rd = [x for x in d6.decisions.pending() if x["slug"] == "review-high"]
        check("review-high decision pending", bool(rd))
        d6.decisions.answer(rd[0].id, "continue", by="test")
        stub.review_high = False
        d7 = dv.Driver(tmp, local=True)
        d7._campaign = stub
        status = d7.run()
        hist2 = [(h["state"], h["result"]) for h in d7.state["history"]]
        print("      after answer:", status, [f"{s}:{r}" for s, r in hist2[-12:]])
        check("EXPORT ran", any(c[0] == "export" for c in stub.calls))
        pops = [c for c in stub.calls if c[0] == "population"]
        pop_rec = [h for h in d7.state["history"] if h["state"] == "POPULATION"]
        check("POPULATION ran once per cycle (2 cycles)", len(pops) == 2, str(pops))
        check("POPULATION round 2 (no gain) -> exhausted", len(pop_rec) >= 2 and "no further population rounds" in pop_rec[1]["note"],
              str([h["note"][-80:] for h in pop_rec]))
        check("cycle start objective recorded at the first TIGHTEN of a pre-existing campaign", d7.state.get("baseline_objective") == 1000.0,
              str(d7.state.get("baseline_objective")))
        check("CYCLE -> second pass (gain large) then DONE", status == "DONE" and d7.state["cycle"] == 2 and d7.state["state"] == "DONE",
              f"{status} cycle {d7.state['cycle']} state {d7.state['state']}")
        check("DRIVE.md shows DONE", "**DONE**" in open(os.path.join(tmp, "DRIVE.md")).read())
    finally:
        rvmod.review_campaign = real_review
    shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"FAILED {len(FAILS)}: {', '.join(FAILS)}")
        sys.exit(1)
    print("all drive dry checks passed")


if __name__ == "__main__":
    main()
