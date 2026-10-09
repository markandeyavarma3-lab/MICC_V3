# 0087 — One month of Kite Connect audits the price spine; it never enters a study

**Date:** 2026-10-09
**Decided by:** Owner. They hold 500 Kite Connect credits, which is one
month of the paid plan, and asked for the audit to be built ("yeah").
**Status:** accepted; built, not yet run (it needs the owner's app and a
daily login)
**Related:** 0045 (the EQ-only spine), 0082 (listing history and the
2026-06-26 .. August full-bhavcopy gap), 0086 (collection continues).

## Context

Every verdict rests on `price_spine_adj`: NSE's files plus this project's
own split and bonus adjustment. It has never been compared with a second
vendor. Kite Connect's paid plan carries daily candles. ₹500 buys one month
of it, which is not enough to keep it as a standing source.

## Decision

1. **Three pieces, standard library only, with no new dependency.**
   - `scripts/kite_login.py`: the owner runs it in their own Terminal. It
     catches the login redirect on 127.0.0.1:5000 and writes the day's
     token.
   - `src/archive/kite.py`: every NSE cash instrument, every series,
     2005 → yesterday, at under 3 requests a second, resumable. It keeps
     its own manifest under `data/raw/archive/KITE`.
   - `src/research/price_audit.py`: compares each company's close with
     both our raw and adjusted series, and lists **steps**. A step is a
     log-ratio jump of more than 2% held for 5 sessions: a corporate action
     one side adjusted for and the other did not.
2. **Credentials stay out of the repository and out of chat.** The key and
   secret are in `~/.micc_kite` and the token in `~/.micc_kite_token`,
   both mode 600; a file anyone else can read is refused. A stale token
   stops the run before its first request. No error message carries a
   secret.
3. **Kite data never enters a study panel.** Kite holds no delisted
   company, so a panel built on it is survivorship-biased by construction.
   It audits; it does not replace.
4. **Nothing Kite serves is published.** Its terms are personal use and the
   repository is public. Raw files sit under the git-ignored `data/`, and
   `PRICE_AUDIT.md` carries counts, dates and step sizes, never a price
   series.
5. **A step is a question, not a correction.** Fixing the spine for what
   the audit finds is a decision of its own, with the affected studies
   named.

## What would reverse this

The owner keeping Kite Connect past one month. It could then be a second
price source with a standing check, which would be its own decision.

## Cost accepted

- **One month, one daily login.** Kite tokens expire every morning. The
  owner logs in by hand; storing their password and TOTP secret to
  automate it is refused.
- **A blind spot the audit cannot close:** delisted companies, and renamed
  symbols before their rename. Both are counted in the report, not hidden.

## Run 2026-10-09: what the audit found

All 5,225 NSE equity instruments were pulled (0 failed, 124 MB, git-ignored).
`docs/reports/PRICE_AUDIT.md` matched 2,651 companies over 5,274,122
company-days.

**The adjusted spine carries unadjusted corporate actions.** It holds 3,107
one-day moves larger than 35% across 1,430 symbols, 2005–2026.

- **Where Kite can confirm** (215 of them): 168, or 78%, are moves only our
  series shows. Kite is flat, and ours drops to ½, ⅕ or 1/10, the
  signature of a split or bonus left unadjusted. Examples: TCS 2018-05-31
  and INFY 2015-06-15, both 1:1 bonuses. Thirty-nine are real moves that
  Kite shows too.
- **Where Kite cannot confirm** (2,892): delisted or renamed symbols, or
  dates before Kite's history begins. Of all 3,107 moves, **1,481 land
  within 1.5% of a clean fraction a/b** (a < b ≤ 20) across 902 symbols. A
  genuine crash does not land on ½; an unadjusted action does.
- **Cause.** The seed's action table holds 681 BONUS and 655 SPLIT rows,
  and only 26 of the jumps fall on one of those dates. Recorded actions were
  adjusted; **the misses are actions the table never recorded.**
- **Why no check caught it.** The build's >35% discontinuity guard
  (`spine.py`) runs only on the tail after the seed boundary (2026-06-25).
  The 21 years before it were never checked.
- **Reach into the deal studies.** Of the eligible deal outcomes, the share
  whose window [entry, exit] contains one of the 1,481 suspect days is:
  - 0.2% at 1 session;
  - 2.3% at 21;
  - 3.4% at 63;
  - 4.1% at 252.

  Each such outcome carries a fake drop of 50–90%.

Kite is also known to adjust things this series deliberately does not
(demergers; gold ETF unit splits). Those are conventions, listed in the
audit, not errors.

**Not done here.** No price was changed and no verdict reopened. A
correction of the spine and a re-check of each registered verdict on
corrected prices is a decision of its own, for the owner.
