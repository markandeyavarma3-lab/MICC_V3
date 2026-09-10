"""nullcal.py — the null calibration. Plan 3 step 6.9, Plan 2 §6.3.

WHAT THIS ANSWERS, AND WHY IT IS THE LAST THING WORTH BUILDING.

Plan 2 §6.3 fixes a participant-ranking procedure and then adds the check that
makes it honest:

    "run the identical procedure on randomly-relabelled participants (permute
     the participant column within date). If the real data yields a similar
     number of 'supported' participants as the shuffled data, there is no
     participant skill in this dataset — only variance. **That comparison is
     the headline finding, not the leaderboard.**"

Every verdict this project has reached is a negative one, and every one of them
rests on the machinery that produced it. This is the only test that interrogates
the machinery itself: point the identical pipeline at data where the answer is
known to be "nothing" by construction, and see whether it agrees. It validates
two things at once —

  1. **No participant skill.** If real and shuffled produce the same count of
     supported participants, the leaderboard is variance.
  2. **The multiplicity machinery is calibrated.** Romano-Wolf claims to control
     the family-wise error rate at 5%. Under a true null that means at most ~5%
     of permutations should produce ANY supported participant. If far more do,
     every corrected p-value this project has published is too small, and the
     negative results are the only conclusions that survive — a procedure that
     is too liberal cannot manufacture a "no".

WHY WITHIN-DATE PERMUTATION, SPECIFICALLY. Shuffling labels globally would break
the calendar: a participant active only in 2007 could be handed 2019 returns,
and the resulting null would be easier to beat than reality. Permuting WITHIN a
trade date holds fixed everything except who did the trade — the set of dates,
the number of deals on each date, and the return attached to each deal. It also
leaves every participant's total event count exactly unchanged, so the
eligibility filter selects the same names under every permutation. The only
thing destroyed is the association between a participant and an outcome, which
is precisely the thing being tested.

THE ELIGIBLE POPULATION IS 7, NOT "A FEW HUNDRED". Plan 2 §6.3 step 1 expects
the >=30-matured-event filter to reduce 27,417 names "to a few hundred".
Measured here, on outcomes vs CHAR_MATCHED at the twelve-month horizon, it
reduces them to **seven**; the short horizons reach ten. The plan's estimate
predates the participation cap (0038), the EQ-only correction (0045), the
suspension exclusion (0055), and CHAR_MATCHED's 74% coverage, each of which cut
the matured population again. A leaderboard of seven is not a leaderboard, and
that is reported rather than worked around.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import duckdb

from src.common.paths import research_db
from src.research import multiplicity

#: Plan 2 §6.3 step 1. A participant needs this many MATURED events at the
#: horizon before it is testable at all.
MIN_EVENTS = 30

#: Months a monthly-cohort t-statistic needs before it means anything. NOT part
#: of §6.3 — the plan sets its bar on EVENTS — and it is not applied as a filter
#: here, because changing a pre-specified procedure after seeing its output is
#: the thing this project exists to refuse. It is reported so the conflict is
#: visible: §6.1 requires the monthly collapse for independence, §6.3 requires
#: 30 events, and 30 events concentrated in one month is ONE observation.
MIN_MONTHS = 12

#: Plan 2 §6.3 step 6. "Supported" means FWER-adjusted p below this, and
#: nothing else.
ALPHA = 0.05

#: §6.3 step 4. Ten thousand for the real run, as specified.
BOOTSTRAP = 10_000

#: Permutations of the participant column. Each is a complete re-run of the
#: procedure. 1,000 estimates P(any supported) to about +-0.7pp at a true 5%.
#: It was 200 while the bootstrap was a Python loop; vectorising it made 1,000
#: cost under a minute, and the extra resolution is the difference between
#: "consistent with 5%" and a number you can actually compare to 5%.
PERMUTATIONS = 1_000

#: Bootstrap draws inside each PERMUTATION, reduced from BOOTSTRAP so that 200
#: full re-runs finish. The bootstrap error on a p-value near 0.05 is about
#: 0.5pp at this size — an order of magnitude below the effect being measured,
#: and it is declared here rather than hidden as a tuning constant.
PERMUTATION_BOOTSTRAP = 2_000

EVENTS_SQL = """
    SELECT UPPER(TRIM(r.client_name_raw)) AS participant,
           CAST(cl.trade_date AS VARCHAR)  AS tdate,
           strftime(cl.trade_date, '%Y-%m') AS ym,
           b.relative_return                AS ab
    FROM deal_forward_outcomes o
    JOIN outcome_benchmark_returns b
      ON b.outcome_id = o.outcome_id AND b.benchmark_id = 'CHAR_MATCHED'
    JOIN institutional_deals_clean cl ON cl.deal_id = o.deal_id
    JOIN institutional_deals_raw  r  USING (raw_deal_id)
    WHERE o.horizon_sessions = {sessions}
      AND o.exit_reason = 'HORIZON'
      AND b.relative_return IS NOT NULL
