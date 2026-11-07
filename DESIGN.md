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

### Phase 2 -- close the loop (~10 agent-days + 2 weeks calendar)
- `drive.py` (`rmfit drive`): resumable state machine PIN_CHECK -> AUDIT -> REPRODUCE -> SPEC_CHECK ->
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
- Structure-search defaults from DeBoer's steering: broad (Gamma > 10 keV) first; data-set-by-data-set then
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
- Skill section 9 (the 1,750-line dated log) -> `rmfit-campaign/HISTORY.md`; sections 2-8 become one-line rules
  pointing at the enforcing function; section 7 rewritten from benchmark results.

### Phase 4 -- UQ as the standard last stage (~5 agent-days)
`rmfit uq`: export -> Park if saturated / two-channel levels -> centred priors from the spec -> emcee/NUTS ->
automated R-hat / tau gates -> linear vs sampled comparison -> band.  Validate on 7Be and d+t.

## Open items not on the roadmap
Competing-resolution test for near-duplicate levels; differential-convolution shards; single-session-only kinds
(density, Doppler, thickness, screening) in shards; `structure add` exit status on a failed scan.

## Progress log
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
