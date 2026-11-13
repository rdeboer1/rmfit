---
name: rmfit-campaign
description: The rmfit process for global R-matrix fitting with AZURE2 -- start a campaign on any reaction, drive or resume one, use idle time while jobs run for input-file / data audits and literature review (sharded pyazr evaluation, bound-tightening polish, interference-sign rounds, level add/remove rounds, dataset-off diagnostics, ledger + STATUS.md), judge results, export for GUI review, and refine the method. Use whenever the task mentions rmfit, a campaign directory, STATUS.md, sign rounds, a tightening polish, a level-add test, fitting a new reaction "the rmfit way", or continuing a fit that a previous session left running on the cluster.
---

# The rmfit process

`rmfit` (`/groups/rdeboer1/user/rdeboer1/R-matrix/rmfit/`, README there) does what an
evaluator does by hand -- polish, flip interference signs, add or remove levels, switch
suspect data sets off -- as resumable steps that a script runs on one cluster node and a
fresh session can pick up from `STATUS.md`. It is not installed as a package:

```bash
export PYTHONPATH=/groups/rdeboer1/user/rdeboer1/R-matrix
python3 -m rmfit.cli <campaign_dir> <command> [options]
```

Read this file top to bottom before the first command on a new reaction; for resuming a
campaign, "Read the state" and "The loop" are enough. Refinements go in the log at the end.

## 1. Read the state, never recompute it

A campaign directory carries everything a fresh session needs:

- `STATUS.md` -- best verified objective per structure, recent rounds and log lines.
  Regenerate with `status`; `status --json` for a compact dump.
- `readme` -- the lab notebook (rmfit appends one paragraph per round; add your own
  with `log "..."`). Archive convention: read it before touching anything.
- `campaign.log` -- every line the driver printed; `rmfit_sge.log` / `rmfit_*.log` --
  cluster job logs.
- `ledger.sqlite` + `candidates/*.npz` -- every candidate vector and score. The
  incumbent is the best candidate with a `verified` score (a fresh single-session
  evaluation of the full model). Sharded numbers rank; verified numbers are reported.
- `campaign.json` -- base model, engine flags, shard count, bounds policy, search config.
- `<reaction>.azr` + `.sav` -- the GUI-reviewable export of the incumbent.
- `variants/` -- shard files, window models, with/without-level files (disposable).

`qstat -u $USER` first: one campaign command at a time per directory (they share the
ledger and `variants/`). The login node is for `status`, `report`, `log`, `export`,
short tests (<= 6 workers, <= 30 min). Everything else runs as a job.

## 2. Starting a campaign on a new reaction

Prerequisites (do these in the reaction's fit directory, not in the campaign):

1. A `.azr` that opens in the GUI, with `data/`, an `output/` directory, and a `readme`.
   Know the CLI-mode flags this reaction uses (`--use-brune`, `--ignore-externals`,
   `--no-long-wavelength`, ...): they are not in the `.azr`, they vary per reaction
   (`~/R-matrix/CLAUDE.md`), and rmfit needs them as `--flags` JSON.
2. Reproduce the last finished fit before building on it: load its `param.sav` by name
   (`pyazr`), confirm the objective matches `chiSquared.out` (chi2 + norm penalty), then
   bake it into a clean file (`rmfit.engine.bake`) and check it with the CLI in mode 1
   with a blank external file. Never trust a bake that was "verified" with the `.sav`
   as the external file (that overrides `<levels>`), and never use parameters from a
   running or crashed fit -- only the last completed one. Purge inactive level lines.
3. Merge any new data sets onto the baked file (`AzrModel.add_data_segment`), capped
   at the energy range the level scheme covers (`set_segment_energy_range`), with
   normalizations free and a systematic error that reflects the paper. Look at every
   new file: a single negative or spiked cross section can dominate the objective.
4. Record all of that in the reaction directory's `readme`.

### First fits: the build phase of `rmfit drive` (DeBoer's procedure of 2026-10-25, encoded 2026-11-08/09)

DeBoer's instruction of 2026-10-25 ("fix one representative data set's norms ... allow the lowest l channels for each
particle pair to vary ... start at low energy and polish one level at a time ... I wouldn't try a real fit until you have
reasonably good starting parameters"; the full quote, the procedure as first written and the 10B+α stage-1 evidence are
in HISTORY.md, "Relocated from SKILL.md" of 2026-11-10) is the build phase of `rmfit drive` (section 3a).  One line per
item, with the state that enforces it:

1. **Fix the scale with one representative data set** -> `SCALE_ANCHOR` (spec `data_sets[].role`: `anchor` = norm fixed at
   the nominal, `free` with `prior_sigma`; `drive.Driver._s_scale_anchor`).  Why: with every norm free, 10B+α stage 1 traded
   missing strength for norms of 0.38-0.68 (`10B+a/10-25-26_rmfit_stage1`).
2. **Seed the lowest-L channel of every pair on every level** at `model.seed_frac` (0.01) γ_W, placeholders for free widths
   at exactly zero, photon channels at `model.photon_seed_ev` -> `SEED_CHANNELS` (`_s_seed_channels`).  Ran: 12C+p L3 demo 3,
   2026-11-10, 20 background channels seeded, 7.59 M -> 64,615.
3. **Every channel that opens inside the fit range is in the model** -> `PAIR_COMPLETENESS` lists the ENSDF states of the
   residual nuclei below the window top that have no pair (`_s_pair_completeness`) -- it REPORTS; the pair is still added by
   hand (builder `11B+a/10-27-26_HE_claude/model/add_pairs_he.py`).  Never cap a data window at a threshold instead
   (DeBoer 2026-10-30, ELBE ¹⁴N+n total capped at 5.1 MeV for want of an n₄ pair; HISTORY.md).
4. **Level by level, from low energy up** -> `LADDER` (`model.ladder_Ex`; skipped without it -- not exercised on any campaign yet).
5. **Then add levels where a resonance has no known level** -> `CANDIDATES` (ENSDF broad first, every entry with a
   `hypothesis`) and, inside the loop, `LEVELSCAN` / `STRUCTURE_ADD` (section 3a).
6. **Only then a global fit** -> `INIT` (`Campaign.init --spec`, baseline verified, engine pinned).

Re-evaluation DeBoer asked for (2026-10-25, "RE-EVALUATE LATER"): items 1, 2, 5 and 6 ran end to end on the 12C+p L3 demos
(section 7); 3 and 4 only report.  A campaign initialised before the drive (`init` first, as the bench does) skips 1-2:
roles and seeds belong before `init`.

Then, in a new dated campaign directory (`<reaction>/<M>-<D>-<YY>_rmfit_campaign/`):

```bash
mkdir <dir> && cp <base>.azr <dir>/ && cp -r data <dir>/data && mkdir <dir>/output
python3 -m rmfit.cli <dir> init --base <dir>/<base>.azr [--sav <base>.sav] --nshards 24 \
    --flags '{"use_long_wavelength": false, "ignore_externals": true, "use_brune": true}' \
    --policy '{"theta2_cap": 1.0, "bg_theta2_cap": 3.0, "bg_energy": <Ex above the data>, "e_window": 0.3, "norm_range": [0.2, 5.0]}' \
    --search '{"top_k": 6, "pairs_per_group": 4, "stage1_nfev": 30, "stage2_nfev": 60, "union_nfev": 100}'
```

`--flags` is passed straight to `pyazr.azure2()`, so the parametrization is chosen there:
`"use_brune": true` (Brune, the archive default), `"use_park": true` (Park: the fit vector
holds the observed reduced width amplitudes, `Gamma = 2 P gamma^2`; see the AZURE2 skill's
"Park's parametrization"), `"use_brune": false` (standard Lane-Thomas). One basis per
campaign -- the ledger's vectors, `.npz` snapshots and `.sav` companions are all in it.

