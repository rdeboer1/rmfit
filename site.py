"""Site settings: values that belong to a cluster site or a user, not to a campaign.

Precedence: environment variable > site file > default.  The site file is ``$RMFIT_SITE`` or ``~/.rmfit/site.json``,
for example::

    {"mail": "you@example.org"}

Keys:
  mail   address for the SGE ``-M`` line of the job scripts rmfit writes (env ``RMFIT_MAIL``).  Unset: no ``-M`` line,
         so the scheduler mails the submitting user on the submit host (its own default).
"""
import json
import os

SITE_FILE_DEFAULT = os.path.join("~", ".rmfit", "site.json")


def site_file() -> str:
    return os.path.expanduser(os.environ.get("RMFIT_SITE") or SITE_FILE_DEFAULT)


def load() -> dict:
    """The site file's settings ({} when it is absent); a malformed file raises with its path."""
    path = site_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except ValueError as e:
        raise ValueError(f"rmfit site file {path}: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"rmfit site file {path}: expected a JSON object")
    return data


def job_mail() -> str:
    """The job mail address: ``RMFIT_MAIL``, else the site file's ``mail``, else '' (none)."""
    return (os.environ.get("RMFIT_MAIL") or str(load().get("mail") or "")).strip()


def mail_line() -> str:
    """The SGE ``-M`` line for a job script, or a comment saying how to set one."""
    addr = job_mail()
    if addr:
        return f"#$ -M {addr}"
    return "# no -M line: set RMFIT_MAIL or \"mail\" in ~/.rmfit/site.json (rmfit/site.py); SGE mails the submitting user"
