#!/usr/bin/env python3
"""Default J^pi of levelscan / structure add on an INTEGER-spin compound nucleus (2026-11-04, 10B+alpha).

Before this fix the default J^pi list was structure.JPI_GROUPS = 1/2+ ... 11/2- (written for 13C+alpha), and
structure.lowest_L accepted J = 1/2 with channel spin S = 3 at L = 3 (it checked only |J-S| <= L <= J+S, not that J-S
is an integer).  `rmfit levelscan` on 10B+alpha (10B 3+, every pair couples to integer J) therefore built dummy levels
with half-integer J (10B+a/11-4-26_s4_levelscan/variants/levelscan_E12p729/templates_E12p729.azr) and its screens started
from 29,709.0 instead of the incumbent 28,504.3.  Now:
  (a) lowest_L returns nothing for a J that cannot couple (J - S not an integer); valid cases are unchanged;
  (b) structure.default_jpis = the model's own active groups: 0+ ... 6- on 10B+a, half-integer on 13N;
  (c) structure.resolve_jpis raises for a J^pi no particle pair can couple to (1/2+ on 10B+a, 1+ on 13N);
  (d) levelscan.template_variant with no jpis writes one dummy per existing group, every dummy channel (pair, L, S) one
      the group already has (no new partial wave), and no half-integer level; explicit 1/2- raises;
  (e) structure.add_level_variant(jpi="1/2+") raises on 10B+a.
Fixture tests/fixtures/jpi_integer/10Ba_c8.azr = 10B+a/11-2-26_rmfit_c8_ref/10B+a.azr (candidate 13).  Pure python
(pyazr AzrModel only, no engine):
    AZURE2_ROOT=<tree> python3 rmfit/tests/test_jpi_default.py      (seconds)"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
FIX = os.path.join(HERE, "fixtures", "jpi_integer", "10Ba_c8.azr")
failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what, flush=True)
    if not cond:
        failures.append(what)


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as err:
        return str(err)
    return None


def old_lowest_L(J, parity, j1, pi1, j2, pi2):           # the pre-2026-11-04 code, for the unchanged-cases check
    out = []
    S = abs(j1 - j2)
    while S <= j1 + j2 + 1e-9:
        for L in range(0, 12):
            if abs(J - S) - 1e-9 <= L <= J + S + 1e-9 and pi1 * pi2 * (-1) ** L == parity:
                out.append((L, S))
                break
        S += 1
    return out


def main():
    import rmfit
    from rmfit.structure import (lowest_L, default_jpis, resolve_jpis, jpi_allowed, add_level_variant, LevelCandidate,
                                 jpi_parse)
    from rmfit.levelscan import template_variant
    from pyazr import AzrModel
    root = rmfit.AZURE2_ROOT
    n13 = os.path.join(root, "tests", "13N", "13N.azr")

    print("(a) lowest_L")
    check(old_lowest_L(0.5, -1, 0.0, 1, 3.0, 1) == [(3, 3.0)], "the old code gave 1/2- + (alpha 0+, 10B 3+) the wave L=3 S=3")
    check(lowest_L(0.5, -1, 0.0, 1, 3.0, 1) == [], "now: no channel for J=1/2 with S=3")
    check(lowest_L(3.0, 1, 0.0, 1, 3.0, 1) == [(0, 3.0)], "3+ on alpha + 10B: L=0 S=3")
    same, n = True, 0
    for twoJ in range(0, 15):
        for par in (1, -1):
            for (j1, p1, j2, p2) in ((0.5, 1, 0.0, 1), (0.5, 1, 0.5, -1), (0.0, 1, 3.0, 1), (1.0, 1, 0.0, 1), (0.5, 1, 1.5, -1)):
                J = twoJ / 2
                if abs((J + j1 + j2) - round(J + j1 + j2)) > 1e-9:
                    continue                                   # J cannot couple: only the new code's empty answer is right
                n += 1
                same &= lowest_L(J, par, j1, p1, j2, p2) == old_lowest_L(J, par, j1, p1, j2, p2)
    check(same and n > 50, f"every couplable (J, parity, spins) case unchanged ({n} cases)")

    print("(b) default_jpis")
    d10 = default_jpis(FIX)
    want = [f"{j}{p}" for j in range(7) for p in "+-"]
    check(d10 == want, f"10B+a: {d10}")
    d13 = default_jpis(n13)
    check(len(d13) > 0 and all("/2" in j for j in d13), f"13N: {d13}")

    print("(c) resolve_jpis")
    err = raises(resolve_jpis, FIX, ["1/2+"])
    check(err is not None and "1/2+" in err, f"10B+a 1/2+ raises: {err}")
    check(raises(resolve_jpis, FIX, ["3+", "7-"]) is None, "10B+a 3+ and a new group 7- are allowed")
    check(raises(resolve_jpis, n13, ["1+"]) is not None, "13N 1+ raises")
    check(resolve_jpis(FIX, None) == want, "None -> the model's own groups")
    lines = []
    resolve_jpis(FIX, ["3+", "7-"], log=lines.append)
    check(len(lines) == 1 and "NEW groups ['7-']" in lines[0], "log names the new group")
    check(jpi_allowed(n13, "1/2+") and not jpi_allowed(FIX, "11/2-"), "jpi_allowed")

    print("(d) template_variant")
    base = AzrModel.from_file(FIX)
    have = {}
    for lv in base.levels:
        have.setdefault(lv.jpi, set()).update((c.pair, c.L, round(float(c.S), 3)) for c in lv.channels)
    with tempfile.TemporaryDirectory() as work:
        out = os.path.join(work, "t.azr")
        var = template_variant(FIX, out, 12.72869)
        check(sorted(var["levels"]) == sorted(want), f"one dummy per existing group ({len(var['levels'])})")
        mdl = AzrModel.from_file(out)
        dummies = [lv for lv in mdl.levels if abs(lv.energy - 12.72869) < 1e-6]
        check(len(dummies) == len(want), f"{len(dummies)} dummy levels written")
        check(all(float(lv.J).is_integer() for lv in mdl.levels), "no half-integer level in the variant")
        newwave = [(lv.jpi, c.pair, c.L, c.S) for lv in dummies for c in lv.channels
                   if (c.pair, c.L, round(float(c.S), 3)) not in have[lv.jpi]]
        check(not newwave, f"no dummy channel outside its group's existing channels {newwave[:3]}")
        check(raises(template_variant, FIX, os.path.join(work, "u.azr"), 12.7, jpis=["1/2-"]) is not None,
              "explicit 1/2- raises")

        print("(e) add_level_variant")
        cand = LevelCandidate(energy=12.73)
        err = raises(add_level_variant, FIX, os.path.join(work, "a.azr"), cand, "1/2+")
        check(err is not None, "add_level_variant 1/2+ raises")
        r = add_level_variant(FIX, os.path.join(work, "b.azr"), cand, "2-")
        check(jpi_parse(r["jpi"]) == (2.0, -1) and r["channels"], "add_level_variant 2- works")

    print("FAILED: " + "; ".join(failures) if failures else "ALL OK")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