"""


@dataclass
class Calibration:
    horizon_sessions: int
    n_eligible: int
    n_events: int
    n_months: int
    real_supported: int
    real_min_p: float
    #: Distinct months each eligible participant is present in, ascending. The
    #: single most important number in this output — see `render`.
    months_present: list[int] = field(default_factory=list)
    #: Participants with enough months for a monthly-cohort statistic at all.
    testable: int = 0
    perm_runs: int = 0
    perm_any_supported: int = 0
    perm_supported_counts: list[int] = field(default_factory=list)
    leaderboard: list[tuple[str, int, float, float]] = field(default_factory=list)

    @property
    def perm_rate(self) -> float:
        return self.perm_any_supported / self.perm_runs if self.perm_runs else 0.0

    def render(self) -> str:
        out = [
            f"  horizon {self.horizon_sessions}s   "
            f"{self.n_events:,} matured events, {self.n_months} months, "
            f"{self.n_eligible} eligible participant(s) at >={MIN_EVENTS} events",
            "",
            f"  REAL       supported {self.real_supported}   "
            f"(smallest FWER-adjusted p = {self.real_min_p:.4f})",
            f"  SHUFFLED   {self.perm_any_supported} of {self.perm_runs} permutations "
            f"produced any supported participant = {self.perm_rate:.1%}",
            "",
            f"  MONTHS PRESENT per eligible participant: {self.months_present}",
            f"  {self.testable} of {self.n_eligible} have the {MIN_MONTHS} months a "
            f"monthly-cohort statistic needs; the rest score 0 by construction.",
        ]
        return "\n".join(out)


def _cohorts(rows) -> dict[str, dict[str, list[float]]]:
    """participant -> month -> [abnormal returns]."""
    out: dict[str, dict[str, list[float]]] = {}
    for participant, _tdate, ym, ab in rows:
        out.setdefault(participant, {}).setdefault(ym, []).append(ab)
    return out


def _stat(monthly: list[float]) -> float | None:
    """Studentised mean of the monthly cohort means.

    Monthly collapse first (decision 0021 and Plan 2 §6.1): overlapping events
    inside a month are not independent observations, and averaging them before
    the t is what stops a participant with forty deals in one month from
    counting as forty months of evidence.
    """
    n = len(monthly)
    if n < 2:
        return None
    mean = sum(monthly) / n
    var = sum((v - mean) ** 2 for v in monthly) / (n - 1)
    if var <= 0:
        return None
    return mean / math.sqrt(var / n)


def _panel(cohorts: dict[str, dict[str, list[float]]],
           months: list[str], eligible: list[str]):
    """(n_months x n_eligible) matrix of monthly cohort means, NaN where absent.

    Built once per arm so the bootstrap is array arithmetic rather than a
    dictionary walk. 200 permutations x 2,000 draws x 7 participants x 226
    months is 632M inner operations; in pure Python that is half an hour, and a
    calibration nobody waits for is a calibration nobody runs.
    """
    import numpy as np

    idx = {m: i for i, m in enumerate(months)}
    a = np.full((len(months), len(eligible)), np.nan)
    for j, p in enumerate(eligible):
        for m, vals in cohorts[p].items():
            i = idx.get(m)
            if i is not None:
                a[i, j] = sum(vals) / len(vals)
    return a


def _studentised(sample):
    """Column-wise studentised mean, ignoring NaN. Returns 0 where undefined.

    A column with fewer than two present months has no dispersion to divide by;
    0 is the honest statistic there, not a large one, and it keeps the candidate
    in the family so the multiplicity correction still counts it.
    """
    import warnings

    import numpy as np

    # An all-NaN column is expected: a participant with no deal in any sampled
    # month. numpy reports it through `warnings`, not `errstate`, and the value
    # is handled explicitly two lines down.
    with np.errstate(invalid="ignore", divide="ignore"), \
            warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        n = np.sum(~np.isnan(sample), axis=-2)
        mean = np.nanmean(sample, axis=-2)
        var = np.nanvar(sample, axis=-2, ddof=1)
        t = mean / np.sqrt(var / n)
    return np.nan_to_num(np.where(n >= 2, t, 0.0), nan=0.0,
                         posinf=0.0, neginf=0.0)


def _run_procedure(cohorts: dict[str, dict[str, list[float]]],
                   months: list[str], eligible: list[str],
                   bootstrap: int, rng: random.Random) -> tuple[list[float], list[float]]:
    """Plan 2 §6.3 steps 3-5, returning (statistics, FWER-adjusted p-values).

    THE BOOTSTRAP RESAMPLES WHOLE MONTHS, AND THE SAME MONTHS FOR EVERY
    PARTICIPANT. §6.3 step 4 says so, and the reason is that participants trade
    the same market in the same months: drawing independent months per
    participant would destroy the cross-sectional dependence and make the
    maximum statistic look smaller than it is, which is the direction that
    invents winners. One index draw per row, shared across columns, is what
    preserves it.
    """
    import numpy as np

    panel = _panel(cohorts, months, eligible)
    observed = _studentised(panel)

    # CENTRED ON THE OBSERVED MEAN: this is what imposes the null. Without it
    # the bootstrap describes the data rather than the null, and every adjusted
    # p comes out far too small.
    centred = panel - np.nanmean(panel, axis=0)

    seed = rng.randrange(2**32)
    gen = np.random.default_rng(seed)
    n_months = len(months)
    draws = np.empty((bootstrap, len(eligible)))
    # Chunked so the gathered array stays bounded regardless of B.
    step = max(1, 2_000_000 // max(1, n_months * len(eligible)))
    for lo in range(0, bootstrap, step):
        hi = min(lo + step, bootstrap)
        idx = gen.integers(0, n_months, size=(hi - lo, n_months))
        draws[lo:hi] = _studentised(centred[idx])

    adjusted = multiplicity.romano_wolf(
        [float(v) for v in observed], [[float(v) for v in row] for row in draws])
    return [float(v) for v in observed], adjusted


def _permute_within_date(rows: list[tuple], rng: random.Random) -> list[tuple]:
    """Shuffle the participant column inside each trade date.

    Every participant keeps its exact event count, so the eligibility filter
    selects the same names under every permutation and the two arms of the
    comparison are testing the same population. The only thing destroyed is
    which participant owns which outcome.
    """
    by_date: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_date.setdefault(r[1], []).append(i)
    out = list(rows)
    for idxs in by_date.values():
        labels = [rows[i][0] for i in idxs]
        rng.shuffle(labels)
        for i, lab in zip(idxs, labels):
            r = rows[i]
            out[i] = (lab, r[1], r[2], r[3])
    return out


def run(sessions: int = 252, env: str | None = None,
        permutations: int = PERMUTATIONS, seed: int = 20260910) -> Calibration:
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        rows = con.execute(EVENTS_SQL.format(sessions=sessions)).fetchall()
    finally:
        con.close()

    cohorts = _cohorts(rows)
    counts = {p: sum(len(v) for v in mm.values()) for p, mm in cohorts.items()}
    # Step 2: N is fixed HERE, before any statistic is computed, and it is the
    # same N for the real arm and every permutation.
    eligible = sorted(p for p, n in counts.items() if n >= MIN_EVENTS)
    months = sorted({r[2] for r in rows})
    if not eligible:
        raise RuntimeError(
            f"no participant reaches {MIN_EVENTS} matured events at {sessions}s")

    rng = random.Random(seed)
    _, adj = _run_procedure(cohorts, months, eligible, BOOTSTRAP, rng)
    real_supported = sum(1 for p in adj if p < ALPHA)
    board = sorted(
        ((eligible[i], counts[eligible[i]],
          sum(sum(v) / len(v) for v in cohorts[eligible[i]].values())
          / len(cohorts[eligible[i]]), adj[i])
         for i in range(len(eligible))),
        key=lambda t: t[3])

    perm_counts: list[int] = []
    for k in range(permutations):
        prng = random.Random(seed + 1 + k)
        shuffled = _permute_within_date(rows, prng)
        sc = _cohorts(shuffled)
        _, padj = _run_procedure(sc, months, eligible, PERMUTATION_BOOTSTRAP, prng)
        perm_counts.append(sum(1 for p in padj if p < ALPHA))

    mp = sorted(len(cohorts[p]) for p in eligible)
    return Calibration(
        horizon_sessions=sessions,
        n_eligible=len(eligible),
        n_events=len(rows),
        n_months=len(months),
        real_supported=real_supported,
        real_min_p=min(adj),
        months_present=mp,
        testable=sum(1 for m in mp if m >= MIN_MONTHS),
        perm_runs=len(perm_counts),
        perm_any_supported=sum(1 for c in perm_counts if c > 0),
        perm_supported_counts=perm_counts,
        leaderboard=board,
    )


def main() -> int:
    print("NULL CALIBRATION — Plan 3 step 6.9, Plan 2 §6.3")
    print("  the identical procedure on participant labels shuffled within date")
    print("  'That comparison is the headline finding, not the leaderboard.'")
    print()
    c = run()
    print(c.render())
    print()
    print("  leaderboard (reported in full, per §6.3 step 5 — not only winners)")
    print(f"    {'participant':<44}{'n':>6}{'mean ab':>10}{'adj p':>9}")
    for name, n, mean_ab, p in c.leaderboard:
        print(f"    {name[:43]:<44}{n:>6}{mean_ab:>9.2%}{p:>9.4f}")
    print()
    if c.real_supported == 0:
        print("  VERDICT: no participant is supported at FWER 5%. The leaderboard")
        print("  above is variance, and the ordering in it carries no information.")
    else:
        print(f"  VERDICT: {c.real_supported} supported — compare against the "
              f"shuffled rate above before reading anything into it.")
    print()
    print(f"  Romano-Wolf claims FWER {ALPHA:.0%}. Under labels that carry no")
    print(f"  information by construction it produced a supported participant in")
    print(f"  {c.perm_rate:.1%} of {c.perm_runs} permutations. A rate far above")
    print(f"  {ALPHA:.0%} would mean the correction is too liberal and every")
    print(f"  adjusted p this project has published is too small.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
