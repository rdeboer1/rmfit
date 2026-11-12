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
  2026-11-12: + `level-close-width` (same-J^pi pair closer than 10 % of the narrower width, MEDIUM, report only; `--close-fraction`,
  budget `close_fraction`); spacing ENFORCEMENT (centroid + bounded gap) not built, its scale is DeBoer's to choose.
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
  ML superset (pseudo-data, no reference fit).  12C+p tier 1 PASS exact 2026-11-10 (26,368 -> 12,040 via DeBoer's background-gamma branch, found by the population stage in 0.06 node-hours); tier-2 case `10Bp_tier2` defined 2026-11-10 (round 8 variant A -> B): PASS exact in 1.31 node-hours (the first run, job 1719105, is VOID: the .sav's fixed values had been ignored at init; `--sav-fixed apply` since 3e57614/next); tier-3
  cases are still to be defined as case files.
- **3.2 STARTED 2026-11-09** (DeBoer: "12C+p from scratch for the L3 demo"): `12C+p/11-9-26_L3_demo/` -- base model from the TUNL
  level scheme + background poles + the 8-9-26 data segments (build_base.py), spec.json drafted by Claude with every data-treatment
  choice recorded as a standing decision for DeBoer to confirm (anchor Meyer 1976; Gerke 1966 excluded provisionally for its
  placeholder errors; two norm priors from the standing 10 % rule; theta2 cap 1.5 for the s-wave state), pre-build audit fixed the
  inherited normError fraction-vs-percent error on all 111 segments; one job (1718547, 8 slots, <= 20 node-hours) runs the build phase
  and the loop with no chat.
- 3.3 DONE 2026-11-10: skill section 9 (1,865 lines, 117 entries) -> `rmfit-campaign/HISTORY.md` verbatim with a dated index in
  SKILL.md; "First fits" is the drive's build-state list (one line per item, the enforcing state named); section 7 rewritten from
  `bench/results.tsv` and the L3 demos (table + what it says + what is still a limit); section 8's long gotchas compressed to
  one-liners; every displaced paragraph is in HISTORY.md under "Relocated from SKILL.md" (nothing deleted).  SKILL.md 721 lines.
