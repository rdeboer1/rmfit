"""``rmfit drive``: the closed loop (R-matrix/rmfit/DESIGN.md Phase 2.1; retrospective finding 2.2 "nobody closes the loop").

A campaign is driven by a resumable state machine whose every state is one checkpoint in ``drive_state.json``::

    build phase (needs --base <azr> [--sav] and <dir>/spec.json; no campaign.json yet)
      PIN_CHECK -> AUDIT -> REPRODUCE -> SPEC_CHECK -> SCALE_ANCHOR -> SEED_CHANNELS -> PAIR_COMPLETENESS -> LADDER
      -> CANDIDATES -> INIT
    loop phase (campaign.json exists)
      TIGHTEN -> SIGN -> SHIFTS_FREE -> STRUCTURE_ADD -> SIGN_POST -> DATASET_OFF -> REVIEW -> EXPORT -> CYCLE
      CYCLE -> TIGHTEN (another pass) | DONE

What each state does is the skill's process (rmfit-campaign SKILL.md section 2 "First fits", section 3 steps 1-7, section 4
stopping rules) with the thresholds read from ``spec.json`` (``budget``, ``stop_rules``, ``pre_authorized``).  Anything the
spec does not answer becomes a ``DECISIONS.md`` entry; a pending entry whose default is ``wait`` ends the leg with status
WAITING, and the next leg applies the answers (``adopt-level-*`` answered "adopt" adopts the structure).  Nothing here
decides data treatment: dataset-off tests, missing pairs and review flags are recorded and queued, never acted on.

One leg = one ``rmfit <dir> drive`` call (one SGE job of ``run_crc_drive``): states run until the state machine stops
(DONE / WAITING / STOP), the wall cap ``--max-minutes`` is reached (status CONTINUE: the job script resubmits itself), or
``<dir>/STOP_DRIVE`` exists.  Engine states refuse the login node unless ``--local`` (fixture tests).  ``--dry-run`` prints
the plan from the current state without touching anything.  ``DRIVE.md`` is rewritten after every state for the supervisor.

Build-phase scope (honest limits, 2026-11-08): SCALE_ANCHOR applies the spec's data-set roles (anchor = norm fixed, free =
norm free with the prior as its systematic, excluded = segments off) to a working copy ``<stem>_drive.azr``; SEED_CHANNELS
lifts every FREE width that sits at exactly zero to ``seed_frac`` x gamma_W in the engine and bakes (zero amplitudes never
move, skill 2026-09-25); it does not add channel lines.  PAIR_COMPLETENESS lists the ENSDF excited states of the model's
residual nuclei whose partition opens below the top of the fit window and has no pair -- a finding and a non-blocking
decision for the supervisor, who writes the pair builder (``11B+a/10-27-26_HE_claude/model/add_pairs_he.py`` pattern).
LADDER runs only when the spec gives ``model.ladder_Ex`` (a from-scratch device).  CANDIDATES writes ``candidates.json``
from ENSDF (broad first) when none exists; every candidate needs a ``hypothesis``.
"""
import dataclasses
import json
import os
import re
import shutil
import socket
import time
from typing import List, Optional

from . import AZURE2_ROOT  # noqa: F401
from .spec import FitSpec, Finding, write_findings_md

BUILD_STATES = ["PIN_CHECK", "AUDIT", "REPRODUCE", "SPEC_CHECK", "SCALE_ANCHOR", "SEED_CHANNELS", "PAIR_COMPLETENESS",
                "LADDER", "CANDIDATES", "INIT"]
LOOP_STATES = ["TIGHTEN", "SIGN", "SHIFTS_FREE", "STRUCTURE_ADD", "SIGN_POST", "DATASET_OFF", "REVIEW", "EXPORT", "CYCLE"]
STATES = BUILD_STATES + LOOP_STATES
ENGINE_STATES = {"REPRODUCE", "SEED_CHANNELS", "LADDER", "INIT", "TIGHTEN", "SIGN", "SHIFTS_FREE", "STRUCTURE_ADD",
                 "SIGN_POST", "DATASET_OFF", "REVIEW", "EXPORT"}
STATUS_WORDS = ("CONTINUE", "WAITING", "DONE", "STOP", "ERROR")
STATE_FILE = "drive_state.json"
STOP_FILE = "STOP_DRIVE"

# spec defaults (budget / stop_rules), SKILL.md sections 3-4 and templates/SPEC_TEMPLATE.json
DEFAULT_BUDGET = dict(polish_nfev=150, polish_rounds_max=4, sign_rounds_max=4, level_tests_max=10, level_nfev=150,
                      pinned_nfev=60, dataset_off_max=2, dataset_off_nfev=100, ladder_nfev=100, cycles_max=3,
                      node_hours_max=0, grid_check=True, figures=6)
DEFAULT_STOP = dict(polish_gain_rel_min=5e-4, sign_rounds_without_accept=2, level_adds_marginal_in_a_row=2,
                    cycle_gain_rel_min=1e-3, dataset_off_extra_pct=5.0, reproduce_rtol=1e-3)

SYMBOLS = ["n", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K",
           "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr",
           "Y", "Zr"]


