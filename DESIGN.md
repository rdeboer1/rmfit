# rmfit design and roadmap (2026-11-07)

This file replaces the design plan the README, the rmfit-campaign skill and `13C+a/9-5-26_rmfit_campaign/readme`
used to cite (`~/.claude/plans/cached-snacking-bubble.md`, lost).  The retrospective it comes from is
`R-matrix/agentic/11-7-26_claude/readme`; read that for the evidence.  Dated progress notes go at the end of this
file; the rmfit-campaign skill keeps the process rules.

## What rmfit is for

An evaluator's global R-matrix fit as resumable steps a script runs on one cluster node and a fresh session picks
up from `STATUS.md`: sharded exact evaluation (chi2 is additive over segments), bounded trust-region polishes in
reduced-width-amplitude space, interference-sign rounds, level add/remove/relocate, dataset-off diagnostics,
basin crossover, a recovery benchmark, a ledger of every candidate.  Module table: README.md.

## Where it stands (2026-11-07)

202 campaigns since August 2026 (13C+a 136, 10B+a 53, 11B+a 12, 12C+a 1); 62 tests.  Every mechanical step is
automated, but a Claude session still chooses every step except `round --rounds N`, every decision about the
objective (data, anchors, systematics, window, frozen block, caps) is made in chat during the campaign, and the
checks DeBoer makes by eye in the GUI (average-vs-narrow structure, norm trends, target-integration grid
exploitation, spurious narrow levels) have no automated counterpart.  Engine churn (the shared pyazr .so replaced
under running jobs, eight frozen builds in eight days for 17O+a) and parameter-file round trips were the largest
avoidable time losses.

## Roadmap (phases; agent-days are estimates)

Principle: human input at the FRONT (a declared spec) and the END (review of a candidate); the middle a closed,
checked loop; autonomy MEASURED by a benchmark.  No new AZURE2 physics unless a testbed needs it.  Data-treatment
decisions stay with the evaluator; the spec records them.

### Phase 0 -- stabilize (done 2026-11-07 unless marked)
- rmfit under git (`rmfit/.git`, baseline commit 7539e88; the 131 `.bak-*` files are in `attic/`, untracked).
- Engine pin per campaign: `enginepin.py`; `init` records `campaign.json["engine"]`; evaluating commands refuse
  another engine (`EnginePinMismatch`) unless `RMFIT_ALLOW_ENGINE_CHANGE=1`; status/report/log/engine warn only;
  `rmfit <dir> engine` shows both.  The job template sets `AZURE2_ROOT` from the pin and checks the .so md5 before
  Python starts.  Campaigns made before 2026-11-07 (no pin) are never refused.  Test: `tests/test_enginepin.py`.
- `~/AZURE2/scripts/install_shared.sh`: the only way to replace `~/bin/AZURE2` and `~/AZURE2/pyazr`; refuses while
  a job or process uses the shared build; keeps old inodes as `.keep_<date>_pre-<hash>`; writes `~/AZURE2/INSTALLED`.
  DeBoer's cadence decision: weekly tagged releases; campaigns pin a frozen clone, never `~/AZURE2`.
- AZURE2-side follow-up (open): `pyazr.build_id()` compiled into `_azure2` so the pin can name a commit directly.

### Phase 1 -- declare the objective, automate the eye (~8 agent-days)
- `spec.py` / `decisions.py`: `spec.json` (authoritative) + rendered `SPEC.md`; sections engine, parametrization,
  data_sets[] {role anchor|free|excluded|screen, norm {nominal, fixed, prior_sigma, group}, systematic_source,
  excluded_rows, window, frame_checked, covariance_file, target_int}, model {fit_window_ex, pairs_required, radius,
  frozen_block, bg_poles, candidates_file}, bounds / objective / search (= BoundsPolicy / ObjectiveSpec /
  SearchConfig), budget, pre_authorized {adopt_level rules, flip_adopt, dataset_off_adopt, extend_window,
  add_pairs_on_window_extension, drop_rows, ...}, stop_rules, standing_decisions[] {date, who, text}.
  `init --spec` derives campaign.json and records the spec sha; `spec check` verifies the .azr against it.
  `DECISIONS.md`: queue of questions outside the spec (machine-parseable headers, `rmfit decide <id> <choice>`).
  `run_level_add` adoption gated by `pre_authorized` (today an `accept` is adopted automatically; the
  resonance-search skill says "report, don't adopt").  First use: retrofit onto 10B+a s5/c9 and 13C+a merged.
- `audit.py` (`rmfit audit`, pre-flight, writes AUDIT.md; HIGH fails init): pair table and masses vs S
  (`pyazr.AzrModel.mass_check`), dead channels (`structure.omitted_open_channels`), nominal norms != 1, free
  unpenalized norms, normErr > 1 units check, integrity/overlap/duplicates/spikes
  (`13C+a/10-2-26_audit/audit_*.py`), target energies (`check_target_energies.py`), legacy `.sav` names
  (`convert_sav_names.py` regexes), absolute output paths, `<targetInt>` on test segments, engine pin, intEC age,
  1-keV level merges, clip check (`13C+a/9-30-26_merged/preflight.py`).  `--kind input|data|literature` = the
  idle-time subagent audits with templated prompts and a structured FINDINGS.md (DONE 2026-11-07: `audit_subagent.py`,
  `templates/audit_{common,input,data,literature}.md`; rmfit writes the prompt, the session hands it to a background
  subagent, verifies each row and marks it `--status`; `rmfit drive` will emit them from its AUDIT state).