- **Recovery yardstick (DeBoer 2026-11-09, after the 7Be attempt-4 post-mortem):** a drive run from a degraded start "recovers" the reference when (1) its data chi2 is <= the reference's, (2) its penalized objective is within 0.5 % of the reference's, (3) `rmfit review` raises no flag the reference does not have, and (4) zero wait decisions were asked.  The old "objective within 1e-4" is kept as a secondary column (`exact`): on 7Be it selects one of at least two near-degenerate background-pole configurations (bench readme 2026-11-09 06:05/06:15), which is not a property of the loop.
### Phase 4 -- UQ as the standard last stage (~5 agent-days)
`rmfit uq`: export -> Park if saturated / two-channel levels -> centred priors from the spec -> emcee/NUTS ->
automated R-hat / tau gates -> linear vs sampled comparison -> band.  Validate on 7Be and d+t.
Built 2026-11-10 (`uq.py`, `rmfit <dir> uq`, drive state UQ when `spec.uq.enabled`): EXPORT -> SETUP (Park's J from a Park
session on the exported file; J < 0.01 levels held; Laplace = Gauss-Newton covariance at the mode) -> SAMPLE (pyazr NUTS,
dense metric from the Laplace, checkpointed) -> GATES (split R-hat, ESS, divergences, E-BFMI, sd ratio; one automatic
re-run with longer chains) -> BANDS (linear vs sampled on spec grids or the model's own energy scans) -> REPORT (`UQ.md`).
Error inflation is reported, never applied; priors and failed-gate chains go to the evaluator (decision `uq-gates`).
Fixture: `tests/test_uq_13n.py` on the queue (`tests/_queue_uq/run_crc_uq_test`, ~8 min on 4 slots).  7Be validation:
`6Li+p/3He+a/AZURE2_evaluation/11-10-26_uq/` (job 1725304): PASS 2026-11-11 -- gates automatic (R-hat 1.003, ESS >= 826,
0.57 % divergent), S34(0) = 0.544 +- 0.007 keV b (1.24 %; sampled = linear within 4 %) against CSEWG 0.56 +- 0.01 on the
externals-on model: central value within 1.3 sigma combined, width 0.6 x -- a model difference (externals), DeBoer's call.
d+t: in progress 2026-11-12 (`3H+d/11-12-26_uq/`, the archive's V1-at-9-fm model, d+t data alone).  Two findings before a
valid run: (1) with no bounds the d+t data leave the 3/2+ background pole's amplitudes unbounded (emcee acceptance 0.11,
width_2_2 beyond its Wigner limit in 67 % of draws; NUTS R-hat 28-42) -- the stage now samples inside the campaign's
theta^2 box by default (`bounds: "policy"`, commit ce08b8d); (2) the first bounded run froze (R-hat 9e7, step 5e-8) because
the metric in u came from the unbounded Laplace, wide along the pole -- the metric is now the Hessian of -log p(u) at the
mode (commit 72e6fde).  Reference on the same density: bounded emcee (64 x 100000) S(40 keV) = 25.67 [25.43, 25.93] MeV b
vs the archive's 25.75 [25.50, 25.98] (Haesner in).  Result of the bounded NUTS run (job 1731806): see the progress log.

## Open items not on the roadmap
Competing-resolution test for near-duplicate levels; differential-convolution shards; single-session-only kinds
(density, Doppler, thickness, screening) in shards; `structure add` exit status on a failed scan.

## Progress log

- 2026-11-12 09:30  Phase 4 d+t validation, two stage defects found and fixed before a valid run (`3H+d/11-12-26_uq/readme`).
  (a) Unbounded posterior: `rmfit uq` sampled the objective with no box; on d+t the data alone do not bound the 3/2+
  background pole (unbounded emcee 1731011: width_2_2 beyond its Wigner limit in 67 % of draws, tau 900-2100; NUTS 1731010:
  R-hat 28 / 42, ESS 2, chains at log p -7500).  The archive's d+t MCMCs are uniform within the Wigner limits, rmfit's polish
  ran in the theta^2 box -- the stage now samples inside that box by default (`uq.bounds` policy | none, `uq.theta2_cap`
  for a bare fit; BoundedTarget, x = c + h tanh u with the Jacobian; ce08b8d, 5a0b72c; test_uq_bounds.py; fixture jobs
  1731094 (nan start, fixed) and 1731128).  (b) Frozen chains in the box (job 1731435, killed): the metric in u was the
  unbounded Laplace / (dx/du)^2, 3400 in u for width_2_2 where the truncated posterior has sd ~1; step size 5e-8, R-hat 9e7.
  metric_u is now the inverse Hessian of -log p(u) at the mode (D C^-1 D + Jacobian curvature + the gradient term of an
  edge-held mode, bounded sd <= 1, Woodbury on the bounded block, g0 saved by SETUP; starts jittered in u; 72e6fde; unit
  test with an edge-held ridge; fixture jobs 1731781, 1731795 PASS).  7Be is unaffected by both (caps 1e5 / 1e7: no box).
  Bounded emcee reference on the identical density (1731092, 64 x 100000, chain_bounded.h5): S(40 keV) 25.672 [25.429,
  25.925], tau 1074-4293, width_2_2 within 2 % of its limit in 5.7 % of draws (archive 4.9 %).  Bounded NUTS: job 1731806.

- 2026-11-11 05:50  Phase 4 verified on 7Be (job 1725304, 24 slots, 4.8 h of sampling): `rmfit uq` PASS with no human input.
  Setup found the 10-24-26 study's four saturated poles again (J <= 2e-3, 18 parameters held), sampled 177 with the 123 norms;
  4 chains x (1000 + 2000) at 44.6 gradients per draw; gates split R-hat 1.003, ESS 826 .. 9641, divergent 0.57 %, E-BFMI
  0.99; sd(NUTS)/sd(Laplace) 0.54 / 1.00 / 1.80.  Bands: S34(0) = 0.544 +- 0.007 keV b linear, sampled [0.537, 0.552] (half-
  width/linear 1.04-1.14, offset -0.04 sigma); 6Li(p,g) 93.1 +- 2.9 eV b; 6Li(p,a) 3.50 +- 0.06 MeV b.  Against CSEWG
  0.56 +- 0.01 (externals on): 2.4 % lower, 1.3 sigma combined, band 0.6 x as wide -- the model (externals ignored, Elwyn fix,
  norms sampled), not the sampler; the number for the evaluation is DeBoer's (externals on or off).  One mistake of mine: the
  first band run had the pair keys swapped (pair 1 is 3He+a); caught because the "6Li(p,a)" grid read zero (closed channel),
  fixed in uq.json and BANDS + REPORT rerun in 1 min on the login node (uq_state.json with the two stages removed resumes
  there -- worth a `--redo bands` flag).  Cosmetic engine item: pyazr's LevelKey prints "@?MeV" for the ground state.
  Phase 4 remaining: d+t validation (3H+d/11-9-26_MCMC_V1_9fm, S(40 keV) = 25.75 [25.50, 25.98]); drive UQ state end to end
  on the 13N drive test.
- 2026-11-10 22:50  Phase 4 built: `rmfit uq` (uq.py, cli `uq`, drive state UQ, spec section `uq`, SKILL.md 3d).  Five fixture
  runs on the queue before it passed (job 1725295, all 16 checks): (1) 1724558 timed out in SAMPLE -- the 13N fixture's
  gradient costs 2.7 s with its target-integrated sets and the at-bound mode drove the trees to depth 10, so the test now
  deactivates the four thick-target sets (0.014 s per gradient), raises the theta2 cap to 10 for an interior mode and caps
  the depth at 6; (2) 1725138: the Park session refused the Brune-basis .sav, so it now takes the level parameters from the
  exported .azr (physical, basis-free) and the norms from the Brune vector -- Park objective = Brune's to 8e-10; (3) 1725248:
  no band because the fixture has no <segmentsTest>, so the test gives a spec grid; (4) 1725262: pyazr 2.10.0
  `bands.trimmed_model` copies intEC.dat into a workdir it never creates (FileNotFoundError) -- uq hands it an existing
  one (engine follow-up for the next release).  Fixture result: 2 chains x 300 in 3 min, 56 gradients per draw, R-hat 1.03,
  0 divergences, sd(NUTS)/sd(Laplace) median 1.00, 12C(p,g) band at 92 keV c.m. 0.15 % linear vs 0.14 % sampled.  Grid
  energies given to add_extrapolation are LAB (e_min 0.1 -> 0.0923 MeV c.m. for p+12C; the docstring says c.m.): a second
  engine follow-up.  7Be validation job 1725304 submitted 22:50 (`11-10-26_uq/run_crc_uq`: campaign init on the current
  engine, then 4 chains x (1000 + 2000) on 24 slots, 195 parameters with the norms, depth cap 8).  .sav audit final tally in the
  10:30 entry below.
- 2026-11-10 10:30  Tier-2 bench PASS, exact (10B+p round 8, `bench/results.tsv`): from the 2022-sign variant A (6,215.5) the drive
  reaches DeBoer's variant B to 1e-9 (5,676.092 on this engine; reference polished from 5,716.4; sign distance 0, data chi2 equal)
  in 0.96 node-hours -- sign rounds found nothing (68 proposals), the population stage's crossover found the two 9/2+ flips --
  then DONE after a no-gain cycle 2 at 1.31 node-hours (jobs 1719612, 1719985, 1720038).  The run asked one question, twice:
  REVIEW's one HIGH flag, the 1 MeV wide 5/2+ 10.063 MeV pole spanning five unfitted peaks, which `ref/REVIEW.md` carries
  identically -- DeBoer's own final model, the region where round 8 tested the b/d/i extra levels and "no extra levels" was
  agreed.  Answered 'continue' by the supervisor with that evidence (D-002, D-003).  Three rules from it: (1) scorer: a
  review-high whose HIGH flags the reference's review carries is not a wait decision (DeBoer's "no new flag" criterion) --
  his to confirm; (2) drive: the init baseline is reviewed once (REVIEW_baseline.md) and a HIGH flag the base model already
  carried is reported, not waited on (did not apply here: the start had none); (3) drive: a flag answered 'continue' is not
  asked again in a later cycle.  And the `init --sav` convention, settled after the archive audit (`agentic/11-7-26_claude/
  sav_fixed_audit/`): the archive uses BOTH readings -- a CLI fit's param.sav holds the fixed values the fit ran with (10B+p),
  a script-built base means the .azr and seeds free values from a stale .sav (10B+a s4/s5, 125-237 fixed values apart) -- so
  the default stays the .azr's fixed values (the behaviour since the first campaign) with a WARNING giving the objective both
  ways, and `--sav-fixed apply` (bench case key `sav_fixed`) takes the CLI's reading.  Audit of all 498 campaigns
  built with a .sav seed (job 1719879, 08:57-21:55, sav_fixed_audit.tsv): 132 pairs consistent; 221 differ by a few
  bake-fixed values with the objective unchanged (84) or moved < 0.2 % (137; the 13C+a merged_ancprior_ng A-D variants
  are in this class, 6-15 values, <= 0.19 %); 29 differ by sign-flipped or re-baked fixed widths where NEITHER reading
  reproduces the logged baseline (10B+a s4/s5 level adds, 13C+a Sept-Oct level-search and merged variants, 12C+a
  9-8-26: script-built bases on engines or files that have since changed, so the audit cannot say which model they
  evaluated, and one is the tier-2 bench's own void run, the only confirmed case); 80 with the seed file deleted, 32
  whose seed no longer initializes, 4 without campaign.json.  Conclusion unchanged: no finished evaluation in the
  archive rests on an unintended fixed block; the 29 inconclusive rows are exploratory campaigns whose readmes record
  their own outcome.
- 2026-11-10 17:45  REGRESSION fixed: 896f365 had replaced the `init --nshards` argument with `--sav-fixed` instead of adding
  it, so every `rmfit init` from the shared checkout failed between 10:28 and 17:45 ("unrecognized arguments: --nshards",
  or AttributeError without it); found by the 13C(a,n) rate session (13C+a job 1723969, which ran on a private copy of
  07780df instead).  Restored, verified by an `init --nshards 3` on the 13N fixture (baseline 336,673.647, campaign.json
  nshards 3).  Lesson for the fixture rule: the 13N test of 896f365 called `Campaign.init` directly, not the CLI; a CLI
  change needs a CLI invocation on the fixture.
- 2026-11-10 08:50  Tier-2 bench job 1719105 VOID, `init --sav` fixed in 3e57614.  The drive ran to DONE (1.39 node-hours, zero wait
  decisions, 5,685 against a polished reference of 6,162) but on the wrong model: `_seed_vector` took only the FREE parameters from
  the .sav and the sharded evaluator took the fixed ones from the .azr, while AZURE2's parameter-file reader (and pyazr's
  `load_sav`) applies the file's fixed values too.  var_B.azr and fit_B/output/param.sav differ in 23 fixed background widths (up
  to 10x), so the reference initialised at 14,082 for the archived 5,716 and the start at 13,073 for 6,215.  Nothing warned: the
  reproduce check looks for output/chiSquared.out and the archived file was stored under another name.  Fix: `Campaign.
  apply_sav_fixed` compares the fixed values and, when they differ beyond the .sav's 8 digits, writes `<stem>_sav.azr` (+ .sav)
  with pyazr `save_fit` and makes it the campaign base (test `tests/test_init_sav_fixed_13n.py`); the bench copies an archived
  `chisq_out` into the output directory before init.  Rerun job 1719612 (08:48).  Open: ~40 archive campaigns (10B+a, 11B+a)
  were built with `init --sav`; most seeds were rmfit's own exports (bake writes both files consistently), but an audit job checks
  every pair (`agentic/11-7-26_claude/sav_fixed_audit/`).