class DriveStop(Exception):
    """Ends the leg with the given status word (STOP or ERROR) and message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def in_sge_job():
    return bool(os.environ.get("JOB_ID"))


class Driver:
    def __init__(self, directory, base=None, sav=None, local=False, log=None):
        self.dir = os.path.abspath(directory)
        os.makedirs(self.dir, exist_ok=True)
        self.local = local
        self._print = log or print
        self.spec_path = os.path.join(self.dir, "spec.json")
        if not os.path.exists(self.spec_path):
            raise DriveStop("ERROR", f"no spec.json in {self.dir}: the spec is the objective; copy rmfit/templates/SPEC_TEMPLATE.json, "
                                     "fill it in (or start from a spec_draft.json) and run `rmfit <dir> spec check` first")
        self.spec = FitSpec.load(self.spec_path)
        self.budget = dict(DEFAULT_BUDGET, **{k: v for k, v in (self.spec.get("budget") or {}).items() if _isnum(v) or isinstance(v, bool)})
        self.stop = dict(DEFAULT_STOP, **{k: v for k, v in (self.spec.get("stop_rules") or {}).items() if _isnum(v)})
        self.state_path = os.path.join(self.dir, STATE_FILE)
        self.state = self._load_state()
        if base:
            base = os.path.abspath(base)
            if self.state.get("base") and os.path.abspath(self.state["base"]) != base:
                self.log(f"WARNING --base {base} differs from the recorded base {self.state['base']}; the recorded one is kept")
            else:
                self.state["base"] = base
        if sav:
            self.state["sav"] = os.path.abspath(sav)
        self._campaign = None
        self.t_leg = time.time()

    # -- state -------------------------------------------------------------------------------------
    def _load_state(self) -> dict:
        if os.path.exists(self.state_path):
            with open(self.state_path) as fh:
                st = json.load(fh)
        else:
            st = {}
        st.setdefault("state", "PIN_CHECK")
        st.setdefault("status", "CONTINUE")
        st.setdefault("cycle", 1)
        st.setdefault("history", [])
        st.setdefault("tested_candidates", [])
        st.setdefault("applied_decisions", [])
        st.setdefault("consumed_decisions", [])
        st.setdefault("dataset_off_tested", [])
        st.setdefault("counters", {})
        st.setdefault("wall_hours", 0.0)
        st.setdefault("findings", {})
        st.setdefault("created", _now())
        return st

    def save(self):
        self.state["updated"] = _now()
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.state, fh, indent=1, default=str)
        os.replace(tmp, self.state_path)

    def log(self, *a):
        msg = " ".join(str(x) for x in a)
        line = f"{time.strftime('%H:%M:%S')} drive {msg}"
        self._print(line)
        with open(os.path.join(self.dir, "campaign.log"), "a") as fh:
            fh.write(line + "\n")

    def note(self, text):
        """A dated readme entry (the campaign's lab notebook; same format as Campaign.note)."""
        if self.campaign is not None:
            self.campaign.note("drive: " + text)
        else:
            with open(os.path.join(self.dir, "readme"), "a") as fh:
                fh.write(f"\n{_now()} (rmfit drive): {text}\n")

    @property
    def campaign(self):
        if self._campaign is None and os.path.exists(os.path.join(self.dir, "campaign.json")):
            from .campaign import Campaign
            self._campaign = Campaign(self.dir, enforce_engine=True)
        return self._campaign

    @property
    def decisions(self):
        if self.campaign is not None:
            return self.campaign.decisions
        from .decisions import DecisionQueue
        return DecisionQueue(os.path.join(self.dir, "DECISIONS.md"))

    @property
    def model(self) -> str:
        """The model the build phase works on (the working copy once SCALE_ANCHOR wrote it), or the campaign's base."""
        if self.campaign is not None:
            return self.campaign.base_azr
        m = self.state.get("model") or self.state.get("base")
        if not m:
            raise DriveStop("ERROR", "no base model: run `rmfit <dir> drive --base <file.azr> [--sav <file.sav>]` the first time")
        return m

    @property
    def counters(self) -> dict:
        return self.state["counters"]

    def _stem(self):
        return os.path.splitext(os.path.basename(self.state.get("base") or self.model))[0]

    # -- decisions ---------------------------------------------------------------------------------
    def ask(self, slug, question, options, default="wait", evidence="") -> Optional[str]:
        """The answer of the latest decision with this slug if it has one and was not consumed yet; otherwise queue it
        (unless one is pending) and return None.  A default other than ``wait`` lets the leg go on with that answer."""
        slug = slug.replace(" ", "-")
        for d in reversed(self.decisions.all()):
            if d["slug"] != slug:
                continue
            if d.pending:
                return None
            if d.id in self.state["consumed_decisions"]:
                break
            self.state["consumed_decisions"].append(d.id)
            self.save()
            return d.get("answer", "")
        did = self.decisions.add(slug, question, evidence=evidence, options=options, default=default)
        self.log(f"decision {did} queued ({slug}): {question}" + (f"  [default if unanswered: {default}]" if default != "wait" else ""))
        if default and default.lower() != "wait":
            self.decisions.answer(did, default, by="default", note="default_if_unanswered applied by rmfit drive")
            self.state["consumed_decisions"].append(did)
            self.save()
            return default
        return None

    def waiting_on(self) -> List[str]:
        return [f"{d.id} {d['slug']}" for d in self.decisions.pending()
                if (d.get("default_if_unanswered") or "wait").strip().lower() == "wait"]

    def apply_decisions(self):
        """Answered ``adopt-level-*`` decisions (queued by Campaign._run_level_add as accept-pending) are applied here."""
        c = self.campaign
        if c is None:
            return
        for d in self.decisions.all():
            if d.pending or d.id in self.state["applied_decisions"] or not d["slug"].startswith("adopt-level"):
                continue
            ans = (d.get("answer") or "").strip().lower()
            m = re.search(r"structure (\d+)", d.get("question", "") + " " + d.get("evidence", ""))
            self.state["applied_decisions"].append(d.id)
            if ans.startswith("adopt") and m:
                sid = int(m.group(1))
                c.adopt_structure(sid, note=f"(decision {d.id} answered '{d.get('answer')}' by {d.get('answered_by', '')})")
                self.counters["adopted_since_sign"] = 1
                self.note(f"decision {d.id} applied: structure {sid} adopted as the base model ({d['slug']})")
            else:
                self.log(f"decision {d.id} ({d['slug']}) answered '{d.get('answer')}': nothing to apply"
                         + ("" if m else " (no structure id in the question)"))
            self.save()

    # -- the leg -----------------------------------------------------------------------------------
    def run(self, max_minutes: float = 0.0, dry_run: bool = False) -> str:
        if dry_run:
            self.print_plan()
            return self.state["status"]
        status = "CONTINUE"
        self.state["status"] = "RUNNING"
        self.state["leg_started"] = _now()
        self.state["leg_host"] = socket.gethostname()
        self.save()
        self.log(f"leg starts at {self.state['state']} (cycle {self.state['cycle']}) on {socket.gethostname()}"
                 + (f", wall cap {max_minutes:g} min" if max_minutes else ""))
        try:
            self.apply_decisions()
            while True:
                if os.path.exists(os.path.join(self.dir, STOP_FILE)):
                    os.remove(os.path.join(self.dir, STOP_FILE))
                    self.note("STOP_DRIVE found: the drive stopped after the current state")
                    status = "STOP"
                    break
                w = self.waiting_on()
                if w:
                    self.log("waiting on " + ", ".join(w))
                    status = "WAITING"
                    break
                if self.state["state"] == "DONE":
                    status = "DONE"
                    break
                nh = float(self.budget.get("node_hours_max") or 0)
                if nh > 0 and self.state["wall_hours"] + (time.time() - self.t_leg) / 3600 > nh:
                    self.note(f"budget.node_hours_max {nh:g} h reached: the drive stopped")
                    status = "STOP"
                    break
                if max_minutes and (time.time() - self.t_leg) / 60 > max_minutes:
                    self.log(f"wall cap {max_minutes:g} min reached: the leg ends, the next one resumes at {self.state['state']}")
                    status = "CONTINUE"
                    break
                st = self.state["state"]
                if st in ENGINE_STATES and not in_sge_job() and not self.local:
                    raise DriveStop("STOP", f"state {st} needs the engine: refusing the login node (qsub run_crc_drive, or --local "
                                            "for a fixture test)")
                self.step(st)
        except DriveStop as e:
            status = e.status
            self.log(f"{status}: {e}")
            self.state["message"] = str(e)
        except Exception as err:  # noqa: BLE001 -- the leg must leave a readable state behind
            import traceback
            status = "ERROR"
            self.state["message"] = f"{type(err).__name__}: {err}"
            self.log("ERROR in state", self.state["state"], ":", traceback.format_exc())
        finally:
            self.state["wall_hours"] = float(self.state["wall_hours"]) + (time.time() - self.t_leg) / 3600
            self.state["status"] = status
            self.state["leg_finished"] = _now()
            self.save()
            self.write_md()
            if self._campaign is not None:
                self._campaign.close()
                self._campaign.ledger.write_status_md()
            self.log(f"DRIVE_STATUS: {status} at {self.state['state']} (leg {(time.time()-self.t_leg)/60:.1f} min, "
                     f"total {self.state['wall_hours']:.2f} h)")
        return status

    def step(self, st):
        handler = getattr(self, "_s_" + st.lower())
        t0 = time.time()
        self.log(f"-- {st} --")
        result = handler() or "next"
        rec = dict(state=st, cycle=self.state["cycle"], when=_now(), minutes=round((time.time() - t0) / 60, 2),
                   result=result if isinstance(result, str) else result[0],
                   note=(result[1] if isinstance(result, tuple) and len(result) > 1 else ""))
        self.state["history"].append(rec)
        if rec["result"] == "next":
            self.state["state"] = self.next_state(st)
        elif rec["result"] == "stay":
            pass
        elif rec["result"] in STATES or rec["result"] == "DONE":
            self.state["state"] = rec["result"]
        self.save()
        self.write_md()

    @staticmethod
    def next_state(st):
        i = STATES.index(st)
        return STATES[i + 1] if i + 1 < len(STATES) else "DONE"

    def print_plan(self):
        cur = self.state["state"]
        self._print(f"rmfit drive plan for {self.dir}  (status {self.state['status']}, cycle {self.state['cycle']}, "
                    f"wall {self.state['wall_hours']:.2f} h)")
        self._print(f"  spec {self.spec_path} sha {str(self.spec.sha)[:10]}; campaign.json {'present' if self.campaign is not None else 'absent'}")
        try:
            self._print(f"  model {self.model}" + (f"  sav {self.state['sav']}" if self.state.get("sav") else ""))
        except DriveStop as e:
            self._print(f"  model: {e}")
        self._print(f"  budget {json.dumps(self.budget)}")
        self._print(f"  stop_rules {json.dumps(self.stop)}")
        done = {h["state"] for h in self.state["history"] if h["result"] != "stay"}
        for s in STATES:
            mark = "->" if s == cur else ("ok" if s in done else "  ")
            need = "engine" if s in ENGINE_STATES else "      "
            self._print(f"  {mark} {s:18s} {need}  {PLAN_TEXT.get(s, '')}")
        pend = self.decisions.pending()
        self._print(f"  pending decisions: {len(pend)}" + ("".join(f"\n     {d.id} {d['slug']}: {d.get('question', '')[:100]}" for d in pend)))
        if self.state.get("message"):
            self._print(f"  last message: {self.state['message']}")

    # -- DRIVE.md ----------------------------------------------------------------------------------
    def write_md(self):
        L = [f"# rmfit drive -- {os.path.basename(self.dir)} ({_now()})", "",
             f"status **{self.state['status']}** at state **{self.state['state']}**, cycle {self.state['cycle']}, "
             f"{self.state['wall_hours']:.2f} node-hours so far; state file `{STATE_FILE}`; stop cleanly with `touch {STOP_FILE}`.", ""]
        if self.state.get("message"):
            L += [f"last message: {self.state['message']}", ""]
        try:
            if self.campaign is not None:
                cid, x, obj, keys = self.campaign.incumbent()
                L += [f"incumbent: candidate {cid}, verified objective {obj:.3f}; base model `{os.path.relpath(self.campaign.base_azr, self.dir)}`", ""]
        except Exception as err:  # noqa: BLE001
            L += [f"incumbent: n/a ({err})", ""]
        pend = self.decisions.pending()
        L += ["## Decisions pending", ""]
        L += [f"- {d.id} `{d['slug']}` (default {d.get('default_if_unanswered', 'wait')}): {d.get('question', '')}" for d in pend] or ["- none"]
        L += ["", "## States", "", "| state | status | last run | min | result | note |", "|---|---|---|---:|---|---|"]
        last = {}
        for h in self.state["history"]:
            last[h["state"]] = h
        for s in STATES:
            h = last.get(s)
            stat = "current" if s == self.state["state"] else ("done" if h and h["result"] != "stay" else ("running" if h else "pending"))
            L.append(f"| {s} | {stat} | {h['when'] if h else ''} | {h['minutes'] if h else ''} | {h['result'] if h else ''} | "
                     f"{(h['note'] or '').replace('|', '/')[:160] if h else ''} |")
        if self.state["findings"]:
            L += ["", "## Build findings", ""]
            for k, rows in self.state["findings"].items():
                L.append(f"### {k}")
                L += [f"- {r}" for r in rows] or ["- none"]
                L.append("")
        L += ["", "## History (last 15)", ""]
        L += [f"- {h['when']} {h['state']} (cycle {h['cycle']}, {h['minutes']} min): {h['result']} {h['note']}" for h in self.state["history"][-15:]]
        with open(os.path.join(self.dir, "DRIVE.md"), "w") as fh:
            fh.write("\n".join(L) + "\n")

    # -- helpers -----------------------------------------------------------------------------------
    def _finding_rows(self, key, rows):
        self.state["findings"][key] = list(rows)[:60]

    def _ex_top(self) -> Optional[float]:
        """Top of the fit window in Ex (MeV): spec model.fit_window.Ex_MeV, else the highest data point of any active segment."""
        fw = (self.spec.get("model") or {}).get("fit_window") or {}
        if fw.get("Ex_MeV"):
            return float(fw["Ex_MeV"][1])
        try:
            from pyazr.datasets import SegmentSet
            from .model import cm_conversion, rows_in_segment
            from .windows import pair_separation
            text = open(self.model).read()
            segs = SegmentSet.from_file(self.model)
            base = os.path.dirname(self.model)
            top = None
            for s in segs:
                if not s.active:
                    continue
                r = rows_in_segment(s, base)
                if r.shape[0] == 0:
                    continue
                e = float(r[:, 0].max())
                e = min(e, s.energy_max) if s.energy_max > 0 else e
                ex = pair_separation(text, s.entrance_key) + cm_conversion(text, s.entrance_key) * e
                top = ex if top is None else max(top, ex)
            return top
        except Exception as err:  # noqa: BLE001
            self.log(f"fit-window top from the segments failed ({err})")
            return None

    def _seed_vector(self, ev):
        from .campaign import Campaign
        return Campaign._seed_vector(self, ev, self.state.get("sav"))

    def _job_script(self, overwrite=False) -> str:
        return write_job_script(self.dir, self.spec, self.campaign.cfg if self.campaign is not None else None, overwrite=overwrite)

    # ==================================================================================================
    # build phase
    # ==================================================================================================
    def _s_pin_check(self):
        from . import enginepin
        cur = enginepin.fingerprint()
        self.state["engine"] = cur
        if self.campaign is not None:
            rec = self.campaign.cfg.get("engine")
            if rec and rec.get("so_md5") and rec["so_md5"] != cur["so_md5"]:
                raise DriveStop("STOP", f"engine pin mismatch: campaign {enginepin.short(rec)} vs imported {enginepin.short(cur)}")
            return "next", f"campaign pin {enginepin.short(rec) if rec else '(none)'} matches"
        eng = self.spec.get("engine") or {}
        if eng.get("so_md5") and eng["so_md5"] != cur["so_md5"]:
            raise DriveStop("STOP", f"spec.engine.so_md5 {eng['so_md5'][:8]} != imported engine {enginepin.short(cur)}: run from the "
                                    f"spec's azure2_root ({eng.get('azure2_root')})")
        if os.path.realpath(cur.get("azure2_root", "")) == os.path.realpath(os.path.expanduser("~/AZURE2")) and not self.local:
            self.log("WARNING the imported engine is the SHARED checkout ~/AZURE2 (weekly releases replace it): a campaign should "
                     "pin a frozen copy; INIT will pin what this job imports")
        self._job_script()
        return "next", f"imported engine {enginepin.short(cur)}"

    def _s_audit(self):
        from .audit import audit_model, write_audit
        cfg = self.campaign.cfg if self.campaign is not None else None
        fs = audit_model(self.model, campaign_dir=self.dir, campaign_cfg=cfg, run_target_energies=True)
        counts = write_audit(fs, os.path.join(self.dir, "AUDIT.md"), self.model)
        highs = [f for f in fs if f.severity == "HIGH"]
        self._finding_rows("AUDIT.md", [f.line() for f in sorted(fs, key=lambda f: {"HIGH": 0, "MEDIUM": 1}.get(f.severity, 2))][:30])
        if highs:
            ans = self.ask("audit-high", f"AUDIT.md has {len(highs)} HIGH finding(s): " + "; ".join(f.message[:90] for f in highs[:3])
                           + ". Fix the input and answer 'fixed' (the audit re-runs), or 'accepted' to go on with them recorded.",
                           ("fixed", "accepted"), default="wait", evidence="AUDIT.md")
            if ans is None:
                return "stay", f"{len(highs)} HIGH -> waiting"
            if ans.lower().startswith("fixed"):
                return "stay", "re-running the audit after 'fixed'"
            self.note(f"AUDIT.md HIGH findings accepted by decision ({', '.join(f.code for f in highs)})")
        return "next", ", ".join(f"{k} {v}" for k, v in counts.items())

    def _s_reproduce(self):
        """Mode-1 reproduction before building (skill section 2 item 2): the base model + .sav must give the archived
        chiSquared.out total.  Plain chi2 is compared (the norm penalty's convention differs between the CLI and rmfit)."""
        from .review import output_dir_of, read_chisq_out
        from .engine import SingleSession
        from .model import single_variant
        if self.campaign is not None:
            return "next", "campaign exists: the baseline was verified at init"
        odir = output_dir_of(self.model)
        cs = os.path.join(odir, "chiSquared.out") if odir else None
        if not cs or not os.path.exists(cs):
            return "next", "no archived chiSquared.out next to the model: nothing to reproduce"
        tab = read_chisq_out(cs)
        ref = sum(d["chi2"] for d in tab.values())
        nref = sum(d["n"] for d in tab.values())
        flags = self.spec.flags()
        vdir = os.path.join(self.dir, "variants")
        os.makedirs(vdir, exist_ok=True)
        src = single_variant(self.model, "drive_reproduce", vdir)
        with SingleSession(src, cwd=vdir, flags=flags, name="drive_reproduce") as ev:
            x = self._seed_vector(ev)
            sc = ev.score(x)
        rel = abs(sc.chi2 - ref) / max(abs(ref), 1e-300)
        msg = f"plain chi2 {sc.chi2:.3f} (N {sc.npts}) vs chiSquared.out {ref:.3f} (N {nref}): {100*rel:.3f} %"
        self.state["reproduce"] = dict(chi2=sc.chi2, ref=ref, n=sc.npts, nref=nref, rel=rel)
        if rel > float(self.stop["reproduce_rtol"]) or sc.npts != nref:
            ans = self.ask("reproduce-mismatch", f"the base model does not reproduce its archived chiSquared.out ({msg}); flags "
                           f"{flags}. 'accept' to build on it anyway, 'stop' to fix the input first.", ("accept", "stop"),
                           default="wait", evidence="campaign.log REPRODUCE")
            if ans is None:
                return "stay", msg + " -> waiting"
            if ans.lower().startswith("stop"):
                raise DriveStop("STOP", "reproduction mismatch not accepted: " + msg)
            self.note(f"REPRODUCE mismatch accepted by decision: {msg}")
        else:
            self.note(f"REPRODUCE: the base model reproduces its archived chiSquared.out ({msg})")
        return "next", msg

    def _s_spec_check(self):
        cfg = self.campaign.cfg if self.campaign is not None else None
        fs = self.spec.check(self.model, campaign_cfg=cfg)
        out = os.path.join(self.dir, "SPEC_CHECK.md")
        counts = write_findings_md(out, "Spec check (rmfit drive)", fs, [f"spec `{self.spec_path}` vs model `{self.model}`", ""])
        highs = [f for f in fs if f.severity == "HIGH"]
        fixable = {"spec-excluded-active", "spec-norm-fixed"}        # SCALE_ANCHOR switches excluded sets off / fixes anchor norms
        blocking = [f for f in highs if f.code not in fixable or self.campaign is not None]
        self._finding_rows("SPEC_CHECK.md", [f.line() for f in fs][:30])
        if blocking:
            ans = self.ask("spec-high", f"spec check: {len(blocking)} HIGH disagreement(s) between spec.json and the model: "
                           + "; ".join(f.message[:90] for f in blocking[:3]) + ". Fix one of them and answer 'fixed', or 'accepted'.",
                           ("fixed", "accepted"), default="wait", evidence="SPEC_CHECK.md")
            if ans is None:
                return "stay", f"{len(blocking)} HIGH -> waiting"
            if ans.lower().startswith("fixed"):
                return "stay", "re-checking after 'fixed'"
            self.note(f"SPEC_CHECK HIGH findings accepted by decision ({', '.join(f.code for f in blocking)})")
        return "next", ", ".join(f"{k} {v}" for k, v in counts.items())

    def _s_scale_anchor(self):
        """Apply the spec's data-set roles to a working copy (First fits item 1): anchor -> norm fixed; free -> norm free,
        prior_sigma as the systematic (percent); excluded -> segments off."""
        if self.campaign is not None:
            return "next", "campaign exists: roles were applied before init"
        from pyazr import AzrModel
        mdl = AzrModel.from_file(self.model)
        changed, rows = 0, []
        for ds in self.spec.data_sets:
            f = ds.get("file")
            if not f:
                continue
            role = ds.get("role", "free")
            norm = ds.get("norm") or {}
            try:
                if role == "excluded" or role == "excluded_in_window":
                    mdl.set_segment_active(f, False)
                    rows.append(f"{f}: {role} -> segments off")
                elif role in ("anchor", "anchor_geometry") or norm.get("fixed") is True:
                    n = mdl.set_segment_norm(f, vary=False)
                    rows.append(f"{f}: {role} -> norm fixed on {n} segment(s)")
                elif role == "free":
                    sig = norm.get("prior_sigma")
                    n = mdl.set_segment_norm(f, vary=(not norm.get("fixed", False)),
                                             sys_error=(100.0 * float(sig) if sig is not None else None))
                    rows.append(f"{f}: free -> norm {'free' if not norm.get('fixed') else 'fixed'}" + (f", systematic {100*float(sig):g} %" if sig is not None else "") + f" on {n} segment(s)")
                else:
                    continue
                changed += 1
            except KeyError as err:
                rows.append(f"{f}: no matching segment ({err})")
        out = os.path.join(self.dir, self._stem() + "_drive.azr")
        os.makedirs(os.path.join(self.dir, "output"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "checks"), exist_ok=True)
        mdl.set_output_dir(os.path.join(self.dir, "output"))
        mdl.write(out)
        sav = self.state.get("sav")
        if sav and os.path.exists(sav):
            shutil.copy2(sav, os.path.splitext(out)[0] + ".sav")
            self.state["sav"] = os.path.splitext(out)[0] + ".sav"
        self.state["model"] = out
        self._finding_rows("SCALE_ANCHOR", rows)
        self.note(f"SCALE_ANCHOR: spec roles applied to {os.path.basename(out)} ({changed} data sets): " + "; ".join(rows))
        return "next", f"{changed} data sets -> {os.path.basename(out)}"

    def _s_seed_channels(self):
        """First fits item 2 for the channels that already exist: every FREE width at exactly zero is lifted to seed_frac x
        gamma_W (in the engine, skill 2026-09-18 / 09-25: never in keV, zero never moves) and the model is baked."""
        if self.campaign is not None:
            return "next", "campaign exists: seeds belong before init"
        from .engine import SingleSession, bake
        from .model import single_variant
        from .local import BoundsPolicy
        from pyazr import AzrModel
        frac = float((self.spec.get("model") or {}).get("seed_frac", 0.01))
        eps = float((self.spec.get("bounds") or {}).get("sign_eps", BoundsPolicy().sign_eps))
        flags = self.spec.flags()
        vdir = os.path.join(self.dir, "variants")
        os.makedirs(vdir, exist_ok=True)
        src = single_variant(self.model, "drive_seed", vdir)
        with SingleSession(src, cwd=vdir, flags=flags, name="drive_seed") as ev:
            x = self._seed_vector(ev)
            gW = ev.wigner_amplitudes()
            zero = [j for j, k in enumerate(ev.keys) if k.kind == "width" and gW.get(j, 0) > 0 and abs(x[j]) < eps * gW[j]]
            if not zero:
                return "next", "no free width at zero: nothing to seed"
            sc0 = ev.score(x)
            x1 = x.copy()
            for j in zero:
                x1[j] = frac * gW[j]
            sc1 = ev.score(x1)
            if sc0.objective > 0 and sc1.objective > 1.2 * sc0.objective:
                self.log(f"seed {frac:g} gamma_W raises the objective {sc0.objective:.1f} -> {sc1.objective:.1f}: halving the seed")
                frac *= 0.5
                for j in zero:
                    x1[j] = frac * gW[j]
                sc1 = ev.score(x1)
            keys = list(ev.keys)
            labels = [str(keys[j]) for j in zero]
        out = os.path.join(self.dir, self._stem() + "_seeded.azr")
        azr, sav, scb = bake(self.model, x1, keys, out, flags, workdir=vdir, output_dir=os.path.join(self.dir, "output"),
                             name="drive_seed_bake", separate=False)
        # non-seeded physical widths must survive the bake (seed_stage1.py width_check: a failed Brune transform at load
        # rescales a whole level)
        A, B = AzrModel.from_file(self.model), AzrModel.from_file(azr)
        bad = []
        for la, lb in zip(A.active_levels, B.active_levels):
            for ca, cb in zip(la.channels, lb.channels):
                if abs(ca.gamma) <= 1e-6:
                    continue
                if abs(cb.gamma / ca.gamma - 1) > 0.01:
                    bad.append(f"{la.jpi} {la.energy:.4f} pair {ca.pair} L{ca.L}: {ca.gamma:.5g} -> {cb.gamma:.5g}")
        if bad:
            raise DriveStop("ERROR", f"seed bake changed {len(bad)} non-seeded widths by > 1 %: " + "; ".join(bad[:4]))
        self.state["model"], self.state["sav"] = azr, sav
        self.state["seeds"] = dict(frac=frac, n=len(zero), before=sc0.objective, after=sc1.objective, baked=scb.objective)
        self._finding_rows("SEED_CHANNELS", [f"{len(zero)} free widths at zero seeded at {frac:g} gamma_W: objective {sc0.objective:.1f} -> "
                                             f"{sc1.objective:.1f} (baked {scb.objective:.1f})"] + labels[:40])
        self.note(f"SEED_CHANNELS: {len(zero)} free widths at exactly zero lifted to {frac:g} gamma_W and baked into "
                  f"{os.path.basename(azr)} (objective {sc0.objective:.1f} -> {sc1.objective:.1f}; non-seeded widths unchanged)")
        return "next", f"{len(zero)} seeds at {frac:g} gamma_W -> {os.path.basename(azr)}"

    def _s_pair_completeness(self):
        """First fits item 3 as a check: excited states (ENSDF) of the model's residual nuclei whose partition opens below the
        top of the fit window and has no pair.  Reported and queued (default 'continue'); the pair builder is the
        supervisor's (reaction-specific radii, channel spins, summed segments)."""
        from pyazr import AzrModel
        top = self._ex_top()
        if top is None:
            return "next", "fit-window top unknown: skipped"
        mdl = AzrModel.from_file(self.model)
        pairs = mdl.pair_lines()
        have = {}          # (z_light, a_light, z_heavy, a_heavy) -> {e2 values}, sepE
        rows, missing = [], []
        for key, c in pairs.items():
            if bool(getattr(c, "is_photon", False)):
                continue
            try:
                z1, m1, z2, m2 = c._get("z1", int), c._get("m1", float), c._get("z2", int), c._get("m2", float)
                sep, e2 = c._get("sepE", float), c._get("e2", float)
            except Exception:  # noqa: BLE001
                continue
            part = (z1, int(round(m1)), z2, int(round(m2)))
            d = have.setdefault(part, dict(e2=set(), sep=sep, keys=[]))
            d["e2"].add(round(e2, 3))
            d["keys"].append(key)
            rows.append(f"pair {key}: {_nuc(z1, m1)} + {_nuc(z2, m2)}(E* {e2:.4f}) threshold Ex {sep + e2:.4f}")
        try:
            from pyazr.nds import fetch_levels
        except Exception as err:  # noqa: BLE001
            self._finding_rows("PAIR_COMPLETENESS", rows + [f"ENSDF client unavailable ({err})"])
            return "next", "pyazr.nds unavailable: pairs listed only"
        for part, d in have.items():
            z, a = part[2], part[3]
            try:
                levels = fetch_levels(f"{a}{SYMBOLS[z].lower()}" if z < len(SYMBOLS) else f"{a}z{z}")
            except Exception as err:  # noqa: BLE001
                rows.append(f"{_nuc(z, a)}: ENSDF fetch failed ({err})")
                continue
            for lv in levels:
                ex_state = float(lv.energy_mev)
                thr = d["sep"] + ex_state
                if ex_state <= 0.0 or thr >= top:
                    continue
                if any(abs(ex_state - e) < 0.005 for e in d["e2"]):
                    continue
                missing.append(f"{_nuc(part[0], part[1])} + {_nuc(z, a)}({ex_state:.4f} {lv.jp}) opens at Ex {thr:.4f} < {top:.3f}: no pair")
        self._finding_rows("PAIR_COMPLETENESS", rows + (missing or ["every ENSDF state of the residual nuclei below the window top has a pair"]))
        self.state["pairs_missing"] = missing
        if missing:
            self.note(f"PAIR_COMPLETENESS: {len(missing)} partition(s) open below Ex {top:.3f} MeV without a pair: " + "; ".join(missing[:6])
                      + ". First-fits rule 3: add a pair for each before fitting (builder pattern 11B+a/10-27-26_HE_claude/model/add_pairs_he.py); "
                        "a window cap instead is a stop-gap to log.")
            self.ask("missing-pairs", f"{len(missing)} partition(s) open below the window top have no pair (DRIVE.md). Add them (the drive "
                     f"re-runs from SCALE_ANCHOR on the new base) or 'continue' without.", ("added", "continue"), default="continue",
                     evidence="DRIVE.md PAIR_COMPLETENESS")
        return "next", f"{len(pairs)} pairs, {len(missing)} missing partitions below Ex {top:.3f}"

    def _s_ladder(self):
        """First fits item 4 when the spec asks for it (model.ladder_Ex = [cutoffs]): data up to each cutoff, levels above
        fixed, polished and carried forward by key; the final vector is baked as the base for INIT."""
        if self.campaign is not None:
            return "next", "campaign exists"
        cuts = (self.spec.get("model") or {}).get("ladder_Ex")
        if not cuts:
            return "next", "no model.ladder_Ex in the spec: skipped"
        from .windows import ladder_variants
        from .engine import Sharded, SingleSession, bake
        from .local import polish, default_bounds, BoundsPolicy
        from .keys import take
        from .model import single_variant
        from .campaign import _dc_from
        flags = self.spec.flags()
        policy = _dc_from(BoundsPolicy, self.spec.get("bounds"))
        nshards = int(self.spec.get("nshards") or 8)
        nfev = int(self.budget["ladder_nfev"])
        vdir = os.path.join(self.dir, "variants", "ladder")
        steps = ladder_variants(self.model, vdir, [float(c) for c in cuts])
        src = single_variant(self.model, "drive_ladder_base", os.path.join(self.dir, "variants"))
        with SingleSession(src, cwd=os.path.join(self.dir, "variants"), flags=flags, name="drive_ladder_base") as ev0:
            x_full, keys_full = self._seed_vector(ev0), list(ev0.keys)
            obj0 = ev0.score(x_full).objective
        rows = []
        for i, info in enumerate(steps):
            path = os.path.join(vdir, f"step{i+1}_Ex{info['cutoff']:g}.azr")
            ev = Sharded(path, os.path.join(vdir, f"shards_step{i+1}"), nshards=nshards, flags=flags)
            try:
                xs = take(x_full, keys_full, ev.keys, ev.x0)
                s0 = ev.score(xs).objective
                fr = polish(ev, xs, bounds=default_bounds(ev, xs, policy), policy=policy, max_nfev=nfev, log=self.log)
                x_full = take(fr.x, ev.keys, keys_full, x_full)
                rows.append(f"step {i+1} Ex <= {info['cutoff']:g}: {s0:.1f} -> {fr.objective:.1f} ({fr.status}, {fr.nfev} evaluations, {len(ev.keys)} free)")
                self.log(rows[-1])
            finally:
                ev.close()
        out = os.path.join(self.dir, self._stem() + "_ladder.azr")
        azr, sav, sc = bake(self.model, x_full, keys_full, out, flags, workdir=os.path.join(self.dir, "variants"),
                            output_dir=os.path.join(self.dir, "output"), name="drive_ladder_bake")
        rows.append(f"full model: {obj0:.1f} -> {sc.objective:.1f} baked into {os.path.basename(azr)}")
        self.state["model"], self.state["sav"] = azr, sav
        self._finding_rows("LADDER", rows)
        self.note("LADDER: " + "; ".join(rows))
        return "next", rows[-1]

    def _s_candidates(self):
        """candidates.json: kept if present (every entry needs a hypothesis); else built from the ENSDF adopted levels of
        spec.compound_nucleus inside the fit window that have no active level within 30 keV, broad first."""
        path = os.path.join(self.dir, "candidates.json")
        if os.path.exists(path):
            bank = json.load(open(path)).get("candidates", [])
            lacking = [i for i, c in enumerate(bank) if not (c.get("hypothesis") or c.get("note"))]
            self._finding_rows("CANDIDATES", [f"{len(bank)} candidates in candidates.json; {len(lacking)} without a hypothesis (skipped by STRUCTURE_ADD): {lacking}"])
            return "next", f"{len(bank)} candidates kept ({len(lacking)} lack a hypothesis)"
        cn = self.spec.get("compound_nucleus")
        if not cn:
            json.dump(dict(candidates=[], note="no compound_nucleus in the spec: empty bank"), open(path, "w"), indent=1)
            return "next", "no compound_nucleus in the spec: empty candidates.json"
        from pyazr import AzrModel
        top = self._ex_top()
        fw = (self.spec.get("model") or {}).get("fit_window") or {}
        lo = float(fw["Ex_MeV"][0]) if fw.get("Ex_MeV") else 0.0
        mdl = AzrModel.from_file(self.model)
        have = [(lv.jpi, float(lv.energy)) for lv in mdl.active_levels]
        try:
            from pyazr.nds import fetch_levels
            levels = fetch_levels(cn.lower())
        except Exception as err:  # noqa: BLE001
            json.dump(dict(candidates=[], note=f"ENSDF fetch failed: {err}"), open(path, "w"), indent=1)
            return "next", f"ENSDF fetch failed ({err}): empty candidates.json"
        cands = []
        for lv in levels:
            ex = float(lv.energy_mev)
            if ex < lo or (top is not None and ex > top):
                continue
            if any(abs(ex - e) < 0.030 for _, e in have):
                continue
            jp = (lv.jp or "").strip()
            clean = re.fullmatch(r"\(?(\d+(/2)?)([+-])\)?", jp.replace(" ", ""))
            jpi = f"{clean.group(1)}{clean.group(3)}" if clean else None
            w = lv.width_kev
            cands.append(dict(energy=round(ex, 4), jpi=jpi, energy_fixed=True, channels=[], source="ensdf",
                              width_kev=w, hypothesis=f"ENSDF adopted level {ex:.4f} MeV {jp or '(J unknown)'}"
                              + (f", Gamma {w:g} keV" if w else "") + " has no level in the model within 30 keV"))
        cands.sort(key=lambda c: (-(c["width_kev"] or 0.0), c["energy"]))     # broad first (skill: Gamma > 10 keV first)
        nmax = int(self.budget["level_tests_max"])
        json.dump(dict(candidates=cands[:nmax], dropped_by_budget=len(cands) - min(len(cands), nmax),
                       note=f"ENSDF {cn} levels in Ex {lo:g}-{top if top is not None else 'top'} MeV without a model level within 30 keV; "
                            f"broad first; written by rmfit drive {_now()}"), open(path, "w"), indent=1)
        self._finding_rows("CANDIDATES", [f"{c['energy']:.4f} {c['jpi'] or 'scan'} {c['hypothesis']}" for c in cands[:nmax]])
        self.note(f"CANDIDATES: candidates.json written from ENSDF {cn}: {min(len(cands), nmax)} levels "
                  f"({len(cands) - min(len(cands), nmax)} more dropped by budget.level_tests_max {nmax}), broad first")
        return "next", f"{min(len(cands), nmax)} ENSDF candidates"

    def _s_init(self):
        if self.campaign is not None:
            return "next", "campaign exists"
        from .campaign import Campaign
        c = Campaign.init(self.dir, self.model, sav=self.state.get("sav"), spec=self.spec_path,
                          note=f"rmfit drive on {os.path.basename(self.model)}")
        c.write_job_script()
        self._campaign = c
        cid, x, obj, keys = c.incumbent()
        self.state["cycle_start_objective"] = obj
        self.state["baseline_objective"] = obj
        self._job_script(overwrite=True)
        return "next", f"campaign initialised: baseline {obj:.3f} (candidate {cid})"

    # ==================================================================================================
    # loop phase
    # ==================================================================================================
    def _incumbent_obj(self) -> float:
        return float(self.campaign.incumbent()[2])

    def _s_tighten(self):
        c = self.campaign
        if c is None:
            raise DriveStop("ERROR", "no campaign.json: the build phase did not reach INIT")
        n = int(self.counters.get("polish_rounds", 0))
        if n >= int(self.budget["polish_rounds_max"]):
            self.counters["polish_rounds"] = 0
            return "next", f"budget.polish_rounds_max {self.budget['polish_rounds_max']} reached"
        before = self._incumbent_obj()
        fr = c.run_polish(max_nfev=int(self.budget["polish_nfev"]), tighten=(n == 0), note="rmfit drive TIGHTEN")
        after = self._incumbent_obj()
        gain = (before - after) / max(abs(before), 1e-300)
        self.counters["polish_rounds"] = n + 1
        msg = f"round {n+1}: {before:.3f} -> {after:.3f} ({100*gain:.3f} %, {fr.status}, {fr.nfev} evaluations)"
        if gain < float(self.stop["polish_gain_rel_min"]) or fr.status == "crashed":
            self.counters["polish_rounds"] = 0
            return "next", msg + " -> converged" if fr.status != "crashed" else msg
        return "stay", msg

    def _sign_state(self, label):
        c = self.campaign
        n = int(self.counters.get(f"{label}_rounds", 0))
        noacc = int(self.counters.get(f"{label}_noaccept", 0))
        if n >= int(self.budget["sign_rounds_max"]):
            self.counters[f"{label}_rounds"] = self.counters[f"{label}_noaccept"] = 0
            return "next", f"budget.sign_rounds_max {self.budget['sign_rounds_max']} reached"
        st = c.run_sign_round(note=f"rmfit drive {label}")
        acc = int(st.get("accepted", 0) or 0)
        n += 1
        noacc = 0 if acc else noacc + 1
        self.counters[f"{label}_rounds"], self.counters[f"{label}_noaccept"] = n, noacc
        msg = (f"round {n}: {st.get('proposed')} proposals, {st.get('improving_screen')} improving on screen, {acc} accepted, "
               f"{st.get('before', 0):.3f} -> {st.get('verified', st.get('after', 0)):.3f}")
        if n >= 2 and noacc >= int(self.stop["sign_rounds_without_accept"]):
            self.counters[f"{label}_rounds"] = self.counters[f"{label}_noaccept"] = 0
            self.counters["adopted_since_sign"] = 0
            return "next", msg + f" -> {noacc} rounds without an acceptance: converged for this structure"
        return "stay", msg

    def _s_sign(self):
        return self._sign_state("sign")

    def _s_sign_post(self):
        if not self.counters.get("adopted_since_sign"):
            return "next", "no structure change since the last sign rounds: skipped"
        return self._sign_state("sign_post")

    def _s_shifts_free(self):
        c = self.campaign
        if not self.spec.pre_authorized.get("shifts_free", False) is True:
            return "next", "pre_authorized.shifts_free is not true: skipped"
        before = self._incumbent_obj()
        fr = c.run_polish(max_nfev=int(self.budget["polish_nfev"]), shifts_free=True, note="rmfit drive SHIFTS_FREE")
        after = self._incumbent_obj()
        return "next", f"{before:.3f} -> {after:.3f} ({fr.status}, {fr.nfev} evaluations)"

    def _s_structure_add(self):
        c = self.campaign
        from .structure import LevelCandidate
        path = os.path.join(self.dir, "candidates.json")
        bank = json.load(open(path)).get("candidates", []) if os.path.exists(path) else []
        tested = set(int(i) for i in self.state["tested_candidates"])
        marg = int(self.counters.get("marginal_in_a_row", 0))
        ntests = int(self.counters.get("level_tests", 0))
        if ntests >= int(self.budget["level_tests_max"]):
            return "next", f"budget.level_tests_max {self.budget['level_tests_max']} reached ({len(bank) - len(tested)} untested)"
        if marg >= int(self.stop["level_adds_marginal_in_a_row"]):
            self.counters["marginal_in_a_row"] = 0
            return "next", f"{marg} marginal adds in a row: the queue ends here ({len(bank) - len(tested)} untested)"
        nxt = None
        # broad first (DeBoer: Gamma > 10 keV first, narrow alignment later; DESIGN.md 2.2): a candidate's width is its
        # width_kev, else the sum of its seed channel widths; unknown widths keep the bank's order after the known ones
        order = sorted((i for i in range(len(bank)) if i not in tested), key=lambda i: (-_cand_width_kev(bank[i]), i))
        for i in order:
            cand = bank[i]
            if not (cand.get("hypothesis") or cand.get("note")):
                self.log(f"candidate {i} ({cand.get('energy')} {cand.get('jpi')}) has no hypothesis: skipped (every structure candidate needs one)")
                self.state["tested_candidates"].append(i)
                tested.add(i)
                continue
            nxt = (i, cand)
            break
        if nxt is None:
            return "next", f"every candidate tested ({len(bank)})"
        i, spec = nxt
        cand = LevelCandidate(energy=float(spec["energy"]), jpi=spec.get("jpi"), channels=spec.get("channels", []),
                              source=spec.get("source", "drive"), note=(spec.get("hypothesis") or spec.get("note") or ""),
                              energy_fixed=spec.get("energy_fixed", True))
        self.log(f"candidate {i}: {cand.jpi or 'scan'} @ {cand.energy} MeV -- hypothesis: {cand.note}")
        st = c.run_level_add(cand, jpis=([cand.jpi] if cand.jpi else None), global_nfev=int(self.budget["level_nfev"]),
                             pinned_nfev=int(self.budget["pinned_nfev"]), note="rmfit drive")
        self.state["tested_candidates"].append(i)
        self.counters["level_tests"] = ntests + 1
        out = st.get("outcome", "?")
        if out == "accept":
            self.counters["marginal_in_a_row"] = 0
            self.counters["adopted_since_sign"] = 1
        elif out == "accept-pending":
            self.counters["marginal_in_a_row"] = 0
        else:
            self.counters["marginal_in_a_row"] = marg + 1
        return "stay", f"candidate {i} {st.get('jpi', cand.jpi) or 'scan'} @ {cand.energy}: {out} (delta {st.get('delta', float('nan')):+.1f})"

    def _s_dataset_off(self):
        """Step 5: the Botek test on the worst chi2/N sets; the result is a table and (if the extra recovery is large) a
        decision with default 'keep' -- whether a data set stays is the evaluator's."""
        c = self.campaign
        import statistics
        cid = c.incumbent()[0]
        rows = c.dataset_table(cid)
        if len(rows) < 2:
            return "next", "fewer than two data sets"
        med = statistics.median(r["per_pt"] for r in rows)
        done = set(self.state["dataset_off_tested"])
        worst = [r for r in rows if r["per_pt"] > max(3.0 * med, 3.0) and r["name"] not in done][: int(self.budget["dataset_off_max"])]
        if not worst or len(done) >= int(self.budget["dataset_off_max"]):
            return "next", f"{len(done)} sets tested this cycle; median chi2/N {med:.2f}"
        r = worst[0]
        st = c.run_dataset_off(r["name"], nfev=int(self.budget["dataset_off_nfev"]), note="rmfit drive")
        self.state["dataset_off_tested"].append(r["name"])
        pct = float(st.get("extra_pct", 0.0))
        msg = f"{r['name']} (chi2/N {r['per_pt']:.1f} vs median {med:.1f}): extra recovery {st.get('extra_recovery', 0):+.0f} ({pct:.2f} %)"
        if pct > float(self.stop["dataset_off_extra_pct"]):
            self.ask(f"dataset-off-{r['name']}", f"{r['name']} distorts the rest of the fit: {msg}. Keep it, exclude it (role excluded in spec.json, "
                     f"then re-init), or change its treatment?", ("keep", "exclude", "retreat"), default="keep", evidence="readme dataset-off entry; REPORT.md")
        return "stay", msg

    def _s_review(self):
        c = self.campaign
        from .review import review_campaign
        r = review_campaign(c, grid_check=bool(self.budget.get("grid_check", True)), figures=int(self.budget.get("figures", 6)))
        highs = [f for f in r["findings"] if f.severity == "HIGH"]
        counts = r["counts"]
        if highs:
            ans = self.ask("review-high", f"REVIEW.md has {len(highs)} HIGH flag(s): " + "; ".join(f"{f.code}: {f.message[:80]}" for f in highs[:3])
                           + ". Look at figures/review_*.png; 'continue' to export as is, 'stop' to intervene.", ("continue", "stop"),
                           default="wait", evidence="REVIEW.md; figures/review_*.png")
            if ans is None:
                return "stay", f"{len(highs)} HIGH review flags -> waiting"
            if ans.lower().startswith("stop"):
                raise DriveStop("STOP", "review HIGH flags: evaluator asked to stop")
        return "next", ", ".join(f"{k} {v}" for k, v in counts.items())

    def _s_export(self):
        c = self.campaign
        azr, sav, sc = c.export(note="rmfit drive export")
        c.report()
        return "next", f"{os.path.basename(azr)} objective {sc.objective:.3f}"

    def _s_cycle(self):
        obj = self._incumbent_obj()
        start = float(self.state.get("cycle_start_objective") or obj)
        gain = (start - obj) / max(abs(start), 1e-300)
        cyc = int(self.state["cycle"])
        path = os.path.join(self.dir, "candidates.json")
        bank = json.load(open(path)).get("candidates", []) if os.path.exists(path) else []
        untested = len(bank) - len(set(self.state["tested_candidates"]))
        msg = f"cycle {cyc}: {start:.3f} -> {obj:.3f} ({100*gain:.3f} %); {untested} candidates untested"
        self.note(f"CYCLE {cyc} complete: objective {start:.3f} -> {obj:.3f} ({100*gain:.3f} %), {untested} candidates untested; "
                  + ("another pass" if gain >= float(self.stop["cycle_gain_rel_min"]) and cyc < int(self.budget["cycles_max"]) else "DONE"))
        if gain >= float(self.stop["cycle_gain_rel_min"]) and cyc < int(self.budget["cycles_max"]):
            self.state["cycle"] = cyc + 1
            self.state["cycle_start_objective"] = obj
            self.state["dataset_off_tested"] = []
            self.counters["level_tests"] = 0
            self.counters["marginal_in_a_row"] = 0
            return "TIGHTEN", msg + " -> another pass"
        return "DONE", msg + " -> DONE"


PLAN_TEXT = {
    "PIN_CHECK": "imported engine vs the campaign pin / spec.engine; writes run_crc_drive",
    "AUDIT": "rmfit.audit -> AUDIT.md; HIGH -> decision audit-high (wait)",
    "REPRODUCE": "base model + .sav vs the archived chiSquared.out (plain chi2); mismatch -> decision (wait)",
    "SPEC_CHECK": "spec.json vs the model -> SPEC_CHECK.md; HIGH -> decision spec-high (wait)",
    "SCALE_ANCHOR": "spec data-set roles applied to <stem>_drive.azr (anchor fixed, free with prior, excluded off)",
    "SEED_CHANNELS": "free widths at exactly zero -> seed_frac x gamma_W, baked to <stem>_seeded.azr",
    "PAIR_COMPLETENESS": "ENSDF states of the residual nuclei open below the window top without a pair -> finding + decision (continue)",
    "LADDER": "model.ladder_Ex steps polished and carried forward (skipped without it)",
    "CANDIDATES": "candidates.json kept, or built from ENSDF <compound_nucleus> (broad first, hypothesis each)",
    "INIT": "Campaign.init --spec (baseline verified, engine pinned)",
    "TIGHTEN": "polish --tighten rounds until gain < polish_gain_rel_min (budget polish_rounds_max)",
    "SIGN": "sign rounds until sign_rounds_without_accept (>= 2 rounds; budget sign_rounds_max)",
    "SHIFTS_FREE": "polish --shifts-free if pre_authorized.shifts_free",
    "STRUCTURE_ADD": "level add per candidates.json entry (hypothesis required); adoption per pre_authorized.adopt_level",
    "SIGN_POST": "sign rounds again if a structure was adopted",
    "DATASET_OFF": "Botek test on the worst chi2/N sets (budget dataset_off_max); large extra recovery -> decision (keep)",
    "REVIEW": "rmfit review (+ grid check) -> REVIEW.md; HIGH -> decision review-high (wait)",
    "EXPORT": "export + report",
    "CYCLE": "another pass from TIGHTEN if the cycle gained >= cycle_gain_rel_min and cycles < cycles_max, else DONE",
}


def _cand_width_kev(cand) -> float:
    w = cand.get("width_kev")
    if _isnum(w):
        return float(w)
    g = sum(abs(float(ch.get("gamma", 0.0))) for ch in (cand.get("channels") or []) if _isnum(ch.get("gamma", 0.0)))
    return g / 1e3 if g > 0 else -1.0


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _nuc(z, m):
    a = int(round(float(m)))
    if z == 0 and a == 1:
        return "n"
    sym = SYMBOLS[z] if 0 <= z < len(SYMBOLS) else f"Z{z}"
    return {(1, 1): "p", (1, 2): "d", (1, 3): "t", (2, 4): "a"}.get((z, a), f"{a}{sym}")


def write_job_script(directory, spec: FitSpec, cfg: Optional[dict], name="run_crc_drive", overwrite=False, max_minutes=600) -> str:
    """``<dir>/run_crc_drive`` from ``templates/run_crc_drive.csh``: engine guard from campaign.json (or spec.engine before init),
    one leg per job, self-resubmission on CONTINUE."""
    import getpass
    from . import enginepin
    path = os.path.join(directory, name)
    if os.path.exists(path) and not overwrite:
        return path
    tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "run_crc_drive.csh")
    rec = (cfg or {}).get("engine")
    if not rec:
        eng = spec.get("engine") or {}
        rec = dict(azure2_root=eng["azure2_root"], so_md5=eng["so_md5"]) if eng.get("so_md5") and eng.get("azure2_root") else None
    parent = os.path.basename(os.path.dirname(os.path.abspath(directory)))
    reaction = parent if "+" in parent else os.path.basename(os.path.abspath(directory))
    slots = int(spec.get("nshards") or (cfg or {}).get("nshards") or 8)
    text = (open(tpl).read()
            .replace("{email}", f"{getpass.getuser()}@nd.edu")
            .replace("{jobname}", "drive_" + reaction.replace("+", ""))
            .replace("{campaign_dir}", os.path.abspath(directory))
            .replace("{slots}", str(slots))
            .replace("{max_minutes}", str(int(max_minutes)))
            .replace("{engine_guard}", enginepin.guard_lines_csh(rec))
            .replace("{pythonpath}", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, 0o755)
    return path


def main_cli(a) -> int:
    """Dispatch of ``rmfit <dir> drive ...`` (called by rmfit.cli before a Campaign is opened: the build phase has none)."""
    if getattr(a, "reset", False) and os.path.exists(os.path.join(a.campaign, STATE_FILE)):
        bak = os.path.join(a.campaign, STATE_FILE + "." + time.strftime("%Y%m%d%H%M%S"))
        os.replace(os.path.join(a.campaign, STATE_FILE), bak)
        print("drive state reset; previous state kept as", bak)
    try:
        d = Driver(a.campaign, base=getattr(a, "base", None), sav=getattr(a, "sav", None), local=getattr(a, "local", False))
    except DriveStop as e:
        print(f"{e.status}: {e}")
        return 2
    if getattr(a, "state", None):
        if a.state not in STATES:
            print("unknown state", a.state, "; states:", " ".join(STATES))
            return 2
        d.state["state"] = a.state
        d.state["status"] = "CONTINUE"
        d.save()
        d.log(f"state set to {a.state} by --state")
    if getattr(a, "write_job", False):
        print("job script:", write_job_script(d.dir, d.spec, d.campaign.cfg if d.campaign is not None else None, overwrite=True,
                                              max_minutes=getattr(a, "max_minutes", 0) or 600))
        return 0
    status = d.run(max_minutes=float(getattr(a, "max_minutes", 0) or 0), dry_run=getattr(a, "dry_run", False))
    print(f"DRIVE_STATUS: {status} state {d.state['state']}")
    return 0 if status in ("CONTINUE", "DONE", "WAITING", "STOP") else 1
