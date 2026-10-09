# exp_006: does the factor-neutral residual of a wide search persist on years nobody has seen?

**Status: DRAFT / PROPOSED, 2026-10-09. Nothing registered, nothing frozen.**
It is written for the owner to argue with (decision 0086, option b).

## 1. The question

exp_005 (0085) asked whether a wide signal search works out of sample on
2016+ and returned NO_SEARCH_SKILL. Its attribution row behaved differently.
That row is the same procedure on the **partial IC net of momentum (hi_252)
and low volatility (downvol_126)**. Its selections were positive in 10 of
11 CONFIRM years:
- q 0.009;
- test IC about +0.027 (top 1), +0.029 (top 10) and +0.030 (top 100).

The ladder fixed the primary first, so that row could not count. It defined
a hypothesis: **the factor-neutral residual of a wide search persists.**

2016+ is spent. The only data on which this can be confirmed is data that
does not exist yet. So the design is forward:
1. Freeze the selection now.
2. Score it only on sessions after registration.
3. Read it once, on a date fixed in advance.

## 2. What it is not

- **Not a re-test of exp_005.** That verdict stands.
- **Not a strategy.** The test is whether the selected set's factor-neutral
  rank IC is above zero, not whether a book makes money. Costs are reported,
  never tested.
- **Not about institutions specifically.** Deal signals are among the 143
  inputs, and exp_005 found them the weakest. This is a question about
  search on Indian equities.

## 3. Power: the number that decides whether to do this

From `scripts/exp006_power.py`, run 2026-10-09. It reports dispersion only;
no mean is read (0035).
- The input is the CONFIRM atlas (2005-01-03 .. 2026-10-01; 1,929,213
  candidates; 256 blocks of 21 sessions).
- It takes the partial IC net of the two attribution factors, the top-N
  sets selected on all of it, and each set's per-block IC series.
- It uses one-sided 5% with 80% power. The effect is exp_005's recorded test
  IC; serial inflation is AR(1).

| top N | SD of block IC | lag-1 r | inflation | effect | blocks needed | years needed |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0753 | +0.21 | 1.53 | 0.0267 | 75 | 6.3 |
| 10 | 0.0767 | +0.21 | 1.54 | 0.0290 | 67 | 5.6 |
| **100** | **0.0727** | +0.21 | 1.54 | **0.0296** | **57** | **4.8** |

**About five years at the most favourable reading.** It is longer if the
effect has decayed since 2016, which exp_005's plain search did by half.
Testing all three N with BH would raise the bar further. The draft therefore
proposes **one test, top 100**, the cheapest of the three. This is chosen
from the dispersion table, not from any mean.

## 4. Proposed frozen specification

| field | proposal |
|---|---|
| experiment_id | `exp_006_forward_residual` |
| family | `TRACK_S_PROCEDURE`, the same family as exp_005; it pays one trial |
| selection | top 100 candidates by \|mean partial IC\| over every block of the CONFIRM atlas (to 2026-10-01), each read in its training sign. **The 100 keys and signs are hashed into the spec at registration.** |
| statistic | per 21-session block, the mean over the 100 of the signed partial rank IC net of hi_252 and downvol_126 (fastic, 0084), on the scan universe |
| forward window | first entry session: the first session whose 21-session forward return starts after the last training return. That is 21 sessions plus 1 of gap after 2026-10-01, about 2026-11-03. It ends at the evaluation date |
| evaluation | **one read, after 60 complete forward blocks (about end-2031).** No interim look decides anything. An interim report of block count and data health only is allowed; it shows no IC |
| test | one-sided t on the mean block IC with AR(1)-inflated SE, against 0, at α 0.05. A block-sign-flip null (1,000 reps) is reported alongside |
| pass bar | t ≥ 1.645, and the mean block IC ≥ half of exp_005's test IC (0.015). A significant but tiny residual is reported, not passed |
| kill criteria | (1) fewer than 50 forward blocks with ≥ 100 names by the evaluation date → UNDERPOWERED, unread. (2) More than 20% of the 100 candidates cannot be computed forward because a base signal's source retired → INVALID. (3) The residual is significant only in the 20% least liquid names → reported as a liquidity effect, not passed |
| costs | the top/bottom-20% long-short book on the 100, pessimistic costs.yml level, monthly; reported, never tested |
| prior | weak. Effects found by search tend to decay. exp_005's plain IC halved after 2016. **UNDERPOWERED at the read, or a pass at the margin, are both likely** |

## 5. What would make me not register it

- **The owner judging five years too long to be worth a registration.**
  That is a fair reading of §3. The alternative is to record the hypothesis
  and let it lapse.
- **A finding that the forward panel cannot be built.** The scan panel needs
  price_spine_adj, the universe membership and the deal flags to keep
  arriving. They do today; a retirement of any of them (kill 2) would show
  up long before 2031.

## 6. What happens on acceptance

1. A `scripts/register_exp006.py` on the pattern of exp_004's: `--rehearse`,
   `--register` typed, a clean-tree guard, and the stored row reproducing
   the hash. It freezes the 100 keys and signs.
2. `src/scan/forward.py`: score the frozen keys on forward blocks only. It
   refuses any block whose forward return starts before the first entry
   session.
3. A remeasure.yml item, `exp006_forward_health`, due yearly. It reports
   block count and data health, never IC.
4. The read, once, after 60 forward blocks.

**The registration must come before the first entry session (~2026-11-03).**
After that date, sessions inside the proposed forward window exist before
the spec does, and the window would have to move later. The 100 keys depend
only on the atlas to 2026-10-01, so they can be frozen now.