Optional `--objective JSON` (campaign.json `objective`, deBoer et al. 2017 Sec. on fitting):
`{"dataset_weight": "reduced", "dataset_key": "file", "loss": "sivia"}`.
`dataset_weight: reduced` is the reduced-chi-squared method (every data set's chi-squared
divided by its number of points, rescaled by N/K so the objective keeps a chi-squared
magnitude; penalty rows unweighted) -- it stops a large set with small errors from
dominating; `loss: sivia` replaces chi-squared by Sivia's broader PDF,
`-2 log[(1 - e^{-R^2/2})/R^2] - 2 log 2` (~R^2/2 for small residuals, ~2 log R^2 for
outliers: outliers are down-weighted as if their error bar were inflated). The Sivia loss
is applied to residuals *standardized by each data set's reference chi2/N* (`loss_scale:
dataset`, scales computed by `init` from the plain baseline and stored in campaign.json):
without that, on a model with chi2/N ~ 20-300 every point sits in the logarithmic tail,
the data lose ~10x their weight against the quadratic norm penalties and the fit drifts
(13C+a, 2026-09-08: plain chi2 701k -> 1,190k in one polish, MANA abandoned, norms snapped
to nominal). Both methods are "statistically incorrect but useful when error bars are
underestimated". The objective
is a property of a campaign: candidates verified under different objectives are not
comparable, so a change of objective means a new campaign directory (seed it with the
previous export). `REPORT.md` and `segment_scores` keep the plain per-dataset chi-squared
whatever the objective. Verified in `rmfit/tests/test_objective_13n.py`.

`init` verifies the baseline (one full-model evaluation), registers the structure,
writes `STATUS.md` and the job script `run_crc_rmfit` (24-core `long` node, mails
`$USER@nd.edu`, `-m abe`). Re-running `init` keeps an existing config unless new values
are given. Policy meanings: `theta2_cap` is the Wigner-limit box for physical levels,
`bg_theta2_cap` for background poles (levels with Ex >= `bg_energy`, whose energies stay
fixed) -- 3.0 is a starting guess, not a physics default: check where the baseline's
background amplitudes already sit (`init`'s cap audit) before trusting it; 12C+alpha
elastic needed ~100 (see HISTORY.md, 2026-09-30); photon channels have no Wigner limit, so the theta2 caps never touch
them: `photon_width_max_ev` (1e4) and `bg_photon_width_max_ev` (1e5) cap |Gamma_gamma| of physical levels and background
poles instead (2026-11-10: a from-scratch 12C+p background pole had polished to 1e12 eV; generous stops, not Weisskopf
limits -- set them per reaction, 0 = unbounded); `e_window` is the energy freedom of a level per polish (MeV); `norm_range`
multiplies the nominal normalization. `narrow_window` (optional, e.g.
`{"gamma_kev": 5, "factor": 3, "min_kev": 1}`) keeps a level whose free partial widths sum
to less than `gamma_kev` within ±max(`min_kev`, `factor`·Γ) of its current energy instead of
±`e_window`, so a polish cannot carry a narrow level away from its peak (the 13C+a 9/2+
drifted 180 keV in one tightening polish). Shard count = cores; sharding is exact
(chi-squared is additive over segments), so more shards only buy speed.

Cost check on a new model (`campaign.log` after `init`): one sharded objective should
be a few seconds and a Jacobian tens of seconds. If a segment with target-effect
convolution dominates (as Cierjacks did on 13C+a), rmfit folds it itself (`model.ConvSpec`);
composite "sum" segments are allowed as convolution pieces.

### 2b. Spec, audit, decisions (2026-11-07; Phase 1 of R-matrix/rmfit/DESIGN.md)

Before `init`, write the campaign's **spec** (`spec.json`, template `rmfit/templates/SPEC_TEMPLATE.json`, schema in
`rmfit/spec.py`): every data set with its role (`anchor` = norm fixed at the nominal; `free` with `prior_sigma`; `excluded`
with the reason; `screen`), the fit window, the frozen block, the pairs that must exist, bounds / objective / search, what the
driver may do on its own (`pre_authorized`: `adopt_level` true / false / rules, `flip_adopt`, `dataset_off_adopt`, ...),
the stop rules and the **standing decisions** with their owner and date.  Then:

    python3 -m rmfit.audit <base>.azr --out AUDIT.md       # pre-flight, no engine session: zero free widths, 1 keV merges,
                                                           # nominal norms != 1, normError as a FRACTION, FLAG columns as
                                                           # errors, tiny errors, duplicates, spikes, thresholds, <targetInt>
                                                           # on test segments, legacy .sav names, output path, engine pin
    python3 -m rmfit.cli <dir> init --base ... --spec spec.json   # flags/policy/search/objective/nshards from the spec unless
                                                           # given; HIGH disagreements with the .azr refuse the init
    python3 -m rmfit.cli <dir> spec check                   # any time: SPEC_CHECK.md; spec render -> SPEC.md; audit -> AUDIT.md

A HIGH audit finding is fixed (or recorded as accepted in the spec's standing decisions) before the baseline.  During the
campaign, anything the spec does not answer goes to **`DECISIONS.md`** (`rmfit decisions` lists, `rmfit decide D-003
"adopt" --by DeBoer` answers); a level add whose `accept` the spec does not pre-authorize is recorded as `accept-pending`
with a queued decision and is NOT adopted (the old automatic adoption only applies to campaigns without a spec).  Spec
drafts to copy from: `10B+a/11-6-26_s5_highE/spec_draft.json`, `13C+a/11-06-26_merged_regionD/spec_draft.json`.

The three idle-time reviews of section 3b are generated, not hand-written, since 2026-11-07:

    python3 -m rmfit.cli <dir> audit --kind all            # audits/{input,data,literature}/PROMPT.md + empty FINDINGS.md
    # hand each PROMPT.md to a background subagent (Agent tool, a cheaper model, at most three at once); it writes FINDINGS.md
    python3 -m rmfit.cli <dir> audit --findings            # unverified (candidate) rows of every FINDINGS.md
    python3 -m rmfit.cli <dir> audit --status data 1 confirmed --note "line 4007 checked"   # after YOU verified it against the files

The prompt carries the segment table, the active data files, the machine AUDIT.md findings, the spec's data-set roles and
standing decisions, the answered DECISIONS and the readme head, so the subagent does not re-report what is known; its table
has a `Status` column that only the driving session changes (candidate -> confirmed | rejected | decision).  Rules of 3b
still apply: findings are candidates until verified, nothing in a fit changes on the strength of a report, data treatment
is the evaluator's.  Without a campaign: `python3 -m rmfit.audit <model>.azr --kind data` writes `audits/` next to the model.

## 3. The loop

Every step is a job (`qsub -v RMFIT_CMD="..." run_crc_rmfit`, or `-hold_jid <id>` to queue
behind the previous one). Every step ends by rewriting `STATUS.md` and appending to the
readme; read both before the next step.

| step | command | purpose | when done |
|---|---|---|---|
| 1 | `polish --nfev 150 --tighten` | walk amplitudes beyond the theta^2 caps into the box (x10 stages), then converge | all theta^2 inside the caps; gain < 0.05% per stage |
| 2 | `round --rounds 2` (repeat) | interference-sign rounds: screen every canonical flip (singles, exposure pairs, same-channel pairs, optional channel patterns), polish the top-k sign-locked then released, greedy union, verify | improving-on-screen and accepted counts fall round over round; stop after two rounds with nothing accepted |
| 3 | `polish --nfev 150 --shifts-free` | warm-start continuation with energy shifts free | gain < 0.05% |
| 4 | `structure add --candidate i` (per entry of `candidates.json`) | forward addition: window J^pi scan at pinned energy, pinned then released full-model polish, control polish without the level, classify, adopt if accepted | all candidates classified |
| 5 | `structure dataset-off --file <substr>` for the worst chi2/N sets | deactivate + refit; reports the extra recovery of the *other* sets beyond the set's own chi2 (the Botek test) | a table for the evaluator |
| 6 | `round --rounds 2` after any structure change | signs may change with the structure | as in 2 |
| 6b | `crossover --donor <cid> [--donor-dir <other campaign>]` | basin crossover: apply another good fit's sign pattern per channel / J^pi group / all and polish every proposal; use it whenever the ledger (or a sibling campaign, e.g. a recovery benchmark) holds a second verified basin | every donor pattern polished; verified union |
| 7 | `review [--grid-check]`, `export`, then GUI review | bake the incumbent to `<reaction>.azr` + `.sav`, verified in a fresh process | CLI mode 1 with the `.sav` as external file reproduces the totals |
| 8 | `uq --uq uq.json --nprocs 4 --threads 6` (queue; section 3d) | uncertainty quantification of the incumbent: export, saturated poles held, Laplace covariance, NUTS chains, R-hat / ESS / divergence gates, linear vs sampled bands -> `UQ.md` | gates PASS; the band table says where the linear band is adequate |

`candidates.json` (write it before step 4): `{"candidates": [{"energy": Ex_MeV, "jpi":
"5/2+" or null to scan, "energy_fixed": true, "channels": [{"pair": n, "L": l, "S": s,
"gamma": width_eV_with_sign}, ...], "source": "...", "note": "..."}]}`. Sources: ENSDF/TUNL
(`pyazr.nds.fetch_levels`), the reaction's literature tables, and residual runs
(`diagnose.residual_runs`) in the fit's worst segments. Omitted channels are seeded at a
small fraction of the Wigner limit.

**Default J^pi of `levelscan` / `structure add` (fixed 2026-11-04).** With no `--jpi` (or `"jpi": null`)
these now use the model's OWN active J^pi groups (`structure.default_jpis`), and any requested J^pi that no
particle pair can couple to raises (`structure.resolve_jpis`; e.g. 1/2+ on 10B+alpha). The log names the
list and warns about any NEW group: its channels are partial waves the model lacks, and their hard-sphere
terms change the elastic channels even at zero width. BEFORE the fix the default was the half-integer
13C+alpha list (1/2+ ... 11/2-), unphysical for integer-J compound nuclei (14N, 16O, 20Ne, ...) without
any warning. **A campaign's `run_snapshot/` copied before 2026-11-04 still has the old default: pass
`--jpi` explicitly there** (e.g. `--jpi 0+ 0- 1+ 1- 2+ 2- 3+ 3- 4+ 4- 5+ 5- 6+ 6-`). In every case, check
the template screen's log line `template screen at Ex ...: incumbent <obj>`: it must equal the
campaign's verified incumbent. Details in the dated entry of 2026-11-04 at the end.

Residual-driven level search (Phase 7, `rmfit levelscan [--ex E ...] [--top K] [--gamma keV]
[--scales 0.5,1,2] [--ex-offsets -0.04,0,0.04] [--jpi ...] [--refit N]`): candidate energies
from the incumbent's residual runs clustered in Ex across segments (plus dispersion-shaped
pairs: two adjacent clusters of opposite sign with the level between them); at each, one
dummy level per J^pi (all of the group's channels, energy free) is appended and every
(J^pi, width partition, sign pattern, energy offset, scale) is evaluated frozen in the
full model, the best `--gn-top` get a GN step on the level's amplitudes + norms, and the
best per J^pi is reported (ledger round kind `levelscan`); `--refit N` sends the top N to
the ordinary level-add refit. Photon channels get a small trial width with both signs.
Validated on 13N: a level removed with the other parameters untouched is found (its J^pi
ranks first, gain ~90% of the loss); after the rest of the model has re-polished without it
the single-level signature is gone (the compensation limit in the plan) and only the refit
of the top candidates can recover it. Template amplitudes are the engine's own conversion
of a tiny reference width scaled by sqrt(Gamma); candidate energies are rounded to 1 eV
before writing (see the AZURE2 skill's add_level gotcha).

Every level test and relocation writes a review figure to `figures/` (data with the
incumbent and the candidate calculation around the energy: excitation functions per
segment, angular distributions for single-energy segments) -- DeBoer's visual check.

Relocation of an existing level (`rmfit relocate --level 9/2+#1 --ex 8.4654 [--window 5]`):
energy kick to `--ex`, then a full re-polish with that level's energy confined to
+-`--window` keV, verified and adopted if it beats the incumbent by tau. Use it for a
narrow level that has drifted from its peak (see `narrow_window` above for keeping it
there afterwards). 13N test: a level shifted by 60 keV comes back and recovers the full
model's objective.