- `review.py` (`rmfit review`, post-fit "GUI eye", writes REVIEW.md + figures): existing pieces
  `diagnose.dataset_table/compare/theta2_table/residual_runs/window_delta`, `Evaluator.point_residuals`,
  `local.sanity`, `levelscan.review_figure`, `13C+a/9-30-26_merged/toppoints.py`; new detectors: norm vs
  median(fit/data) direction; norm trend vs angle/energy; average-vs-narrow (port of resonance-search
  `blur_map.py` / `blur_compare.py` / `peakfind.py`); target-integration grid exploitation (objective at the campaign
  grid vs a converged grid via `Campaign.set_grid_setting`; level width vs sub-point spacing); per-point summary
  (CLAUDE.md wording) + top-k chi2 carriers; provisional narrow / one-dataset levels.  Calibrate on the cases
  DeBoer's eye found: 11B+a bumpiness, 17O+a an2 grid, 13C+a high-Ex average, 10B+a ND5U25 norm 1.32 at fit/data 0.64.
  DONE 2026-11-07 (`review.py`, `tests/test_review.py`): table from `AZUREOut_*.out` (engine-free, any archived fit; the
  13N test output reproduces chiSquared.out per segment) or from a campaign's single session; detectors per-point /
  top-points / norm-opposite / norm-{angle,energy}-trend / residual-run / average-not-structure /
  broad-level-averages-peaks / fit-zigzag / level-below-resolution / one-dataset-level / grid-exploited (`--grid-check`).
  Calibration on the archived cases: 13C+a 9-17-26 gui_review -> the 12.5 MeV poles, 1/2+ 12.759 (57 MeV), 1/2- 11.468,
  7/2+ 11.507, 5/2+ 12.626 all HIGH/MEDIUM `broad-level-averages-peaks` (the two levels DeBoer kept, 7/2- 11.436 and
  3/2- 10.927, are flagged too: a real 0.5-2 MeV level in a dense region looks the same to this detector -- the
  evaluator's call); 17O+a an2 -> 5/2+ 8.1617 (13 eV) and 5/2- 8.2636 (0.8 eV) MEDIUM `level-below-resolution` under the
  Best target integration (plus four more of the same kind); 11B+a 8-27-26 -> the archived output is post-fix, so the
  zigzag detector is calibrated on a synthetic saw-tooth only; 10B+a ND5U25 -> synthetic norm-opposite test + the
  stage-1b campaign cannot be re-opened (covariance reference predates 2026-10-26).  First campaign run: 10B+a s5 (grid check -0.00 %; HIGH: the 2- 14.708 / 15.022 poles over six unfitted peaks; the fixed ND5U/MANA norms' n*).  Worked examples: `R-matrix/agentic/11-7-26_claude/review_calibration/`.

### Phase 2 -- close the loop (~10 agent-days + 2 weeks calendar)
- **2.1 DONE (first version, 2026-11-08; `drive.py`, `templates/run_crc_drive.csh`, `tests/test_drive_dry.py` engine-free, `tests/test_drive_13n.py` on the queue).**  States as planned except: SIGN x2 and the post-add SIGN are two states that each run rounds until the stop rule (>= 2 rounds, `sign_rounds_without_accept`); SEED_CHANNELS seeds existing free zero widths only (no channel lines added); PAIR_COMPLETENESS reports and queues (default `continue`), the pair builder stays with the supervisor; LADDER runs only with `model.ladder_Ex`; a pending `wait` decision ends the leg WAITING and the next leg applies answered `adopt-level-*` entries; DATASET_OFF never excludes (decision, default `keep`); REVIEW HIGH flags wait for the evaluator.  Not yet run on a live campaign.
- (as planned) `drive.py` (`rmfit drive`): resumable state machine PIN_CHECK -> AUDIT -> REPRODUCE -> SPEC_CHECK ->
  SCALE_ANCHOR -> SEED_CHANNELS -> PAIR_COMPLETENESS -> LADDER -> CANDIDATES -> INIT -> TIGHTEN -> SIGN x2 ->
  SHIFTS_FREE -> STRUCTURE_ADD -> SIGN -> DATASET_OFF -> REVIEW -> EXPORT -> {DONE | WAITING | loop}; the skill's
  "First fits" (anchor one set, seed lowest L per pair from `10B+a/10-25-26_Rmatrix_Claude/stage1/seed_stage1.py`,
  add every open pair as in `11B+a/10-27-26_HE_claude/model/add_pairs_he.py`, ladder via `windows.ladder_variants`),
  section 3 steps 1-7, section 4 stopping rules, budget caps per state, a required hypothesis on every structure
  candidate.  One SGE job per leg (`templates/run_crc_drive.csh`, generalized from `10B+a/11-6-26_s5_highE/
  run_crc_s5` + `polish_loop.sh`), self-resubmitting with `-hold_jid` unless DONE/WAITING/STOP; refuses the login
  node.  State in `drive_state.json`.  Traps as checks: intEC purge in adopt_structure/export, `_bare_extrap.azr`
  with targetInt off, output-path refusal, mode-1 reproduction before building, legacy-name refusal, pre-screen
  size cap.  The Claude session supervises: reads STATUS/DECISIONS/REVIEW, `rmfit decide`, `drive --dry-run`.
- **2.2 BUILT 2026-11-09 (first version; `spec.json` section `structure`, drive states RECALL and LEVELSCAN, `Campaign.run_recall`, CLI `recall`).**  Encoded: (a) **broad first** -- candidates with a known width below `structure.broad_first_kev` (10) wait until the broad queue and the residual scan are exhausted, then run as the narrow-alignment phase (`narrow_phase`); unknown widths count as broad.  (b) **Residual-driven candidates** -- state LEVELSCAN (`levelscan_per_cycle`, `levelscan_top`, `levelscan_gamma_kev` null = auto) runs `Campaign.run_levelscan` when the broad queue is empty: residual-run clusters, a template screen of every J^pi at the width the runs show, the best (J^pi, pattern) appended to candidates.json with the screen as hypothesis and the next two J^pi as alternatives that STRUCTURE_ADD tests on the full model (DeBoer's "one level of every J^pi at the estimated width" and the angular-distribution J^pi comparison, done inside the model on the differential segments within 250 keV).  (c) **Recall before trust** -- state RECALL after INIT removes the `recall_levels` broadest known levels one at a time (child campaigns in `recall/`) and asks the same level-add procedure to find them with no J^pi given; a level is re-found when accepted with the true J^pi, energy within max(50 keV, 3 Gamma) and width within a factor 3; below `recall_min_pass` every add of the run becomes an accept-pending decision (non-blocking decision `recall-low`, answer `trust` to lift it).  (d) **Local release** -- `local_release_mev` / `local_nfev`: neighbours, background and norms within the window are polished before the global stage of every add (DeBoer 2026-10-02).  Not encoded (documented as open): fitting data set by data set with a merge at the end (multi-campaign orchestration), data thinning for structure searches, candidates from the resonance-search scripts on raw data (levelscan is the in-model equivalent), the ML candidate source (pass criteria still unmet).
- (as planned) Structure-search defaults from DeBoer's steering: broad (Gamma > 10 keV) first; data-set-by-data-set then
  reconcile; never reconcile windows before the merge; angular-distribution J^pi shape screen; recall test on
  known levels before trusting level-add on a new reaction; candidates from ENSDF + resonance-search scripts; the
  ML fit-audit model (`ML_development/10-31-26_claude`) as `candidates.json "source":"ml"` only after its pass
  criteria are met on 10B+a.
- Only if a testbed needs it: multi-compound-nucleus sign rounds / levelscan (17O+a); sharded density / Doppler /
  thickness (12C+12C, 11B+a).

### Phase 3 -- measure it (~6 agent-days + cluster time)
- `bench/` (`cases/<name>/case.json`, `bench.py run|score`, git-tracked `results.tsv`).  Reference objectives
  re-measured on the pinned engine (archived numbers carry the Q-coefficient, under-integration and normErr bugs).
  Degraded starts: perturbed signs/jitter, levels removed, the archived start before the human's key decision.
  Score: chi2 ratio, DECISIONS requested, human turns, wall/node hours, recall (`keys.sign_distance`), review flags.
  Tiers: 0 minutes (`ML_development/10-31-26_claude/gen_12Cp/superset.azr`, `tests/fixtures/jpi_integer/10Ba_c8.azr`)
  after every commit; 1 hours (7Be `6Li+p/3He+a/AZURE2_evaluation/10-20-26_Elwyn_fix`, 5088.78+201.29, Brune and
  Park; 12C+p `8-9-26_claude_learns_12C+p` from Claude's 26,368 basin vs DeBoer's hand-flipped 12,214); 2 a day
  (10B+p round 8, 5,686.5+27.4; "no extra levels" as a recall test); 3 rare (11B+a `11-02-26_np702_gpSM` 10,887.6;
  10B+a c9/s5; 13C+a merged from its spec, target <= 706,809 on the 9-5-26 data with the same decision list).
- One fresh spec-to-candidate demonstration on a small reaction, zero mid-run chat (candidates 13C+n, 7Li+a,
  12C+p from scratch).
- **3.1 BUILT 2026-11-09** (`rmfit/bench/`: `cases/<name>.json`, `python3 -m rmfit.bench score|run|list`, `results.tsv`): a case names a
  reference campaign and runs; `score` reads the ledgers only (objective, data chi2 and penalty from the segment scores, sign distance,
  wait decisions and human turns from DECISIONS.md, node hours from drive_state.json, new HIGH/MEDIUM flags of REVIEW.md vs the
  reference's; `--review` writes a missing or stale REVIEW.md, noting the engine) and applies the yardstick; `run` writes the SGE job
  (reference init, `perturb`, spec, drive).  First rows: 7Be tier 1 attempts 2, 3 (FAIL) and 4 (PASS: data chi2 5082.5 <= 5088.8,
  +0.33 %, 0 wait decisions, no new flag; not exact).  Tier 0 = the AZURE2 tests/13N fixture (4 flips, 3 slots, ~1 h), not the
  ML superset (pseudo-data, no reference fit).  12C+p tier 1 (26,368 -> 12,067 via DeBoer's background-gamma branch) and tier 2/3
  cases are still to be defined as case files.
- **3.2 STARTED 2026-11-09** (DeBoer: "12C+p from scratch for the L3 demo"): `12C+p/11-9-26_L3_demo/` -- base model from the TUNL
  level scheme + background poles + the 8-9-26 data segments (build_base.py), spec.json drafted by Claude with every data-treatment
  choice recorded as a standing decision for DeBoer to confirm (anchor Meyer 1976; Gerke 1966 excluded provisionally for its
  placeholder errors; two norm priors from the standing 10 % rule; theta2 cap 1.5 for the s-wave state), pre-build audit fixed the
  inherited normError fraction-vs-percent error on all 111 segments; one job (1718547, 8 slots, <= 20 node-hours) runs the build phase
  and the loop with no chat.
- Skill section 9 (the 1,750-line dated log) -> `rmfit-campaign/HISTORY.md`; sections 2-8 become one-line rules
  pointing at the enforcing function; section 7 rewritten from benchmark results.
- **Recovery yardstick (DeBoer 2026-11-09, after the 7Be attempt-4 post-mortem):** a drive run from a degraded start "recovers" the reference when (1) its data chi2 is <= the reference's, (2) its penalized objective is within 0.5 % of the reference's, (3) `rmfit review` raises no flag the reference does not have, and (4) zero wait decisions were asked.  The old "objective within 1e-4" is kept as a secondary column (`exact`): on 7Be it selects one of at least two near-degenerate background-pole configurations (bench readme 2026-11-09 06:05/06:15), which is not a property of the loop.
### Phase 4 -- UQ as the standard last stage (~5 agent-days)
`rmfit uq`: export -> Park if saturated / two-channel levels -> centred priors from the spec -> emcee/NUTS ->
automated R-hat / tau gates -> linear vs sampled comparison -> band.  Validate on 7Be and d+t.

## Open items not on the roadmap
Competing-resolution test for near-duplicate levels; differential-convolution shards; single-session-only kinds
(density, Doppler, thickness, screening) in shards; `structure add` exit status on a failed scan.

## Progress log

- 2026-11-10 02:40  Two more gaps closed while demo attempt 4 runs.  (1) Photon widths were unbounded: `default_bounds` caps
  particle amplitudes through the Wigner limit, which photon channels do not have, so attempt 3's 5/2- background pole polished
  to Gamma_gamma 1e12 eV.  `BoundsPolicy.photon_width_max_ev` (1e4) / `bg_photon_width_max_ev` (1e5) now bound |x| <=
  sqrt(Gamma_max / c), c the asymptotic factor of the transform probed at x = 1e4 per photon channel (with external capture the
  physical width is c (x - x0)^2, x0 of order 1: 13N 1/2+ E1 has x0 = 1.0, so the factor at x_ref would be 12x off); generous
  stops, not Weisskopf limits, for DeBoer to set per reaction (8f970e9; tests/test_photon_bound.py, stub + 13N engine).  (2) The
  AUDIT state now writes the three subagent audit prompts and waits for their verified FINDINGS.md before the first engine state
  (decision `audit-subagents`; rows in status 'decision' become one wait decision each; `pre_authorized.skip_subagent_audits` set
  in the bench case specs; 5b0e54d).  Neither reached attempt 4 (job 1718885, started 00:52 on bc40f84); the 13N queue test is
  resubmitted on 5b0e54d once job 1718884 (on bc40f84) reports.

- 2026-11-10 02:00  Seeding verified, next gap found: 13N test job 1718747 passed its new SEED_CHANNELS check (13 free zero channels
  of the fixture given placeholders and seeded) and every other check but POPULATION, which was "deferred to the next cycle" because
  the polish of the now-larger model did not converge in 2 x 30 evaluations -- in a cycles_max 1 run there is no next cycle.  L3
  demo attempt 3 (job 1718748, 162 free parameters after INIT, 7.59 M -> 101 k in cycle 1) showed the same at scale: TIGHTEN ran its
  6 x 300 evaluations still gaining 10 % per round, and SIGN and POPULATION were deferred in cycle 1 and again in cycle 2, i.e. the
  candidate would have had no sign round at all.  Drive change (bc40f84, `_polish_gate`): the deferral happens at most once per
  campaign and never in the last cycle; after that the stages run on the unconverged incumbent and the readme says the polish
  budget is too small for the model.  Dry test scenario 5 covers it.  Attempt 3 stopped cleanly (STOP_DRIVE) in cycle 2; attempt 4
  (`12C+p/11-10-26_L3_demo4/`, same base and spec, job 1718885) and the 13N test (job 1718884) queued on bc40f84.  Also seen in
  attempt 3's cycle-1 export: 5/2- background photon widths of 1e12 eV -- the policy caps particle theta2, not photon widths; the
  REVIEW of attempt 4 will show whether it flags them (otherwise a bounds gap to add).

- 2026-11-10 01:10  L3 demo attempt 2 (job 1718582): DONE in 1.06 node-hours, zero wait decisions, REVIEW.md written -- the process
  works end to end on a from-scratch model -- but the candidate is poor (223,352, chi2/N 55.5) because two drive states did nothing on
  a from-scratch base: SEED_CHANNELS searched the engine's free list for zero widths, and an exact zero is never a parameter (Golden
  rule 3), so the eight background poles' 20 channels stayed out of the fit; SHIFTS_FREE polished with no shift parameter because the
  base varied no shift.  43 parameters, 1-3 sign proposals, immobile restarts.  Fixed (d4ba273): placeholders before the seed
  session (photon channels at `model.photon_seed_ev`), varyShift on at SCALE_ANCHOR where a shift uncertainty exists, dataset-off
  decision asked once.  13N test now zeroes a background channel and requires it seeded (job 1718741); attempt 3 queued
  (`12C+p/11-10-26_L3_demo3/`, job 1718742).  Neither gap was visible on 7Be or 13N, whose models carry fitted values everywhere:
  the from-scratch path had never been exercised with the engine.
- 2026-11-10 00:40  13N tier-0 bench rebuilt (job 1718612, 23 min on 3 slots): reference = the fixture polished 6 x 200 to 26,678.456; the
  4-flip start (29,709) recovered it EXACTLY (sign distance 0, +0.0 %, 0 decisions, no new flag): PASS and exact.  Tier 0 now runs
  in ~25 minutes on 3 slots as a drive regression with a real reference.  results.tsv: 7Be x 3 + 13N x 1.
- 2026-11-10 00:10  13N tier-0 bench (job 1718536, 25 min on 3 slots, DONE, 0 decisions): the drive took the 4-flip start 29,709 -> 26,678 --
  92 % BELOW the "reference" 336,448, because `~/AZURE2/tests/13N` is a plain-calculation regression fixture (chiSquared.out 336,522 at
  the .azr's start values), not a fit.  The scorer now reports REFERENCE-SUSPECT when a run beats its reference by > 1 % and tests
  'exact' as |rel| <= 1e-4 (it had passed a -92 % run as exact).  Tier-0 case redefined: the reference is the fixture polished to
  convergence (`polish` rounds in the job before `perturb`); the bogus row was removed from results.tsv.
- 2026-11-09 23:55  L3 demo attempt 1 STOPPED, attempt 2 queued.  The three idle-time subagent audits (input, data, literature; prompts
  from `rmfit audit --kind all`, Sonnet, ~10 min each) on the running first attempt found what the machine audit cannot: a FRAME error
  in the inherited segment table (11 elastic sets with EXFOR heading ANG = lab angles entered as AZURE2 code 4 = c.m.; 2768 rows;
  Rutherford test confirms lab), Jiang 2004 converted without the Jacobian (1.19x), Vojtov 1977b being capture to the 2366 keV state,
  Armstrong 1966b a duplicate of 1966a, digitizing precision used as point errors (Jackson at 29 % of the weight), 100 free norms for
  36 files, and the channel radius (3.5 fm in the model, 6.0 in a stale readme and my spec; published 3.4-3.6).  Attempt 1 qdel'd 75
  min in; `12C+p/11-9-26_L3_demo2/` built with the corrections (readme lists each, with the provisional ones as open decisions) and
  queued as job 1718582.  Process lesson, to build: the subagent audits belong BEFORE the first engine state (the drive's AUDIT state
  should emit the prompts and wait for FINDINGS.md), and `spec check` now compares channel radii (b1fdec2).  Verified rows are
  marked in the first attempt's audits/*/FINDINGS.md (`rmfit audit --status`).
- 2026-11-09 22:50  Phase 3 started (DeBoer: "go ahead with Phase 3, 12C+p from scratch for the L3 demo").  3.1 bench suite built and
  committed (8525431) with the 7Be rows (attempt 4 PASS under the yardstick; the review-flag comparison that was pending is now done:
  no new HIGH/MEDIUM flag); 13N tier-0 case queued (job 1718536).  3.2 L3 demo on 12C+p from scratch queued (job 1718547; readme in
  the directory).  Engine: DeBoer installed a new shared build at 21:31 (pyazr 2.10.0 .so cda57a47); the 7Be campaigns stay pinned
  to 6ea4e95a, which is no longer on disk -- the scorer opens campaigns read-only and notes the engine a review ran on.  Also: the
  drive's AUDIT no longer blocks on data findings of a set the spec excludes (bfd214f); the target-energies checker's `ln` fixed.
  Summary page of the 7Be benchmark published for DeBoer (agentic/11-7-26_claude/7Be_bench_summary/).
- 2026-11-09 19:40  13N engine tests of RECALL + LEVELSCAN.  Job 1717876: the recall child's AZURE2 could not fill its segments (relative data paths from `recall/<tag>/`); fixed by linking the data directories into `recall/` and each child (4483508).  Job 1718060 (62 min, all checks pass): RECALL removed the 1/2+ 2.368 MeV level (Gamma 133 keV) and the level-add procedure located it with no J^pi given (1/2+, 2.3686 MeV, Gamma 122 keV, gain 8.6e6) -- and classified it "unphysical", because its s-wave amplitude ends on the theta2 cap 1.0, where the incumbent's own level sits (`at bound: g[1/2+#1 p1 L0 S0.5]=2.282` in every polish of the parent).  That is the recall test doing its job: the criteria would reject a level the model carries, and the cause is the policy cap, not the search.  `run_recall` now reports `located` (J^pi, energy, width right) apart from `passed` (criteria accept), names an at-cap rejection as a spec-bounds finding, and the drive's recall-low decision carries the cause; the same-J^pi proximity check skips switched-off levels (the recall child saw its own removed level as a "doublet partner"); 13N test requires the level located (6733cf6).  Job 1718295 (56 min): all checks pass, RECALL table reads "LOCATED but rejected by the criteria (... theta2 cap 1, where the incumbent's own level sits too (theta2 1.1) ...)", no doublet flag against the switched-off level.  Phase 2.2 is verified end to end on 13N; kept log tests/_queue_drive/drive_1718295_pass.log.  LEVELSCAN as designed: the one bank candidate tested, then 1 residual cluster screened and a 7/2- at 2.391 MeV appended, tested as accept-pending because the failed recall had marked adds untrusted.
- 2026-11-09 08:30  Phase 2.2 built (DeBoer: "go ahead with the new yardstick and Phase 2.2"): spec section `structure` (broad_first_kev, narrow_phase, levelscan_per_cycle/top/gamma_kev, local_release_mev/local_nfev, recall_levels/min_pass; template + SPEC.md render), drive states RECALL (after INIT) and LEVELSCAN (before STRUCTURE_ADD), STRUCTURE_ADD broad-first gate with the narrow phase last and a J^pi list per candidate, `Campaign.run_recall` + CLI `recall`, crossover-pass donor dedupe.  Dry test extended (RECALL, LEVELSCAN once the broad queue empties, narrow deferred) and passes; 13N end-to-end test extended (recall of the broadest known level, levelscan top 1) queued as job 1717876.  Open from 2.2: per-data-set fits with a merge, thinning, raw-data candidates, ML source.
- 2026-11-09 06:30  DeBoer: "go ahead with the new yardstick and Phase 2.2".  Yardstick adopted (Phase 3 bullet): data chi2 <= reference, objective within 0.5 %, no new review flag, zero wait decisions; 7Be attempt 4 passes it (5082.5 <= 5088.8, +0.33 %, 0 wait decisions; review flags to be compared when the bench scorer exists).  Phase 2.1 verification closed on that basis.  Phase 2.2 (structure-search defaults) starts.
- 2026-11-09 06:15  diag4b (bench readme 06:15): transplanting the reference's energies (5307.7), its whole background block (5313.1) or energies + signs (7134) onto pert4's vector all polish back into pert4's configuration.  The two basins are near-degenerate competitors of the penalized objective (pert4 better on data chi2, worse on norm penalty).  Phase 2 criterion as written (objective 1e-4) is not met and probably picks the wrong yardstick; proposed replacement in the bench readme (data chi2 <= ref, objective within 0.5 %, review flags, zero decisions).  Awaiting DeBoer.
- 2026-11-09 06:05  Attempt-4 post-mortem (bench readme 06:05): the sign oracle fails (6994 at distance 9), so the last 0.33 % is not a sign barrier.  pert4 fits the data better than the reference (chi2 5082.5 vs 5088.8) and loses 23.7 on the norm penalty; five background/high poles sit 0.4-1.8 MeV from the reference's and the 3/2+#2 pole is emptied.  A distinct background configuration of equivalent data quality.  Candidate drive move if diag4b (job 1715385) confirms: background-pole energy kicks in the population restarts or a RELOCATE stage.  Benchmark criterion to revisit with DeBoer (objective 1e-4 vs data chi2 + review flags).
- 2026-11-09 05:20  7Be benchmark attempt 4 (POPULATION on, bench readme 05:20): STOP at node_hours_max 8 h in cycle 7, final 5307.46 = reference x 1.0033, sign distance 13, no wait decision.  Criterion (1e-4) not met; two population rounds took 9.8 % -> 0.66 % -> 0.33 % (attempt 3 ended at +13.5 %).  Cycles 1-5 were polish-only (sign/population deferred until the polish converged).  Post-mortem diag4 queued (job 1715363); options for DeBoer in the bench readme.
- 2026-11-08 19:45  13N end-to-end drive test with POPULATION on passed (job 1712562, 32 min, 15 checks): two restarts (8 random flips each) polished into one other basin (70700.8 vs incumbent 67402.4, sign distance 3), one crossover pass polished 10 patterns and recovered the incumbent, no gain -> population switched off for the structure, loop went on to DONE.  Fix from the log: members with an identical sign pattern donated the same crossover moves twice; `run_population` now polishes each distinct donor pattern once (retest job 1713092 passed 20:07: 5 patterns polished instead of 10).  7Be attempt 4 (job 1712561) started 19:10.
- 2026-11-08 16:30  POPULATION stage built (DeBoer: "go ahead and build the restart + crossover stage into the drive"): `Campaign.run_population` (restarts of the incumbent with random high-exposure flips, sign-locked then released polishes to convergence, control, crossover passes between members, winner verified), CLI `population`, drive state POPULATION after SIGN (budget restarts_per_cycle 4 / restart_nfev / crossover_passes 2 / population_rounds_max 3; stop population_gain_rel_min 1e-3; an improvement sets SIGN_POST; a no-gain round switches it off until a structure change).  Dry test and 13N test extended.  Verification: 7Be attempt 4 (pert4 from ref2, same 8 flips) with the stage on.

- 2026-11-08 13:10  7Be attempt-3 post-mortem (bench dir diag3.log): oracle with the reference's 17 signs polishes toward the reference (5334.8, distance 0); no single/pair/channel/group flip gains > 2.6 even with 600-evaluation polishes.  The sign pattern is the barrier and local proposals cannot cross it; a population + crossover stage is the method change to test (next: perturbed restarts of pert3 polished in parallel, crossover between them with union_nfev 600).

- 2026-11-08 12:40  7Be benchmark attempt 3 (job 1711152, 1.26 node-hours): drive DONE with zero decisions after six cycles (24 polishes of 600 evaluations, sign rounds deferred until convergence, then 4 rounds with 0 accepted) at 6002.6, 13.5 % above the target, sign distance 17 -- NOT recovered.  The polish from the 8-flip start itself undid six flips and moved fifteen other amplitudes through zero (a third basin); single/pair flips on the 40/80/150 screen do not leave it.  Phase 2 criterion not met by the METHOD (the loop machinery is fine).  Post-mortem job 1711661 (bench dir diag3.py): oracle signs + single flips with long polishes, to choose between longer screens and multi-flip moves.

- 2026-11-08 11:15  7Be benchmark attempt 2 (job 1711062): the reference reproduces (init's new check: 5088.801 vs 5088.785); the drive ran three cycles to DONE with no decision but ended at 6610, 25 % above the target 5290, sign distance 14, every one of 18 sign rounds accepting nothing while the polishes still gained 1-2 % per 300 evaluations -- the sign rounds ran on an unconverged incumbent, which the skill's step order forbids.  NOT recovered.  Drive change: `stop_rules.sign_after_converged_polish` (default on) defers sign rounds until TIGHTEN left on convergence rather than on its budget (4945161).  Attempt 3 queued (job 1711152, pert3): perturbed start polished 600, polish 600 x <= 6 per cycle, <= 8 cycles / 6 node-hours, search top_k 8 with local release 1 MeV.  Whatever attempt 3 gives, the method result stands on its own: this is the first run of the recovery benchmark on 7Be (skill section 6: run it once per reaction before trusting the method there).

- 2026-11-08 10:20  `rmfit drive` verification.  13N end to end (job 1709427, 22.9 min, 3 shards): every state ran, DONE, all checks pass; REPRODUCE compared the seed with the copied chiSquared.out; DATASET_OFF queued the skowronski_luna_bgo question (extra recovery 9.7 %) with default keep.  7Be tier-1 benchmark attempt 1 (`6Li+p/3He+a/AZURE2_evaluation/11-8-26_drive_bench`, job 1709448): the loop ran as designed (perturbed 5.7e7 -> 6706 in 26 min, six sign rounds, stop rule after two without an acceptance, DONE, no decision) but the reference campaign was built on the wrong objective: `ignore_externals: false` gave chi2 6879 for the archived 5089, and caps 3 / 100 cannot hold a reference whose 30 MeV poles sit at theta2 up to 2e6.  Two fixes: `init` compares the seed's plain chi2 with a chiSquared.out in the base model's output directory and warns (566b893); `drive` records the cycle start objective on a pre-existing campaign (2b7d502; CYCLE had stopped after one pass at 0 %).  Attempt 2 queued with the reproducing flags and caps 1e5 / 1e7 (job 1711062, `run_crc_bench2`).  Lesson for the benchmark suite (Phase 3): the reference objective is re-measured on the pinned engine AND checked against the archived chiSquared.out before any perturbation; caps come from the reference's own theta2 table.

- 2026-11-08 01:30  Phase 2.1 `rmfit drive` built: `drive.py` (state machine, 19 states, `drive_state.json`, `DRIVE.md`, decisions wired through `Driver.ask`), `templates/run_crc_drive.csh` (one leg per job, self-resubmit on CONTINUE, engine guard), CLI `drive` (`--base/--sav` first call, `--dry-run`, `--max-minutes`, `--local`, `--state`, `--reset`, `--write-job`).  Engine-free test passes (build states on a 13N copy, refusal / STOP_DRIVE / decisions / persistence, loop counters on a stub campaign); 13N end-to-end on the queue (job 1709427, tests/_queue_drive).  Next: run it on a live testbed (7Be tier-1 from a perturbed start, then 10B+a s5 from its spec_draft) and encode the 2.2 structure-search defaults.

- 2026-11-07 23:30  Phase 1.4 DONE: the evaluator's standing rules (retrospective section 5) and the recurring traps
  written where sessions read them -- archive CLAUDE.md "Standing rules from the evaluator" (frame first, minimal bug
  reproduction, audit before fitting, data treatment with the evaluator, scope, norms, structure search, GUI/in-place
  editing and copied-.azr paths, log axes, cluster limits, acknowledgement wording); azure2-eval Golden rules gained
  Ex-vs-E_cm, the minimal-reproduction rule and the copied-.azr paths (held checkout + branch skills/agentic-2026-11-07).
  Phase 1 complete.  Next: Phase 2, `rmfit drive` (built 2026-11-08, entry above).

- 2026-11-07 23:00  Phase 1.3 `rmfit review` built, tested (engine-free, 13N output), calibrated on the archived 13C+a and
  17O+a cases (see the 1.3 entry above).  Not a decision maker: every flag is a candidate with the number behind it, in
  CLAUDE.md's per-point wording.  Engine path (`rmfit <dir> review [--grid-check]`) first run on 10B+a s5 (job 1708099 + login node; it caught the
  closed-channel ANC-as-width bug, fixed in ab6577f).  Remaining in Phase 1: 1.4 (rules into docs).
- 2026-11-07  Phase 0 built: git (7539e88 baseline, 7ef9e24 engine pin), `enginepin.py`, job-template guard,
  `install_shared.sh`, this file.  Sharded fixture job queued (tests/_queue_sharded).
- 2026-11-07 15:30  Phase 1a built: `spec.py` (+ `templates/SPEC_TEMPLATE.json`, `rmfit spec check|render|derive`, `init --spec`,
  spec_sha), `decisions.py` (`DECISIONS.md`, `rmfit decisions|decide`, level-add adoption gated by `pre_authorized.adopt_level`),
  `audit.py` (`rmfit audit` -> AUDIT.md).  Regression: the audit reproduces 13C+a 10-2-26 (745 zero-width channels, nominal
  norms, Cierjacks 0.02 % row = ~11,400 points), 3H+d Conner (FLAG column), 12C+p (normError fraction).  Live run on
  10B+a s5: 0 HIGH, 2 MEDIUM.  Tests test_spec_decisions / test_audit pass on the login node; test_campaign_spec_13n queued.
  Still Phase 1: `rmfit review` (1.3) and the audit `--kind input|data|literature` subagent templates (1.2b).
- 2026-11-07 16:25  Phase 1.2b built: `audit_subagent.py` + `templates/audit_*.md` (`rmfit <dir> audit --kind input|data|literature|all`
  -> `audits/<kind>/PROMPT.md` with the segment table, active files, machine findings, spec roles / standing decisions,
  answered DECISIONS and the readme head; `--findings` / `--status KIND N confirmed|rejected|decision` on the subagents'
  `FINDINGS.md`).  test_audit_subagent.py PASS (login node).  First prompts written for 10B+a s5 (audits/).
  First run on 10B+a s5 (three sonnet subagents, 6-15 min each): input 0/3/5, data 1/3/5, literature 0/5/2 (HIGH/MEDIUM/LOW).
  Two top findings verified by the session: the June 9.7 % / March 3 % scale is nowhere in the objective (fixed norms, scale
  terms removed from the covariance -- the recorded treatment, but the spec note said otherwise and was corrected), and the
  MANA HPGe p3/a1 rows enter at ~1.2 % effective sigma against 3.2 % in the file (HIGH, for DeBoer).  The harness refuses
  subagent report writes: they return the report as text and the session saves it (template says so now).
- 2026-11-07 16:20  Fixture job 1700560: enginepin, keys, spec, audit, campaign_13n, levelscan PASS; test_campaign_spec_13n
  FAILED: the spec gate logged accept-pending and did not adopt, but the returned dict / ledger row / readme note were built
  before the gate ran and still said "accept".  Gate moved ahead of them in `_run_level_add`; rerun queued (job 1703121,
  tests/_queue_spec/spec.log).  Skill now in this repository (297e17b, pushed): edit it here.
  16:26 job 1703121: test_campaign_spec_13n PASS on the node (level add -> accept-pending, D-002 queued, not adopted; 811 s).
- 2026-11-07 13:00  install_shared.sh verified with positive/negative controls (`--check-script`); two detector bugs fixed
  (pipefail + grep -q; pinned-root rule).  Skill section-7 note pushed to AZURE2 dev 4d16764; since 16:10 the skill lives in THIS repository (`.claude/skills/rmfit-campaign/SKILL.md`, 297e17b).
  Spec drafts for 10B+a s5 and 13C+a region D written (Phase 1 input).  Fixture job 1700297: enginepin + keys PASS on the
  node; campaign + levelscan tests running.
