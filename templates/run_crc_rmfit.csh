#!/bin/csh
# rmfit campaign step on one 24-core node (written by `rmfit init`).  Usage:
#   qsub run_crc_rmfit                            (runs the command in RMFIT_CMD below)
#   qsub -v RMFIT_CMD="round --rounds 2" run_crc_rmfit
#   qsub -v RMFIT_CMD="polish --nfev 150 --tighten" run_crc_rmfit
#   qsub -hold_jid <jobid> -v RMFIT_CMD="..." run_crc_rmfit   (queue behind another step)
# Every command is resumable from the ledger; STATUS.md is rewritten at the end.
# One campaign command at a time per directory; the login node is for status/report/log.

#$ -M {email}
#$ -m abe
#$ -pe smp 24
#$ -q long
#$ -N {jobname}
#$ -cwd
#$ -j y
#$ -o rmfit_sge.log

echo "Sourcing ${HOME}/.login"
source ${HOME}/.login
module load gsl/gcc/2.8
setenv OMP_NUM_THREADS 1
if (! $?RMFIT_CMD) setenv RMFIT_CMD "status"
echo "`date` rmfit ${RMFIT_CMD} on `hostname`"
cd {campaign_dir}
setenv PYTHONPATH {pythonpath}
python3 -m rmfit.cli . ${RMFIT_CMD}
echo "`date` done (exit $status)"
