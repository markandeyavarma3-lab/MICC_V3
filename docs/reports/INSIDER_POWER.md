# INSIDER_POWER.md — could a promoter-trade study be powered? Dispersion and n only

**Not registered. Nothing charged to a family. No effect estimated** (0035): only
the cohort SD and minimum detectable effect of the abnormal return after each
promoter filing. Generated 2026-09-29 by `python -m src.research.insider_power`
and `python -m src.research.insider_power --charmatched`, on the seed's SEBI PIT
filings 2016-01 → 2026-07, fixed horizon 2026-08-31.

Bound = 0.5%/month × horizon months (0028). A population is registrable only
when its MDE is at or below the bound.

## Against the equal-weighted market (the method 0046 used)

| population | horizon | events | cohorts | cohort SD | MDE | bound | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| promoter buy | 1m | 18,644 | 127 | 3.13% | 0.78% | 0.50% | 1.56× short |
| promoter buy | 3m | 17,993 | 126 | 5.72% | 1.84% | 1.50% | 1.22× short |
| promoter buy | 12m | 16,327 | 116 | 15.66% | 7.52% | 6.00% | 1.25× short |
| promoter sell | 1m | 10,497 | 127 | 3.36% | 0.90% | 0.50% | 1.80× short |
| promoter sell | 3m | 9,919 | 126 | 5.87% | 1.90% | 1.50% | 1.27× short |
| **promoter sell** | **12m** | **9,284** | **116** | **15.16%** | **6.80%** | **6.00%** | **1.13× short** |
| pledge / revoke / invoke | any | | | | | | 1.8× – 7.2× short |

Promoter sells at twelve months, **1.13× short**, is the closest any population
in this project has come (0046 measured 1.25× on the same horizon, with fewer
months).

## Against CHAR_MATCHED (size × momentum × volatility peers)

| population | horizon | events | cohorts | cohort SD | MDE | verdict |
|---|---|---:|---:|---:|---:|---|
| promoter buy | 1m | 17,270 | 127 | 3.04% | 0.76% | 1.51× short |
| promoter buy | 3m | 16,705 | 126 | 5.77% | 1.87% | 1.24× short |
| promoter buy | 12m | 15,180 | 116 | 16.07% | 7.84% | 1.31× short |
| promoter sell | 1m | 9,803 | 127 | 3.33% | 0.94% | 1.89× short |
| promoter sell | 3m | 9,264 | 126 | 6.04% | 2.01% | 1.34× short |
| promoter sell | 12m | 8,691 | 116 | 16.99% | 8.99% | 1.50× short |

**Matching did not reduce the noise for insider events; it raised it at twelve
months** (15.2% → 17.0%), and about 600 sells drop out for want of a qualifying
peer cell. On deals a size match cut cohort SD by a third (0028); on promoter
filings it does not. The CHAR_MATCHED benchmark still controls for a real
confound — promoters sell after run-ups, which is momentum — so a registration
would have to choose between the more sensitive benchmark and the better
control, and say which before looking.

## Landing

**No population is registrable today, under either benchmark.** MDE falls as
1/√cohorts. At the best case (promoter sells, 12 months, market benchmark,
1.13×) the bound needs 1.13² ≈ 1.28× the cohorts: about 148 twelve-month
cohorts against 116, **roughly 2½ – 3 more years**. Under CHAR_MATCHED (1.50×)
it needs 2.25×, about a decade.

Recommendation: do not draft or register the insider study now; a spec frozen
today lands UNDERPOWERED. Re-run this measurement yearly. The collector keeps
the series current (src/archive/insider.py), so the cohorts accrue on their own.