Ordinary additions: `touch <dir>/STOP` ends a `round --rounds N` loop after the current
round; `verify <cid>` re-scores a candidate; `log "..."` appends to the readme;
`report` writes `REPORT.md` (per-dataset chi2/N, theta^2 table, structure decisions).

## 3a. The closed loop: `rmfit drive` (2026-11-08; DESIGN.md Phase 2)

`rmfit <dir> drive` runs sections 2-4 as a resumable state machine instead of a session choosing every step.  It needs
`<dir>/spec.json` (section 2b): the spec's `budget`, `stop_rules` and `pre_authorized` are the thresholds, and anything the
spec does not answer becomes a `DECISIONS.md` entry.

    cp <base>.azr <base>.sav <dir>/; cp -r data <dir>/data; mkdir <dir>/output; write <dir>/spec.json
    python3 -m rmfit.cli <dir> drive --base <dir>/<base>.azr --sav <dir>/<base>.sav --dry-run   # records the base, prints the plan,
                                                                                               # writes run_crc_drive
    qsub <dir>/run_crc_drive                     # one leg per job: states run until DONE / WAITING / STOP or DRIVE_MAX_MIN (600),
                                                 # then the job resubmits itself (CONTINUE)
    python3 -m rmfit.cli <dir> drive --dry-run   # any time: where it is, what comes next, what it waits for (also DRIVE.md)
    python3 -m rmfit.cli <dir> decide D-003 "adopt" --by DeBoer; qsub <dir>/run_crc_drive     # after a WAITING leg
    touch <dir>/STOP_DRIVE                       # stop cleanly after the current state

States: build phase `PIN_CHECK AUDIT REPRODUCE SPEC_CHECK SCALE_ANCHOR SEED_CHANNELS PAIR_COMPLETENESS LADDER CANDIDATES
INIT RECALL` (section 2 prerequisites and "First fits": AUDIT runs the machine checks and then, on a new campaign, writes the
three subagent audit prompts (section 3b) and WAITS for their verified FINDINGS.md -- decision `audit-subagents`, 'done' or
'skip', `pre_authorized.skip_subagent_audits` for fixtures; rows left 'decision' become one wait decision each (2026-11-10:
12C+p demo 1 had fitted a lab-frame error for an hour before the idle-time data audit found it); the archived
chiSquared.out must reproduce, the spec's data-set roles are applied to a working copy `<stem>_drive.azr`, free widths at exactly zero are seeded at `model.seed_frac` (0.01) gamma_W,
ENSDF states of the residual nuclei that open below the window top without a pair are listed, `candidates.json` is built
from ENSDF broad-first when absent -- every candidate needs a `hypothesis`; RECALL (2026-11-09, `structure.recall_levels`)
removes the broadest known levels one at a time and asks the level-add procedure to find them again with no J^pi given --
below `recall_min_pass` every add of the run is queued as a decision instead of adopted), then the loop `TIGHTEN SIGN POPULATION
SHIFTS_FREE LEVELSCAN STRUCTURE_ADD SIGN_POST DATASET_OFF REVIEW EXPORT CYCLE` (section 3 steps 1-7 with section 4's stopping rules: polish rounds
until the gain is below `polish_gain_rel_min` -- size `budget.polish_nfev` to the model, 150 is far too few for 200 free
parameters; sign rounds only once the polish converged (`sign_after_converged_polish`, else they are deferred to the next
cycle: 7Be 2026-11-08, 18 rounds accepted nothing on a moving incumbent -- deferred at most once and never in the last cycle,
after which they run on the unconverged incumbent and the readme says the polish budget is too small: 12C+p L3 demo 3,
2026-11-10, 162 free parameters never converged in 6 x 300 evaluations) and until `sign_rounds_without_accept`; then
POPULATION, the basin-crossing stage (`Campaign.run_population`, CLI `population`): `budget.restarts_per_cycle` sign-perturbed
restarts of the incumbent (random 6-12 high-exposure flips, <= 3 per J^pi, 20 % jitter), each polished sign-locked then
released to convergence in rounds of `restart_nfev` (0 = `polish_nfev`), plus the control, then `crossover_passes` passes of
`crossover` moves from the best member with every other as donor, each pattern polished, the winner polished to convergence
-- judged on polished objectives only; an improvement is a new basin and SIGN_POST finishes its last signs; a round gaining
less than `population_gain_rel_min` switches the stage off until a structure change (`population_rounds_max` caps it).  Why
(7Be benchmark 2026-11-08, bench readme): the sign rounds left a basin 13.5 % above the reference, sign distance 17; the
reference's 17-flip pattern starts at three times the incumbent's objective and polishes down to it, while no single, pair,
channel or group flip gained more than 2.6 even with a 600-evaluation polish -- local proposals do not cross basins, a
population of polished basins and crossover between them does (six restarts + one pass: 6002.6 -> 5325.7); the structure
search per the spec's `structure` section (2026-11-09): candidates broad first -- a known width below `broad_first_kev` (10)
waits until the broad queue and the residual scan are exhausted, then the narrow-alignment phase (`narrow_phase`); when the
broad queue is empty LEVELSCAN (`levelscan_per_cycle`, `levelscan_top`, `levelscan_gamma_kev` null = the run width) screens
the residual-run clusters with one level of every J^pi and appends the best (J^pi, pattern) to `candidates.json` with the
screen as hypothesis and the next two J^pi as alternatives; every add polishes the neighbourhood first (`local_release_mev`,
`local_nfev`); level adds until `level_adds_marginal_in_a_row`, adoption per `pre_authorized.adopt_level`; the Botek test on the worst chi2/N sets, result
recorded, never excluded; review HIGH flags wait for the evaluator; another pass while a cycle gains `cycle_gain_rel_min`
and `cycles_max` allows).  `DRIVE.md` is rewritten after every state; `drive_state.json` is the checkpoint (`--state S`
jumps, `--reset` starts over and keeps the old file).  Engine states refuse the login node (`--local` is for fixtures).

What the supervising session does: read `DRIVE.md`, `STATUS.md`, `DECISIONS.md`, `REVIEW.md`; relay the pending decisions
to the evaluator with the evidence files; `decide`; resubmit.  It does not pick a step the spec answers, and it does not
answer a data-treatment decision itself (section 5).  Limits (2026-11-10): no channel lines or pairs are added automatically (PAIR_COMPLETENESS and SEED_CHANNELS report what is
missing), LADDER needs `model.ladder_Ex`, multi-compound-nucleus models are outside the sign rounds / levelscan, and no live
evaluation has run under it yet -- what has: the 13N fixture (`tests/test_drive_13n.py`, every queue change is rerun there,
~70 min on 3 slots), the bench cases of section 7 and the 12C+p L3 demos (`12C+p/11-10-26_L3_demo4/`, `_demo5/`).

## 3b. While jobs run: audit and read (idle time is work time)

DeBoer, 2026-10-02: "You're spending most of your time thinking about just doing the fit
minimization, but what about spending some of the idle time doing things like checking over the
data and input file for mistakes or looking through the literature to try to identify ways to
improve the fitting technique?" -- and, asked whether this belongs in the process: "add this type
of activity to the skill files so you start doing this type of things for all of our projects."

A polish or a sign round takes hours and needs no attention between milestones.  Whenever a job
is running and nothing is actionable, do NOT just wait for the next log line: run the three
reviews below.  They are read-only, they cost no node, and on 13C+alpha every large gain of the
merged fit came from this kind of work rather than from more minimization (a free unpenalized
normalization on the n-total data, a 2019 data file with statistical-only errors, a width window
that swallowed a neighbouring level, a wrong elastic / inelastic partition that only independent
data exposed).

**When.**  At the first idle window of every campaign, and again whenever data are added, a
structure change is adopted, or a fit stalls.  Mandatory, not optional, when: a fitted
normalization leaves 0.7-1.4; a frozen or pinned part of the model carries a large share of the
objective; two fits of the same data disagree in absolute scale; a level sits at a bound or at a
threshold guard; a new data set is about to enter the fit.

