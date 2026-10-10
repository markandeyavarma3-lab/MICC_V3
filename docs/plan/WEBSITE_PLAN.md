# Website plan: a public, daily, data-only view of Indian institutional activity

**Status: DRAFT, 2026-10-09.** Written from the owner's answers that day. The
name is a working title (**"Deal Lens"**); the owner chooses before launch.

## 1. What it is, and what it never is

**It is** a free public site for analysts and students. It shows, every
trading day, who traded India's bulk and block deals. The participant labels
are this project's own work:
- high-frequency round-trippers;
- mutual funds, grouped by fund house;
- foreign institutions;
- promoters;
- individuals.

Around those labels it shows each stock's institutional history and each
participant's footprint.

**It never** says buy, sell or hold, makes a performance claim, ranks anyone
by returns, or hints at a future price. That is the owner's line ("we will not
give any suggestions like buy or sell, just display the data and facts"), and
it is also SEBI's line for anyone unregistered:
- January 2025 circular: no advice, no performance claims, no price hints;
- the Research Analyst Regulations as amended in 2024 and 2025.

So the site carries no forward-return statistics per stock or per
participant. The project's research verdicts are aggregate and pre-registered;
a later version may explain them.

## 2. Who it is for

Analysts, students and researchers, in English. The site assumes they know
what a bulk deal is and wants them to go deeper: dense tables, exact numbers,
filters, downloads, method notes on every label.

## 3. Version 1: three sections

### 3.1 Today: deals, labelled

- **Header strip.** The session date; counts of bulk and block deals; the
  share that are same-day round trips; FII and DII net cash flow; F&O
  positioning by category (FII, DII, Pro, Client) and its change on the day.
- **The deals table.** One row per deal: symbol, client as filed, our
  participant, type label, side, quantity, price, ₹ value, and a flag if the
  same client did the opposite trade in the same stock that day. Filter by
  type, side, exchange and size. **Round-trippers are folded under one
  summary row by default**, because they are most of the volume and least of
  the information. One click shows them.
- **Calendar.** Any past session since 2005 opens the same view.

### 3.2 Stock pages (~2,300 companies with any disclosure)

- **Price context.** A simple end-of-day closing line, with deals marked on
  it (buy/sell, coloured by participant type). Prices are shown, never
  returns after events (§1).
- **Deals tab.** Every bulk and block deal, filterable, with the same
  labels.
- **Ownership tab.** Quarterly shareholding as filed: promoter, FPI
  (Category I/II), mutual funds and other institutions as stacked areas, and
  holder counts. Each quarter links to the exchange filing.
- **Insider tab.** SEBI PIT disclosures by category (promoter, director,
  employee), shown as a timeline.
- **Identity box.** ISIN, any symbol renames, series moves (EQ → BE), and
  delisting with its reason, from `security_master`.

### 3.3 Participant pages (27,772 participants)