- 2026-11-10 05:15  L3 demo attempt 5 (job 1719021, photon caps): DONE after 2 cycles in 1.28 node-hours, zero wait decisions,
  63,535 (attempt 4: 63,456 with photon widths of 1e9-1e16 eV).  Every background photon width is inside the 1e5 eV cap and four sit
  on it: the runaway bought 0.12 % and no physics; the cap value is the evaluator's number (spec bounds).  The course repeats
  attempt 4's: polish + signs + population stall at 210,853, SHIFTS_FREE carries the drop to 63,552, LEVELSCAN's doublet-region
  proposals marginal/unphysical, 0 HIGH / 23 MEDIUM.  Phase 3.2 is demonstrated (spec -> candidate -> review, no mid-run chat):
  what is still Claude's draft, not an evaluation, is the spec itself (nine open decisions) and the 31 unverified audit rows.

- 2026-11-10 05:01  Phase 3.3 finished (skill 804 -> 721 lines; HISTORY.md 2,052 lines): section 7 now reads from the bench
  table instead of the September limits; "First fits" names the drive state behind each of DeBoer's six items and records what the
  re-evaluation found (1, 2, 5, 6 ran on the demos; 3 and 4 report only).  Phase 3.1 tier 2: `bench/cases/10Bp_tier2.json`
  (`10B+p/11-10-26_bench_tier2/`): round 8 variant B (DeBoer's final, 5,716.4 on the pinned engine, +0.04 % vs the archived
  5,713.9) from variant A (the 2022 signs, 6,215.5): five channel signs and four magnitudes apart, 43 free + 12 norms, one
  evaluation 0.11 s -- far below the roadmap's "a day"; machine audit 0 HIGH; job 1719105.  The "no extra levels" recall run
  (the b/d/i alternatives as candidates, adopt_level off) is the follow-up.