**How.**  One background subagent per review (Agent tool, `model` set to a cheaper model than the
session's so the reviews do not consume the main budget), at most three at a time, each with a
self-contained prompt (paths, file-format facts, what is already known and must not be
re-reported), each writing ONE report into `<reaction>/<M-D-YY>_audit/` next to a `readme` that
quotes why it was run.  The reviews never edit a fit directory, never submit jobs.  A report's
findings are CANDIDATES: verify each one against the files yourself (numbers, line, segment key)
before telling the evaluator, and change nothing in a fit on the strength of a report alone --
data treatment stays the evaluator's decision (section 5).  Worked example with the three prompts:
`13C+a/10-2-26_audit/`.

**1. Input-file audit** (the `.azr` of the current seed):
- particle pairs: mass, charge, spin, parity, excitation and separation energy, radius identical
  on every level line and right against the nuclear data; thresholds reproduce to ~1 keV;
- channel sets: every (pair, L, S) allowed by angular momentum and parity, none missing at low L,
  the same set on every level of a J^pi group;
- levels: same-J^pi pairs within 1.5 keV; free amplitudes that are exactly 0 (they never move);
  levels within 3 keV of a threshold; fixed / free flags against the campaign's rules;
- segments: file exists; entrance / exit keys match what the file holds; energy window against
  the data's range and the exit threshold; isDiff against the angle column and its frame; "sum"
  tails complete for every channel open in the window;
- segment tails: list every segment with tokens after the file name other than `0 0`
  (azure2-eval SKILL, ".azr file anatomy", has the field meanings and an awk one-liner) and
  record which are composite SUM / RATIO segments and which are UPOS (secondary-gamma)
  segments. A UPOS segment's observable is the secondary gamma, not the primary cross section,
  and no extrapolation reproduces it, so curves, scans and post-hoc tests on it must run in data
  mode on a pseudo-data grid (12C+alpha 2026-10-05: 39 UPOS and 138 RATIO segments in one model);
- normalizations: every `varyNorm 1` with `normError 0` is a FREE UNPENALIZED norm -- list them
  with their fitted values and ask whether each is intended; list fitted norms outside 0.7-1.4;
  check every norm / shift setting against the evaluator's recorded decisions;
- `<targetInt>` keys bind to the intended segments; in sharded runs a convolved segment must be angle-integrated or at
  ONE fixed angle (minA == maxA; fixed-angle conv pieces since the 2026-10-15 entry); an angular distribution with a
  `<targetInt>` line still needs a single session.

**2. Data audit** (every file of an active segment):
- integrity: non-numeric rows, zero or negative values or errors, duplicated rows;
- units and scale: ratios between overlapping sets of the same reaction, band by band; an
  absolute anchor (a total cross section, a unitarity constraint) compared with EVERY independent
  measurement of the same quantity, not only the one in the fit;
- frames: lab energy of the right projectile (test against thresholds), lab vs c.m. angles and
  cross sections against the segment type; a converted file is cross-checked by evaluating it
  frozen in both frames with identical errors (the chi-squares must agree exactly);
- uncertainties: statistical-only where the source gives a systematic one; an advertised error
  floor that does not hold; implausibly small or constant errors;
- double counting: the same measurement under two names or in two overlapping windows;
- energy scale: for a set with narrow structure, run a post-hoc shift scan on the frozen model
  curve BEFORE any refit (none / constant / a+b*sqrt(E) / a+c*E, norm re-optimized; azure2-eval
  SKILL, "Fitting a data set's energy scale"); a shift freed afterwards must be SEEDED at the scan
  optimum -- MIGRAD from zero stalls in a local minimum next to zero (12C+alpha 2026-10-07: -193
  from zero vs -795 seeded);
- against the source: re-fetch the EXFOR entry (`pyazr.nds`, skill `nds-explorer`; fallback in
  `13C+a/10-2-26_n16O_exfor/readme`) and compare values, units and error columns row by row.

**3. Literature review**: earlier evaluations of the same compound system (what data, channels,
radii, energy limits, how they treated normalizations and backgrounds), measurements of channels
the fit does not yet constrain, and method papers on the specific difficulty the campaign is
stuck on.  Every claim carries a citation; a paper that could not be read is listed as such;
nothing is quoted from memory.  The output is a short list of actionable ideas, each with a cheap
test, not a survey.

**Cheap in-session checks that belong to the same habit** (minutes each, no node):
- decompose a summed observable into its partial cross sections by extrapolation and compare each
  partial with independent data -- a total can be right with the wrong partition;
- the clip check before every qsub: sanity + bounds + clipped objective of the seed under the
  policy the job will use (`13C+a/9-30-26_merged/clip_check.py`); a start-up clip that costs more
  than a fraction of a per cent means a window or a cap is wrong;
- a coverage plot of what EXFOR holds against what the fit uses
  (`13C+a/10-2-26_n16O_exfor/plot_coverage.py`).

## 3c. A structure you can see but no search finds: the width-floor recipe (13C+α, Ex 9.4 MeV, 2026-10-05/07)

The evaluator pointed at a broad backward-angle (α,n₀) resonance near Ex 9.4 MeV ("see segment 25") that every tool had declared
null: levelscan at 9.47/9.51/9.56 (all J^π, 50-400 keV), sign rounds over the groups there, a seed/re-partition test, and the first
local-release level add (all 11 J^π: every candidate collapsed to 11-183 eV and came out "marginal", best +239).  The level that was
finally accepted (1/2⁻, 9.348 MeV, Γ_n0 198 keV, Γ_α0 15 eV, +10,950 vs its control) had been within reach of the very first test: it
was lost because a released polish lets a broad seed shrink to nothing while the neighbours re-absorb the misfit, and a collapsed
candidate is then scored as "nothing there".  The recipe that found it:

1. **Localise and characterise the deficit before fitting anything.**  Band map of χ² per 0.2 MeV of Ex by data set (from the
   incumbent's per-point residuals, e.g. a summary page's curves json), then per 10 keV with the MEAN PULL per band and per angle group.
   A broad deficit shows as the model under the data by 2-3 σ at EVERY angle over ≥ 50 keV with the same pull sign (9.74-9.78 here;
   at 9.4 it was the backward angles 0.35-0.71 of the data over 400 keV).  A narrow spike (two 10 keV bands, pull changing sign) is a
   lineshape / resolution question, not a level search.  Write the anatomy into the readme first.
2. **Width-floor level add, every J^π, with the local release and a same-budget control.**  `structure add --local-release 0.5
   --local-nfev 80 --pinned-nfev 60 --nfev 150` with `total_width_floor_windows: [[E-0.0005, E+0.0005, 100000]]` (a floor on the
   TOTAL width over the level's open channels, 2026-10-12 -- NOT the older per-channel `width_floor_windows`, which forces the width
   into one named channel; see HISTORY.md, 2026-10-12) and `setenv RMFIT_SEED_OMITTED 1` so every open channel of the group exists
   and can take width; seeds Γ_n0 150 + Γ_α0 30 keV in the lowest L; one campaign directory per J^π (an accepted level is
   adopted into its base, so groups must not share one), three groups per node job.  The floor is one-sided on the sign the amplitude
   starts with and never above 0.95 of the cap; it is skipped for an amplitude that is exactly 0 (the control's "level off" state --
   the first run had the control carrying the floored level, start 42k too high; a control whose start differs from the incumbent is
   broken, check it before reading any delta).  Verdict = delta vs the control, tau from k; "at_bound" empty at the end means the data,
   not the floor, chose the width.
3. **Cross-checks that make the verdict believable.**  (a) The same recipe on the OTHER plausible hypotheses: widen the existing
   neighbour instead (a floor on its width: here the 3/2⁻ 9.36 → pinned at 400/500 keV, +2,349/+9,938 = rejected); (b) a data-only
   window multi-start on the complaining data set (`10-5-26_an0_only`: ±0.5 MeV window, norms fixed, random a₀ sign patterns, 11 J^π
   with a level, 250 evaluations each, ~1 h on one node) -- a SCREEN that must agree on J^π and width (it did: 1/2⁻ ≈ 5/2⁻ tied; the full
   data broke the tie 1/2⁻ +10,950 vs 5/2⁻ -14,965), never a start vector (transplants came back +3k..+83k, see the 10-06 entry);
   (c) per-dataset and per-angle attribution of the gain (here 72 % ND 2021, all at the backward angles -- the symptom the evaluator named).
4. **Full free refit of the accepted fit** (every parameter, no floor, 400 evaluations): the level must hold on its own (it did:
   9.3474 / 198.8 keV / 16 eV, objective -312, nothing else moved) -- then that export is the incumbent.
5. **Propagate.**  Any model that freezes this block (the merged fit's Ex < 10) gets a NEW seed with the refreshed levels
   (10-6-26_merged_refresh/refresh_frozen.py: copy energies and channel gamma fields by (J^π, energy order), add new levels fixed, keep
   fixed flags, partial .sav, frozen check, recentre the policy windows) and a refit; the splice cost is normal (0.25M here) because
   the free levels above the cut were tuned to the old block.
6. **Then the next region**, by the band map, with the SAME recipe -- and expect most J^π to be rejected quickly (the high-spin ones by
   10⁴-10⁵: a 100 keV floor is above their Wigner limit); a candidate that passes on a data set other than the one you aimed at still
   counts (DeBoer 2026-10-07: "our goal is to fit the entirety of the data sets").

Cost: 11 J^π = 4 node jobs × 6-8 h; the anatomy and the window screen are login-node work.  Full narrative: 13C+a/10-5-26_ex94_floor/readme
(and 10-3-26_ex94_local, 10-5-26_an0_only, 10-5-26_an0_reconcile, 10-6-26_32m_widen, 10-6-26_lowE_12m_refit, 10-6-26_merged_refresh).

## 3d. Uncertainty quantification: `rmfit uq` (2026-11-10; DESIGN.md Phase 4)

`rmfit <dir> uq [--uq uq.json|JSON] [--nprocs N] [--threads T]` (as a job: `qsub -v RMFIT_CMD="uq --uq uq.json --nprocs 4
--threads 6" run_crc_rmfit`; the drive runs it after its last cycle when `spec.uq.enabled`) is `rmfit/uq.py`: EXPORT the
incumbent to `uq/<name>.azr` + `.sav` -> SETUP (Park's J of every level from a Park session on the same file; levels with
J < `j_saturated` 0.01 are saturated -- their widths sit at the channel-radius ceiling, the data do not set them, the Brune
Hessian is singular along them -- and are HELD; Laplace covariance of the sampled block) -> SAMPLE (`pyazr.sampling` NUTS,
`chains` x (`warmup` + `draws`), dense metric from the Laplace covariance, `target_accept` 0.9) -> GATES (split R-hat <=
1.01, min bulk ESS >= 400, divergences <= 1 %, E-BFMI >= 0.3; a failure re-runs with 2x the draws once, then it is a
decision `uq-gates`) -> BANDS (the spec's `uq.bands` grids or the model's own `<segmentsTest>` energy scans: the LINEAR
band from the Laplace covariance on the free R-matrix block, the same x sqrt(chi2/nu) printed beside it and NOT adopted,
and the SAMPLED band from `band_draws` posterior draws, percentiles 2.5/16/50/84/97.5) -> `UQ.md`.  Norms are sampled
(the full posterior) unless `sample_norms` is false; `uq.priors` {engine name: [mean, sigma]} adds Gaussian priors beyond
the objective's own penalties.  BOUNDS (2026-11-12): the chains run inside the campaign's theta^2 box -- every sampled
particle amplitude at |gamma| <= sqrt(cap) gamma_W with the policy's cap for its level (`bounds: "policy"`, the default;
NUTS on x = c + h tanh(u) with the Jacobian, draws stored in x, the metric in u from the Hessian of -log p(u) at the
mode -- not the Laplace / (dx/du)^2, which froze the d+t chains, job 1731435), because the data alone need not bound a background
pole: on d+t with no box width_2_2 left its Wigner limit in 67 % of the draws and emcee's acceptance fell to 0.11
(3H+d/11-12-26_uq).  `bounds: "none"` lifts it; `theta2_cap` gives one cap to a bare .azr + .sav that has no policy.  The
box is the campaign's (the polish ran in it); a different prior on an amplitude is the evaluator's.  Read it as: half-width / linear sigma near 1 and a small median offset = the linear band
is adequate there; a ratio well above 1 or an offset of a sigma = the posterior is skewed along a direction the Jacobian
misses (a saturating width, a sign-ambiguous amplitude).  Everything is conditional on the model and the spec's data
decisions.  Cost: a gradient is ~2 objective evaluations; 7Be (195 free) ~25-50 gradients per draw.  Pitfalls: a script
that spawns the chains must guard `if __name__ == "__main__"` (spawn re-imports it; without the guard it recurses);
`pyazr.bands.extrapolation_bands` opens its session with pyazr's DEFAULT flags, so `uq` trims the model and opens the
extrapolation session with the campaign's flags itself.  Validation: section 7.

## 4. Judging results

- Acceptance thresholds scale with s^2 = objective / N because errors are
  underestimated (s^2 ~ 15-20 on 13C+a). A flip needs a verified gain
  >= max(0.1% obj, 5 s^2 ln N) *beyond the control polish of the incumbent* (the
  incumbent keeps improving on its own by hundreds per polish; flips are credited only
  with what they gain beyond that). A level needs >= max(s^2 k ln N, 0.2% obj), theta^2
  inside the caps, an energy that stays in its window, and a redistribution ratio
  rho <= 0.5 (rho = chi2 lost by some data sets / gained by others).
- Trial outcomes: accept / marginal / worse / reverts (the sign walked back in the
  released polish; never retried on that structure) / drift (the sign walked back but
  the polish found a vector better than the control by >= tau: kept, joins the union)
  / unphysical / collapse (widths -> 0) / blowup / relocated (energy left its window)
  / live-harmful / crashed.
- Convergence of the sign search: improving-on-screen counts decay geometrically
  (archive history 16 -> 4 -> 3 -> 1). Two rounds without an acceptance = converged for
  the present structure.
- `sanity` flags theta^2 over the cap, |E| > 60 MeV, norms outside (0, 100), a
  non-finite Brune transform, and parameters at a bound (listed in the readme entry).
  Any |value| > 1e6 or |E| > 1000 MeV means catastrophic cancellation in
  total-cross-section chi2, i.e. a fake improvement.
- Read `REPORT.md`'s per-dataset table after every structure step: a data set whose
  chi2/N is far above the rest, or whose removal recovers more than its own chi2 in
  the others, is an evaluation question (normalization, energy calibration, resolution),
  not a fitting question.
- **Run `rmfit <dir> review` before judging a fit by eye** (2026-11-07, DESIGN.md 1.3): `REVIEW.md` + `figures/review_*.png`
  hold the checks DeBoer makes in the GUI -- per-point summary per data set (fraction within 1 / 2 sigma, median |r|, how
  many points carry half of the chi2 and where), the top chi2 carriers, every norm against its segment's own optimum n*
  (a free norm on the other side of 1 from n* was pulled by a group / covariance / prior), n* trends with angle or energy
  inside one experiment (a shape problem dressed as a scale), residual runs with the level inside or missing,
  residuals that vanish when blurred over 50 keV (the fit follows the average), MeV-wide levels spanning visible
  unfitted peaks, a zigzag of the calculated curve (bumpiness), levels narrower than 2 % of the data spacing under a
  target integration (`--grid-check` re-scores on a converged grid), levels seen by one data set only.  Engine-free on
  any finished CLI run: `python3 -m rmfit.review <file.azr> [--output DIR]`.  Flags are candidates, not verdicts: look
  at the figure before writing a readme line, and leave data treatment to the evaluator.
- **Check every fitted norm against the set's fit/data ratio** (the norm multiplies the data and its errors, so at a
  sensible minimum fit/data ≈ norm). A norm that moved the other way (10B+α stage 1b, 2026-10-25: June ND5U25 norm 1.32
  with the fit at 0.64 of those data) points to a data-scaled `vector` in that set's covariance acting as a hidden
  normalization with Peelle's bias, not to an rmfit bug. Scan that one norm with the plain and the covariance χ²; the
  fix and the numbers are in the `data-covariance` skill's Traps (analysis variants as `relvector`). Also distrust norms
  sitting on the `norm_range` bounds while χ²/N ≫ 1: the priors are negligible there and the norms absorb shape misfit
  (see "First fits" in section 2).