- **Identity.** Canonical name, every raw spelling filed, type and how it
  was set (behaviour, name pattern or owner ruling, with the ruling's note),
  and fund house.
- **Behaviour, descriptive only.** Deals per year, buy/sell mix, same-day
  round-trip rate (the PROP_HFT test made visible), and the stocks traded
  most. No returns after its trades, and no ranking (§1).
- **Deals table**, with downloads.
- Pages are generated for every participant. The ~1,500 with 6 or more
  deals get full pages; the long tail renders client-side from shards, so
  the build stays fast.

### 3.4 Throughout

- **Search first.** One box for stocks, participants and raw spellings. The
  index is prebuilt and loads in under 150 KB.
- **Downloads.** Every table downloads as CSV (the owner's choice; see the
  licence gate, §7).
- **Method notes.** Each label links to a short page saying exactly how it
  is assigned: the 95% / 20-day round-trip rule, the name patterns, owner
  rulings and the fund-house file.
- **Freshness.** Every page shows "data as of <session>, built <time>",
  read from the collector's own health check. If the Mac misses a night, the
  site says so instead of looking current.
- **Source line** on every page: data from NSE and SEBI public disclosures;
  labels by this project.

## 4. Look: research terminal

- **Two themes** (light and dark), following the system theme with a
  toggle.
- **Type:** tabular monospace numerals (JetBrains Mono or IBM Plex Mono) and
  a clean sans for prose (Inter or IBM Plex Sans).
- **Colour carries meaning only:** buy and sell; one hue per participant
  type, held across every chart; round-trippers in a muted grey. The palette
  is checked for contrast and colour blindness.
- **Layout:** tight tables with sticky headers, small multiples for
  ownership, sparklines in tables, and keyboard navigation (`/` to search).
- **Mobile works** (tables scroll horizontally inside their cards), but
  desktop is the primary target, given the audience.

## 5. How it is built

| piece | choice | why |
|---|---|---|
| framework | **Astro**, static output | fast pages, no server, islands of interactivity only where needed |
| tables | TanStack Table (a lightweight interactive-table library) in islands | sort, filter and virtualise 10k rows |
| charts | Observable Plot or ECharts | dense, accessible, themeable |
| search | a prebuilt JSON index with fuzzy match (MiniSearch) | instant, offline-capable |
| data | JSON shards per stock, per participant and per session; CSV alongside | each page loads only its own data |
| host | **GitHub Pages**, from a new public repo | free, CDN-served, HTTPS |

### 5.1 The nightly pipeline, on the Mac

After `collect_daily.sh` finishes, a new stage runs `src/site/export.py`:
1. It reads the warehouse read-only.
2. It writes the JSON and CSV shards into the site repo's working copy.
3. `astro build` produces the static site.
4. It pushes **one fresh snapshot** to the site repo's `gh-pages` branch:
   orphan, force-pushed, so git history never grows with data.
5. Pages serves it within minutes.

A failed export or build pages through the existing stage alerts. The site
then keeps yesterday's snapshot and says so.

### 5.2 Size and speed budgets

- Site under 1 GB (GitHub Pages' limit).
- Each page's first load under 300 KB.
- The Today page under 1 second on a laptop.

Measured at the first full export; the full history of deals is about 235k
rows.

## 6. Repos

- **`institutional-research` (this repo):** the exporter, `src/site/`,
  tested like everything else.
- **New public repo (`deal-lens`, working name):** the Astro project plus the
  nightly `gh-pages` snapshot.
- **No secret goes in either repo.** The push uses the owner's existing git
  credentials on the Mac.

## 7. Gates before launch

1. **The price history is fixed** (the Kite audit, 0087). The adjusted series
   holds 3,107 one-day moves larger than 35%, many of them missed splits and
   bonuses. Charts would show fake −50% days.
2. **NSE's data terms.** The owner chose price charts and full downloads.
   Commercial use of NSE market data needs an NSE Data & Analytics
   agreement, and a free non-commercial site is a grey area. Before launch:
   read NSE's current data policy, and ideally ask NSE Data & Analytics or a
   securities lawyer. If needed, the fallback is to drop the price line and
   the raw-row downloads, keeping our own labels downloadable.
3. **No Kite data, ever.** Kite's terms are personal use; the exporter
   refuses its tables by construction, and a test checks this.
4. **The SEBI line holds in review.** Before launch, every page is checked
   for any forward return, ranking or price hint.
5. **Freshness is truthful:** a stale night shows as stale.

## 8. Phases

1. **Exporter + data contract.** `src/site/export.py` with tests, writing
   the shards locally. Sizes measured.
2. **Site skeleton.** The new repo; Astro with the design system; the Today
   page on real data, viewed locally.
3. **Stock and participant pages**, plus search.
4. **Nightly pipeline** wired into the collector, deploying to Pages.
5. **Gates (§7)**, then the name, then launch.

## 9. Open for the owner

- The name.
- When to start phase 1. It can run alongside the price fix, but nothing is
  published until gate 1 passes.

## 10. Broadening (owner, 2026-10-10: "build everything", order mine)

| Part | What | Source | State |
|---|---|---|---|
| A | Who owns what: every named holder above 1% | SHP XBRL (`src/ingest/shp_holders.py`) | live |
| C | Market structure: pledges, announcements, board meetings, actions, sector and index membership | NSE filings (`src/archive/nse_filings.py`) | live |
| B | Fundamentals: quarterly results, market cap, trailing P/E | NSE results XBRL (`src/archive/results.py`) | live; backfill nightly |
| E | Screener and site-wide search | the stock documents | live |
| D | Mutual-fund monthly portfolios: every holding of every covered scheme | each fund house's site (`src/archive/mf_portfolios.py`, `configs/mf_sources.yml`) | live for the houses below |

**Part D coverage.** SEBI makes each house publish month-end portfolios on
its own site within ten days; AMFI only links to them. Each house's page is
rendered nightly and its files kept as served; one parser reads every house's
layout (`src/ingest/mf_portfolios.py`).

- Covered (2026-10-10): SBI, ICICI Prudential, HDFC, Nippon India, Aditya
  Birla Sun Life, Motilal Oswal, DSP, Mirae Asset, Tata, Groww, PPFAS, Baroda
  BNP Paribas, Invesco, Samco, Shriram, Helios, JM Financial (17 houses,
  ~1,030 schemes for September 2026). Old Bridge is configured; its page
  lists nothing after February 2026.
- Refused, and respected: **Kotak** (a bot-check page) and **Bandhan**
  (HTTP 403) to automated browsers.
- Not yet mapped: **Axis** (encrypted API traffic), **UTI** (the page hangs
  headless), **Franklin Templeton** (files named by a path the site serves
  only as its app shell), **HSBC** and **Union** (their pages list only old
  years), **Edelweiss, Canara Robeco, Quant, LIC, Sundaram, PGIM, Mahindra
  Manulife, WhiteOak, 360 ONE, Navi** and the smallest houses. The Funds
  page lists the houses covered; a house not listed is missing, not empty.