- 2026-11-10 04:55  13N queue test job 1719011 (1adb0af): all drive 13N checks passed in 73 min on 3 slots, three legs (AUDIT
  gate -> 'skip' answered by the harness, REPRODUCE mismatch accepted, then DONE).  So the polish gate, the photon caps and the
  subagent AUDIT gate are exercised end to end on the fixture; log kept as `tests/_queue_drive/drive_1719011_pass_gate_cap.log`.
  L3 demo attempt 5 (job 1719021) at that time: cycle 1 ended at 63,552 (attempt 4: 63,456) with every background photon width
  at or below the 1e5 eV cap (three sit at the cap: 1/2+ E1, 5/2- M2, 7/2+ -- the number is DeBoer's to set), cycle 2 running.

- 2026-11-10 02:26  12C+p tier-1 bench PASS exact (job 1718963, bf30536): from Claude's 26,368 basin (100,748 in DeBoer's free scheme)
  the polish reached 24,740, 22 sign proposals accepted none, and the POPULATION crossover found the 3/2- E2 flip and polished to
  the reference 12,039.786 to all digits, sign distance 0, in 0.06 node-hours.  The roadmap's "does the method find what the human
  found" case is answered: yes, by the basin-crossing stage, in minutes.  Scorer: `pre_answered` slugs in a run (case-defined
  decisions such as audit-high on a reference with known input findings) are excluded from the yardstick and listed in the note.