## 5. What the human decides

rmfit hands these to the evaluator rather than deciding them:

- normalization scale and systematic error of a new data set (and any rows dropped);
- an angle- or energy-dependent trend in fitted normalizations (the norms absorb it
  silently);
- whether a data set that distorts the rest stays in the fit;
- the energy range of the model (data above the level scheme's range are capped, not
  fitted);
- accepting a level whose gain is statistically clear but whose J^pi or energy
  contradicts the literature;
- error inflation (the Birge factor sqrt(chi2/nu) that `UQ.md` prints beside the plain band), priors on R-matrix
  parameters, and what to do with chains that fail their gates after the automatic rerun (`uq-gates`).

The GUI review: `printf '1\n<reaction>.sav\n\n7\n' | AZURE2 <flags> --no-gui --no-readline
<reaction>.azr` fills `output/` with the fit (the `.sav` carries the fitted norms), then
`AZURE2 <reaction>.azr &` on an X display.

## 6. Diagnostics and benchmarks

- `keys.canonical_signs(x, keys, fixed)`: the sign pattern modulo the exact symmetries
  (all amplitudes of one level; all amplitudes of one particle pair in every level;
  fixed nonzero amplitudes tie a level's gauge to a pair's). Only valid for particle
  channels -- see limits.
- `keys.sign_distance(x1, x2, keys, fixed)`: the minimal number of flips between two
  patterns modulo those symmetries.
- `perturb --out <dir> --flips 8 --jitter 0 --ekick 0 --polish-nfev 150`: the recovery
  benchmark. Flips high-exposure signs of the incumbent, polishes to a genuine worse
  minimum in a sibling campaign directory, and records the target; every later
  verification there logs the sign distance and the gap. Success = back to the target
  within 1e-4. Run it once per reaction before trusting the method there.
- The oracle script (`13C+a/9-6-26_rmfit_recovery_signs/oracle_patterns.py`) applies a
  known target's sign pattern per channel / per group / all at once and polishes: it
  separates "finding the pattern" from "reaching the basin from the pattern".
