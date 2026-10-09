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