- 2026-11-10 02:24  L3 demo attempt 4 (job 1718885, drive bc40f84): DONE after 3 cycles in 1.44 node-hours, zero wait decisions, final
  63,456 (attempt 2: 223,352).  The polish gate worked as designed: cycle 1 deferred SIGN/POPULATION, cycle 2's polish converged, 50
  sign proposals accepted none, the POPULATION crossover crossed to a new basin (-5.2 %, a 3/2- E2 flip) and SHIFTS_FREE took
  -9.5 % more; cycle 3 changed nothing.  LEVELSCAN's three proposals at the 3/2-/5/2+ doublet were unphysical or marginal.  The photon
  runaway recurred without the cap (background poles' gamma amplitudes 1e9-1e16 eV): attempt 5 (`12C+p/11-10-26_L3_demo5/`, job
  1719021) runs the same base with the caps; its spec skips the new audit gate by a standing decision (attempt-1 audits stand, 31
  rows unverified -- open).  13N test job 1718884 passed the gate (SIGN/POPULATION ran) but stalled on the non-blocking recall-low
  decision the harness did not know; fixed (1adb0af), rerun as job 1719011.  12C+p tier-1 bench: reference converged at 12,039.79,
  start 100,748; two one-line bugs on the way (audit-high on a reference with known findings -> answered 'accepted' by the
  supervisor; a base outside the campaign dir kept '..' in its path, 71dfa23); third submission job 1718963.

