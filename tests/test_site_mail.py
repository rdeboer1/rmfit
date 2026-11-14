#!/usr/bin/env python3
"""The job mail address is a site setting (rmfit/site.py), not a hard-coded domain.

  (a) RMFIT_MAIL wins over the site file; the site file ($RMFIT_SITE) is used without it; with neither there is no
      -M line, only a comment; a malformed site file raises with its path;
  (b) the three job-script writers -- Campaign.write_job_script (init), drive.write_job_script (drive --dry-run) and
      bench.write_job -- write that line and leave no template field behind.
Engine-free, seconds.  Run:  python3 rmfit/tests/test_site_mail.py"""
import json, os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from rmfit import site                                   # noqa: E402

FAILS = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


def writers(tmp):
    """The three generated scripts' text."""
    from rmfit.campaign import Campaign
    from rmfit import drive
    from rmfit.spec import FitSpec
    from rmfit.bench import bench
    out = {}
    cdir = os.path.join(tmp, "X+p", "camp"); os.makedirs(cdir, exist_ok=True)
    c = object.__new__(Campaign); c.dir = cdir; c.cfg = {"base_azr": "x.azr"}
    out["campaign"] = open(c.write_job_script(overwrite=True)).read()
    spec = FitSpec({"reaction": "X+p", "nshards": 4})
    out["drive"] = open(drive.write_job_script(cdir, spec, {}, overwrite=True)).read()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    case = bench.load_case(os.path.join(here, "bench", "cases", "13N_tier0.json"))
    case["_base"] = tmp
    out["bench"] = open(bench.write_job(case, next(iter(case["runs"])))).read()
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="rmfit_site_mail_")
    saved = {k: os.environ.pop(k, None) for k in ("RMFIT_MAIL", "RMFIT_SITE")}
    try:
        sf = os.path.join(tmp, "site.json")
        os.environ["RMFIT_SITE"] = os.path.join(tmp, "absent.json")
        check("(a) neither: no -M line", site.job_mail() == "" and site.mail_line().startswith("# no -M line"))
        json.dump({"mail": "file@example.org"}, open(sf, "w"))
        os.environ["RMFIT_SITE"] = sf
        check("(a) site file", site.mail_line() == "#$ -M file@example.org")
        os.environ["RMFIT_MAIL"] = "env@example.org"
        check("(a) RMFIT_MAIL wins", site.mail_line() == "#$ -M env@example.org")
        del os.environ["RMFIT_MAIL"]
        open(sf, "w").write("{not json")
        try:
            site.load(); bad = False
        except ValueError as e:
            bad = sf in str(e)
        check("(a) malformed site file raises with its path", bad)

        json.dump({"mail": "file@example.org"}, open(sf, "w"))
        for name, text in writers(tmp).items():
            mlines = [l for l in text.splitlines() if l.startswith("#$ -M")]
            check(f"(b) {name}: the only -M line is the site file's", mlines == ["#$ -M file@example.org"])
            check(f"(b) {name}: no template field left", "{mail_line}" not in text and "{email}" not in text)
        os.environ["RMFIT_SITE"] = os.path.join(tmp, "absent.json")
        for name, text in writers(tmp).items():
            check(f"(b) {name}: no -M line without a setting", not any(l.startswith("#$ -M") for l in text.splitlines()))
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"{len(FAILS)} FAILED"); sys.exit(1)
    print("all site mail checks passed")


if __name__ == "__main__":
    main()