- `diagnose.dataset_table`, `theta2_table`, `residual_runs`, `compare` feed `report`.
- **Bench suite (2026-11-09, DESIGN.md Phase 3.1)**: `python3 -m rmfit.bench list|score|run` on `rmfit/bench/cases/<name>.json`.
  `score` applies DeBoer's recovery yardstick from the ledgers alone (data chi2 <= reference, objective within 0.5 %, zero wait
  decisions, no HIGH/MEDIUM review flag the reference lacks; 'exact' 1e-4 as a secondary column) and appends to `bench/results.tsv`;
  `run` writes the SGE job (reference init, `perturb`, spec, `drive`).  Supersedes "success = within 1e-4" above for drive runs: the
  7Be post-mortem showed 1e-4 selects one of two near-degenerate background configurations.

## 7. What the benchmarks show, and the known limits (November 2026)

The September list and the 2026-11-07 note that replaced it are in HISTORY.md ("Relocated from SKILL.md", 2026-11-10).
Numbers below are `bench/results.tsv` rows (DeBoer's recovery yardstick, section 6) and the L3 demos (DESIGN.md Phase 3).

| case (tier) | start | result | cost |
|---|---|---|---|
| 13N `13N_tier0` (0) | 4 high-exposure flips polished to 29,709 (ref 26,678) | PASS, exact to 1e-4, cycle 1 | 0.39 node-h, 3 slots |
| 7Be `7Be_tier1` (1), `6Li+p/3He+a/.../11-8-26_drive_bench` | 8 flips polished to a 17-sign basin 13.5 % above the reference 5,290.1 | attempts 2-3 FAIL (sign rounds alone: 6,610 / 6,003); attempt 4 PASS at 5,307.5 (+0.33 %, data chi2 below the reference) once the POPULATION stage existed | 9.8 node-h, 8 slots, STOP at the 8 h budget |
| 12C+p `12Cp_tier1` (1), `12C+p/11-10-26_bench_tier1` | DeBoer's 8-9-26 model with Claude's 26,368 level values (100,748 in the free scheme) | PASS, exact: polish 24,740, 22 sign proposals accepted none, crossover found the 3/2- E2 flip -> 12,039.786 = reference | 0.06 node-h, 8 slots |
| 10B+p `10Bp_tier2` (2), `10B+p/11-10-26_bench_tier2` | round 8 variant A (2022 signs, 6,215) vs B (5,716): five signs, four magnitudes | PASS, exact: sign rounds (68 proposals) found nothing, the population crossover flipped the two 9/2+ channels -> 5,676.092 = reference in 0.96 node-h; DONE at 1.31 node-h; one review-high asked (the reference's own 1 MeV 5/2+ pole flag), answered with the reference's evidence (first run VOID: `init --sav` had taken the .azr's fixed values, see section 8) | 1.31 node-h, 8 slots |
| 12C+p L3 demo from scratch (`12C+p/11-10-26_L3_demo4`, `_demo5`) | ENSDF levels, 39 data sets, Claude's draft spec with nine open decisions | DONE, 3 cycles, zero wait decisions, 63,456 (demo 4); demo 5 adds the photon caps (1e5 eV, three widths at the cap) | 1.4 node-h, 8 slots |
| 7Be `rmfit uq` validation (Phase 4), `6Li+p/3He+a/AZURE2_evaluation/11-10-26_uq` | the tier-1 reference (5,290.1, 195 free), 4 NUTS chains x (1000 + 2000), norms sampled, 4 saturated poles held | PASS, no human input: R-hat 1.003, ESS >= 826, 0.57 % divergent; S34(0) = 0.544 +- 0.007 keV b, sampled = linear within 4 %; CSEWG's 0.56 +- 0.01 (externals on) is 1.3 sigma away -- a model difference | 4.8 h on 24 slots |
| d+t `rmfit uq` validation (Phase 4), `3H+d/11-12-26_uq` | the archive's V1 9 fm model, d+t data alone (Haesner out), 15 free, 4 bounded amplitudes (theta2 box = the archive's Wigner prior), 4 NUTS chains x (1000 + 2000) then (2000 + 4000) | gates FAIL twice (R-hat 1.013 / 1.018 on width_1_2, ESS 266 / 145, 0.9 % divergent: a rarely visited tail, also seen by bounded emcee) -> `uq-gates`; the band is stable: S(40 keV) 25.652 [25.408, 25.913] MeV b sampled, 25.615 +- 0.249 linear (ratio 1.01), NUTS = emcee within 0.15 sd, the archive with Haesner 25.745 [25.504, 25.976].  Found on the way: the unbounded posterior (bounds added) and a frozen metric (metric_u fixed).  Run 2 (4 x (2000 + 8000), DeBoer's call): R-hat 1.009 and 0.81 % divergent pass, ESS 261 fails the 400 gate; band 25.660 [25.405, 25.882], NUTS = emcee to 0.02 sd | 4.2 h + 4.1 h on 4 slots |

What that says:
- **Sign rounds alone do not cross basins; the population stage does.** Single, pair, channel and group flips never gained
  more than a few units against a 13.5 % gap (7Be); restarts + crossover between polished members found the reference's
  pattern on 7Be, 12C+p and 13N.  Run SIGN to convergence first (it is cheap and finds the local flips), POPULATION after.
- **The polish budget must fit the model**: 162 free parameters never converged in 6 x 300 evaluations (demo 3); the gate
  (`sign_after_converged_polish`) defers SIGN/POPULATION at most once and the readme then says so.  Size `polish_nfev`
  to the model before the run, not after.
- **The yardstick is DeBoer's, not 1e-4**: 7Be's two near-degenerate background configurations differ by 0.3 % with the data
  chi2 on the right side; "exact" is a secondary column.
- **A from-scratch model needs every stop the archive models had by inheritance**: photon widths without a cap ran to 1e16 eV
  (demos 3-4); seeds for free zeros, the anchor, the caps and the frozen block are spec items, not defaults to trust.
- **Costs** (8 slots): 13N / 12C+p minutes; 7Be hours (the population stage is 6 restarts x polish to convergence per cycle);
  13C+a (35k points, 330 free, 24 shards: objective 0.6-1.5 s, Jacobian ~20 s, polish ~9 min, sign round 2-4 h, level test
  ~1.5 h) has not run under the drive.

Still true (limits):
- No channel lines or pairs are added automatically; LADDER is unexercised; multi-compound-nucleus models are outside the sign
  rounds / levelscan; density / Doppler / thickness / screening kinds are single-session only (no shards).
- The structure search has been validated on recall only (13N, a removed level found with no J^pi given; 12C+p demos: the
  3/2-/5/2+ doublet proposals were unphysical or marginal); a level the archive never had has not been found by it yet.
- No live evaluation has run under the drive (10B+a s5 waits for DeBoer's spec); UQ (Phase 4) is not a stage yet.
- Energy shifts are finite-differenced; a shift held by polish's bounds is not differenced at all with AZURE2 >= 77cd6b3
  (HISTORY.md 2026-10-30).  Data covariances, normgroups, shiftgroups: `rmfit/covariance.py`, README "Data covariances and
  normalization groups", rules in HISTORY.md 2026-10-22/24/25 (relvector terms are scaled by one reference model,
  `cov_reference.npz`; `--refreeze-every` defaults to 0).
- rmfit is under git since 2026-11-07 and every campaign is pinned to one engine (`campaign.json["engine"]`,
  `EnginePinMismatch` unless `RMFIT_ALLOW_ENGINE_CHANGE=1`; the shared build changes only through
  `~/AZURE2/scripts/install_shared.sh`; pin a frozen clone under `~/AZURE2_work/`, never `~/AZURE2`).

## 8. Gotchas

- Never open two pyazr sessions in one process (parameter tables desync); rmfit runs
  one process per session and `bake()` verifies in a fresh process. Do not use
  `save_fit` for campaign files. `pyazr` bakes skip inactive levels since 2026-09-05;
  older baked files may have mis-placed values in J-groups with inactive lines.
- `bake()` writes the FIXED parameters' current physical values too since 2026-10-24 (a fixed width is fixed in rwa space,
  so its observed value moves with the level's free amplitudes); exports made before that with mixed levels are a slightly
  different model -- re-export from the ledger vector.  To freeze a level's observed widths, fix its closed-channel
  amplitudes too (`13C+a` `fix_frozen_anc.py`).  Test `tests/test_bake_fixed_13n.py`; the story in HISTORY.md (relocated).
- `total 1` (optical-theorem neutron total, AZURE2 dev d37d4e6) is in rmfit's keyword table and in
  bake's keyword guard; builds before d37d4e6 ignore it silently and compute elastic only.
- Delete `output/intEC.*` whenever segments change (stale-cache rule of the AZURE2 skill).
- Since 2026-11-04 `levelscan` / `structure add` default to the model's own J^pi groups and raise on a J^pi no
  pair can couple to; run_snapshots copied before that still default to the half-integer 13C+alpha list, so pass
  `--jpi` with them (section 3, and the 2026-11-04 entry at the end).
- New levels are appended at the end of the file and levels are removed by
  deactivation, so every existing parameter key stays valid across structures.
- A released polish lets amplitudes cross zero: sign patterns are not preserved by
  polishing, and a "basin" is only defined up to the amplitudes that are near zero.
- Frozen screens (flip, no refit) are cheap but favour flips of small amplitudes;
  the GN screen (one damped Gauss-Newton step on the group's columns) is the ranking
  that matters; coordinated multi-level flips need several backtracking GN iterations
  (`search.gn_iters_multi`) and their own polish quota (`search.multi_top`).
- Job mail: `-m abe` (start, end, abort) so a silent crash is noticed.
- **`pkill -f` / `pgrep -f` patterns are regexes and every reaction name has a `+`**: find the pid with a fixed-string match
  (`ps -eo pid,cmd | grep -F "11B+a_udr.azr"`), kill BY PID, confirm with `kill -0 <pid>` failing, only then remove the log;
  launch background programs with `< /dev/null` and a size cap.  **When a batch of jobs dies at once, `df -h /groups/<group>`
  first** (the group quota).  The 748 GB deleted-log story of 2026-10-11 is in HISTORY.md (relocated).
- **`init --sav` and FIXED parameters (2026-11-10)**: AZURE2's parameter-file reader sets every parameter it names, fixed level energies and widths included; rmfit seeds only the free ones and evaluates the .azr's fixed values.  The archive uses both readings: a CLI fit's `param.sav` holds the fixed values the fit ran with (10B+p var_B.azr + fit_B/output/param.sav, 23 background widths up to 10x apart: the tier-2 bench initialised at 14,082 for the archived 5,716 with no warning), a script-built base means the .azr and seeds from a stale .sav (10B+a s4/s5).  So init now logs every disagreement with the objective both ways and keeps the .azr's values by default; `--sav-fixed apply` (a CLI fit) writes `<stem>_sav.azr` (+ .sav) with the file applied and makes it the base (`Campaign.apply_sav_fixed`, test `tests/test_init_sav_fixed_13n.py`).  Keep the archived `chiSquared.out` in the base's output directory so init's reproduce check runs (bench: `chisq_out`); the audit of every `--sav` campaign is in `agentic/11-7-26_claude/sav_fixed_audit/`.
- **REVIEW's HIGH flags and the drive (2026-11-10)**: the init baseline is reviewed once (`REVIEW_baseline.md`); a HIGH flag the base model already carried is reported, not waited on; a flag answered 'continue' is not asked again (`drive_state` `review_continued`).  A flag the evaluator's own model carries (the 10B+p 1 MeV 5/2+ pole, DeBoer's 'no extra levels') still queues `review-high` when the start did not have it: the spec cannot tell the drive that a standing decision answers it, so answer with the evidence.
- **Close same-J^pi pairs: a report, not a constraint (2026-11-12)**: `review` flags two levels of one J^pi whose gap is below a fraction of the NARROWER total width (MEDIUM `level-close-width`, section "Close same-J^pi pairs"; default 10 %, `review.CLOSE_GAP_FRACTION`; `rmfit <dir> review --close-fraction f`, `python -m rmfit.review <azr> --close-fraction f`, spec budget `"close_fraction"`; 0 = off).  Nothing in rmfit enforces a minimum spacing: a centroid-plus-bounded-gap reparametrization would be a model constraint and its scale is the evaluator's to choose (not chosen as of 2026-11-12), and MEDIUM does not make the drive wait.  The flag is a question, never a verdict: on 13C+a it marks the 7/2+ pair at 10.42 MeV (gap 1 keV, widths 240 and 280 keV), which DeBoer's merge tests on the main line found NOT redundant (the (a,n2g) data need both, `13C+a/11-06-26_merged_regionD/readme`).  The test of a flagged pair has two halves: a merged refit, AND a refit of the pair started from the merged solution (`13C+a/11-09-26_merge72`, `11-12-26_split72`); a merged model that only wins against a two-level fit stuck in a worse minimum proves nothing.
- **Park-mode campaigns (`"use_park": true`)**: (1) the J > 0 wall is carried as residual rows since 2026-10-24
  (`engine.ParkWall`, test `tests/test_park_wall_13n.py`; check `m.park_norms(x)` on any older Park result); (2) `--sav` seeds
  are applied by NAME with no basis conversion -- convert a Brune `.sav` through a CLI mode-1 run in Park mode first;
  (3) `theta2_cap` bounds the observed theta^2 in Park mode, the formal one in Brune mode.  Details in HISTORY.md (relocated).

## 9. Refinement log -> HISTORY.md (dated index)

The dated log of every method change since 2026-09-05 (1,865 lines) lives in `HISTORY.md` next to this file (relocated
2026-11-10, nothing deleted).  Append new entries there and add a line here.  What each entry established is already a
rule in sections 2-8; read an entry when a rule's reason matters (`grep -n <date> HISTORY.md`).  Index (date -- subject):

- 2026-09-05  pyazr `engine_level_keys` counted inactive levels: the live 13C+a 5/2+ block was corrupted by every bake. ...
- 2026-09-05  sharding: the convolved Cierjacks segment (17 of 23 s per evaluation) is folded by rmfit on a fine grid; ...
- 2026-09-06  flips were credited with the incumbent's own continuation gain: added the control polish. ...
- 2026-09-06  level tests: seed only the new level's keys; window scans sharded (33 min per level); ...
- 2026-09-07  recovery benchmark: an 8-flip perturbation polished to a minimum sits 29 signs from its origin (`sign_distance`) ...
- 2026-09-07  MANA 13C(a,a): Heil's shapes at ~0.67x scale with 1% errors; three bad rows removed; ...
- 2026-09-07  round 3 of the signs benchmark (multi-level screen): 17 of 404 improve on the screen; ...
- 2026-09-07  Validation A PASSED on the signs-only benchmark: 777,349 -> 771,193 -> 769,848 -> 747,364 -> 730,814 -> 728,879 (target ...
- 2026-09-07  `verify_candidate` from a heredoc script fails (`spawn` needs a real `__main__` file): ...
- 2026-09-07  oracle on the 728,879 incumbent: the *old* incumbent's 7/2+ p5 L1 S2.5 pattern (3 flips) polishes to 716,659 (+11,930 ...
- 2026-09-08  first crossover round on 13C+a: 33 donor patterns, 8.1 h, 6 accepted/drift, union kept 2 -> 707,332 ...
- 2026-09-08  DeBoer's guidance on underestimated error bars (BandH stays in): added the configurable objective (`ObjectiveSpec`: ...
- 2026-09-08  the unscaled Sivia loss is degenerate when chi2/N >> 1 (see section 2): ...
- 2026-09-08  objective scan on 13C+a (`9-8-26_rmfit_robust/objective_scan.md`): ...
- 2026-09-08  freeing normalizations is a structure change: edit a copy of the base file (`AzrModel.set_segment_norm(<file ...
- 2026-09-09  PLANNED (DeBoer): residual-driven level search, `rmfit levelscan`: residual peaks -> candidate energies; ...
- 2026-09-09  narrow levels drift: the 13C+a 9/2+ (Gamma_n ~0.4 keV ...
- 2026-09-10  robust campaign (global-scaled Sivia, free Heil norms) finished at 183,309 (plain chi2 931,838): ...
- 2026-09-10  with the error bars corrected by hand (BandH x2, MANA 3% systematic in quadrature ...
- 2026-09-10  `rmfit levelscan` built (rmfit/levelscan.py, test_levelscan_13n.py). ...
- 2026-09-10  `levelscan.review_figure` + `Campaign.review_figure`: written by `relocate` and `structure add` (figures/). ...
- 2026-09-11  the exported `.azr` of a campaign carries the fitted `<levels>` but NOMINAL normalizations: ...
- 2026-09-11  RETRACTION (DeBoer challenged the claim, and he was right): ...
- 2026-09-12  a model variant written into a SUBDIRECTORY needs the base model's `data/` linked beside it ...
- 2026-09-12  THE TEMPLATE SCREEN AND THE NARROW-RESONANCE INTEGRATION FIX INTERACT BADLY, and this is now the binding cost problem. ...
- 2026-09-13  A FREE ENERGY SHIFT IN THE .azr IS NOT A FREE PARAMETER IN A CAMPAIGN. ...
- 2026-09-13 (later)  the same shift test was void a SECOND time: `run_polish` had `shifts_free=False` as its own default and replaced the ...
- 2026-09-13  OPEN ISSUE, single-session path only: `SingleSession.residuals(x ...
- 2026-09-13  A POSITIONAL .sav IS INVALID AFTER A LEVEL ADD/REMOVE. ...
- 2026-09-13  EVERY STRUCTURE MOVE IS JUDGED AGAINST A SAME-BUDGET CONTROL POLISH, now including `run_relocate` (it had none: ...
- 2026-09-13  THE REDESIGNED LEVEL SEARCH IS WIRED INTO `rmfit levelscan` with two new flags. ...
- 2026-09-13  REDESIGNED SCREEN, FIRST END-TO-END RESULT (13N, the removed 3/2- 3.5032 MeV level ...
- 2026-09-14  REDESIGNED SCREEN, FIRST REAL USE (13C+a at Ex 9.862 MeV, job 1441224, `13C+a/9-13-26_levelscan_986/`): NULL. ...
- 2026-09-14  THE TEMPLATE SCREEN IS TWO-STAGE (`template_screen(stage_scales=(1.2, 5.0), refine_top=3)` ...
- 2026-09-14  FIRST LEVEL ACCEPTED BY `structure add` ON 13C+a AFTER THE FROZEN SCREEN SAID NULL at the same energy (job 1441491 ...
- 2026-09-14  THE TEMPLATE SCREEN'S AMPLITUDES WERE WRONG BY ~100x ON 13C+a; ...
- 2026-09-14  FIX VALIDATED ON THE REAL CASE (login node, 6 shards, grid 5/20, 1/2+ only at 9.862 MeV on the 92-level incumbent): ...
- 2026-09-14  GATE C' (`13C+a/9-14-26_levelscan_986_fixed`, job 1441597): ...
- 2026-09-14  THE SCREEN'S LOCAL TOP CANDIDATE, A 9/2+ 2 keV FROM AN EXISTING 9/2+, WAS ACCEPTED BY THE CRITERIA (job 1441606 ...
- 2026-09-14  FIRST LEVEL FOUND FROM RESIDUALS ALONE (`13C+a/9-14-26_levelscan_resid`, job 1441631, `levelscan --top 3 --refit 1` ...
- 2026-09-14 (DeBoer)  BROAD STRUCTURE FIRST. "Don't get stuck investigating the inconsistencies between alignments of very narrow resonances ...
- 2026-09-14 (evening)  STATE AND HANDOVER. Campaign best: 366,565, 95 levels (`13C+a/9-14-26_signround_72p`). ...
- 2026-09-14 (evening)  READ THE DRIVER'S campaign.log, NOT THE SGE STDOUT FILE. ...
- 2026-09-14 (night)  THE BROAD-ONLY SEARCH PAID OFF AT ONCE (`13C+a/9-14-26_levelscan_broad2`, job 1443649 ...
- 2026-09-14 (night)  THE BROAD-ONLY SEARCH FOUND THE CAMPAIGN'S LARGEST GAIN (`13C+a/9-14-26_levelscan_broad2`, job 1443649 ...
- 2026-09-14 (late)  SIGN ROUNDS NO LONGER PROPOSE FLIPS OF ~ZERO AMPLITUDES (search.py, backup `.bak-2026-09-14`): ...
- 2026-09-15  A DETACHED (nohup) SUBMITTER CANNOT qsub ON THIS CLUSTER: "job rejected: job does not provide an AFS token". ...
- 2026-09-15  SECOND BROAD LEVEL FROM THE SAME SEARCH FAMILY (`13C+a/9-15-26_levelscan_broad4`, job 1447357 ...
- 2026-09-16  A SIGN FLIP IN A CHANNEL THE DATA DO NOT SEE IS A NO-OP, AND SIZE DOES NOT TELL YOU WHICH ONES THOSE ARE. ...
- 2026-09-16  WHEN SINGLE-LEVEL ADDS STOP PAYING, MAP THE CHI^2 AND AUDIT THE CAPS BEFORE SCREENING ANOTHER ENERGY. ...
- 2026-09-16  THE MODEL'S BACKGROUND POLES WERE INERT, AND THAT IS WHY THE FIT WAS PINNED AT THE WIGNER LIMIT. ...
- 2026-09-16  level tests accepted broad absorbers on the 13C+a high-Ex window (`13C+a/9-14-26_highE_structure`): ...
- 2026-09-16  TWO SAME-J^pi LEVELS WITHIN ~1 keV MAKE A FIT UNWRITABLE. ...
- 2026-10-06  Park parametrization available (`"use_park": true`)
- 2026-09-17  audit the pair table before fitting (13C+α)
- 2026-09-18  seed dead channels in units of γ_W, never in keV (13C+α)
- 2026-09-18  leave-one-dataset-out: totals are not enough (13C+α)
- 2026-09-18  a per-dataset table must reproduce a number you already know
- 2026-09-18  after a session restart, qsub may lose its Kerberos cache
- 2026-09-18  new data in a channel the model never used (13C+α, (α,α₁γ))
- 2026-09-18  campaign directories go directly under the reaction directory
- 2026-09-19  one bad point can hold a converged fit hostage (13C+α, MANA)
- 2026-09-19  levels added by the search had FIXED energies (method gap)
- 2026-09-19  run_level_add now fits the new level's energy; and restarts are not the limit
- 2026-09-19  AZURE2's 1 keV level-merge tolerance is permanent; rmfit now guards against it
- 2026-09-20  `add_level_variant` NEVER SEEDED OMITTED CHANNELS, whatever `LevelCandidate`'s docstring said (`seed_fraction` was an ...
- 2026-09-20  after a login-node REBOOT the Kerberos caches are gone
- 2026-09-20 (later)  "EFFECTIVE PARAMETERS" IN tau WHEN CHANNELS ARE SEEDED (DeBoer's decision). ...
- 2026-09-20  a template screen can manufacture a level (13C+α, 7/2⁺ at 10.42)
- 2026-09-20 (evening)  both fixes from the entry above are installed
- 2026-09-21  first real use of the capped templates; a level add can be a SPLIT
- 2026-09-21 (morning)  "splits" is now a verdict; the screen's "nan" explained
- 2026-09-21 (night)  J^pi reassignment study; two-channel templates; when a flag is a grid gap
- 2026-09-22  "BROAD" VERDICT (DeBoer). Report figures of the 13C+a high-Ex window showed its broad levels fitting the AVERAGE (a,n0) ...
- 2026-09-23  THRESHOLD GUARD on free level energies. In `13C+a/9-22-26_ntot_fix` the polish converged (1,403,526 -> 311,680) but the ...
- 2026-09-24  the level search never estimated a width; `--gamma auto` now does (13C+α high-Ex)
- 2026-09-24 (later)  stripping broad levels to "rebuild narrow" fails; rank residuals by density
- 2026-09-24  FIGURES OF UPOS DATA NEED DATA-MODE CURVES. A <segmentsTest> extrapolation can never be UPOS (ESegment(ExtrapLine) ...
- 2026-09-25  data-definition fixes outrank structure; measure them frozen first
- 2026-09-25  a level pinned at the threshold guard: test both sides, same budget
- 2026-09-25  zero amplitudes never move: audit closed channels below thresholds
- 2026-09-25  two copies of one conversation: name one owner
- 2026-09-25  width caps by energy window (`BoundsPolicy.theta2_cap_windows`)
- 2026-09-25  copying a campaign directory: repoint the ledger's structure paths
- 2026-09-27  per-level theta^2 cap for added levels; the narrow loop
- 2026-09-28  peak-weighted chi² and a per-channel width bound for narrow-level tests
- 2026-09-28 (later)  three traps from the run-off comparison
- 2026-09-29  csh job scripts: never put JSON in a shell variable
- 2026-09-30  four lessons from the 12C+α campaign (`12C+a_onefile/9-8-26_rmfit_campaign/`)
- 2026-09-30  export refuses a model with a free width at exactly 0 (guard added)
- 2026-09-30  what the 13C+α window campaigns taught about windowed fits (both sessions)
- 2026-10-01  CRC default Python moved to 3.12.15; its sqlite3 is broken on compute nodes
- 2026-10-02  idle-time reviews are part of the process (section 3b); four lessons from the 13C+α merged fit
- 2026-10-03  local release: judge a flip or a new level after its neighbours have moved
- 2026-10-05  a released level that collapses never answers "is a BROAD level wanted?"; width floors and per-channel bounds
- 2026-10-06  data-only window fits are a screen, not a start vector
- 2026-10-07  a candidate is judged on the whole data set, not on the data set it was aimed at
- 2026-10-07  the Ex 9.4 recipe is now section 3c
- 2026-10-10  near-degenerate BROAD same-J^pi levels are separated at write time, not fixed
- 2026-10-10  shard layout: composite sums are split, free-shift segments get their own shard (~4x per iteration)
- 2026-10-11  a `+` in a pkill pattern filled the group quota
- 2026-10-12  the width floor belongs on the TOTAL width; a level add only has the channels the candidate names
- 2026-10-12 (b)  sharded convolution follows AZURE2 dad58dc; local ±mΓ table in every level add; seed reset after the window scan
- 2026-10-15  windowed `<targetInt>` convolution in sharded fits; fixed-angle conv pieces
- 2026-10-16  recall test of the level add; split rule ignored distant poles; the seed decides alpha-dominated levels
- 2026-10-20  centred parameter priors (`param_priors`), first use an ANC prior
- 2026-10-24  model-scaled (`relvector`) covariance: refreeze between polish passes (`--refreeze-every`)
- 2026-10-25  physical seeds must be TINY, not 1 eV: the Brune transform can fail and rescale a level (10B+α stage 1)
- 2026-10-26  a frozen build needs AZURE2_ROOT, not just PYTHONPATH (13C+a session)
- 2026-10-30  level labels in models with several compound nuclei carry "@<nucleus>"
- 2026-10-30  Jacobian shift columns: held ones skipped, the rest forward only (DeBoer: ...
- 2026-11-04  levelscan / structure add default to HALF-INTEGER J^pi: integer-spin systems must pass --jpi
- 2026-11-07  <targetInt> ranges were dropped from shards; scattering lengths were missing from the rows (11B+a)
- 2026-11-07  data files outside data/ were lost in every working directory; bake when the fit started from a file (11B+a)
- 2026-11-09  Recovery yardstick; Phase 2.2: the structure-search rules become drive defaults
- 2026-11-08 (evening)  POPULATION: restarts + crossover become a drive stage (7Be benchmark post-mortem)
- 2026-11-08  `rmfit drive`: the loop is closed in code (first version)
- 2026-11-10  Phase 3.3: First fits -> the drive's build-state list; section 7 rewritten from the bench results; long gotchas of
  section 8 (bake fixed values, pkill/quota, Park) and the old section 7 relocated verbatim to HISTORY.md ("Relocated from SKILL.md")