- 2026-11-10 01:10  Phase 3.3 (part): SKILL.md section 9 relocated to `rmfit-campaign/HISTORY.md` (1,865 lines, nothing deleted),
  section 9 is now a 117-line dated index; the skill is 803 lines.  Phase 3.1: 12C+p tier-1 case `bench/cases/12Cp_tier1.json`
  (reference = DeBoer's background-gamma branch of the 8-9-26 exercise at 12,044 on the 2026-11-09 engine, start = the same model with
  Claude's 26,368 level values: two photon signs and 130x smaller background gammas), `bench run` now accepts a start FILE; job
  1718930.  Running: 13N test 1718884 (bc40f84), demo attempt 4 1718885.

- 2026-11-10 01:02  Two more gaps closed while demo attempt 4 runs.  (1) Photon widths were unbounded: `default_bounds` caps
  particle amplitudes through the Wigner limit, which photon channels do not have, so attempt 3's 5/2- background pole polished
  to Gamma_gamma 1e12 eV.  `BoundsPolicy.photon_width_max_ev` (1e4) / `bg_photon_width_max_ev` (1e5) now bound |x| <=
  sqrt(Gamma_max / c), c the asymptotic factor of the transform probed at x = 1e4 per photon channel (with external capture the
  physical width is c (x - x0)^2, x0 of order 1: 13N 1/2+ E1 has x0 = 1.0, so the factor at x_ref would be 12x off); generous
  stops, not Weisskopf limits, for DeBoer to set per reaction (8f970e9; tests/test_photon_bound.py, stub + 13N engine).  (2) The
  AUDIT state now writes the three subagent audit prompts and waits for their verified FINDINGS.md before the first engine state
  (decision `audit-subagents`; rows in status 'decision' become one wait decision each; `pre_authorized.skip_subagent_audits` set
  in the bench case specs; 5b0e54d).  Neither reached attempt 4 (job 1718885, started 00:52 on bc40f84); the 13N queue test is
  resubmitted on 5b0e54d once job 1718884 (on bc40f84) reports.

- 2026-11-10 00:52  Seeding verified, next gap found: 13N test job 1718747 passed its new SEED_CHANNELS check (13 free zero channels
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

- 2026-11-09 23:35  L3 demo attempt 2 (job 1718582): DONE in 1.06 node-hours, zero wait decisions, REVIEW.md written -- the process
  works end to end on a from-scratch model -- but the candidate is poor (223,352, chi2/N 55.5) because two drive states did nothing on
  a from-scratch base: SEED_CHANNELS searched the engine's free list for zero widths, and an exact zero is never a parameter (Golden
  rule 3), so the eight background poles' 20 channels stayed out of the fit; SHIFTS_FREE polished with no shift parameter because the
  base varied no shift.  43 parameters, 1-3 sign proposals, immobile restarts.  Fixed (d4ba273): placeholders before the seed
  session (photon channels at `model.photon_seed_ev`), varyShift on at SCALE_ANCHOR where a shift uncertainty exists, dataset-off
  decision asked once.  13N test now zeroes a background channel and requires it seeded (job 1718741); attempt 3 queued
  (`12C+p/11-10-26_L3_demo3/`, job 1718742).  Neither gap was visible on 7Be or 13N, whose models carry fitted values everywhere:
  the from-scratch path had never been exercised with the engine.
- 2026-11-09 23:05  13N tier-0 bench rebuilt (job 1718612, 23 min on 3 slots): reference = the fixture polished 6 x 200 to 26,678.456; the
  4-flip start (29,709) recovered it EXACTLY (sign distance 0, +0.0 %, 0 decisions, no new flag): PASS and exact.  Tier 0 now runs
  in ~25 minutes on 3 slots as a drive regression with a real reference.  results.tsv: 7Be x 3 + 13N x 1.
- 2026-11-09 22:32  13N tier-0 bench (job 1718536, 25 min on 3 slots, DONE, 0 decisions): the drive took the 4-flip start 29,709 -> 26,678 --
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
