#!/bin/zsh
# site_publish.sh — export the public site's data, build it, and publish it.
#
# Run by collect_daily.sh after the backup and the health check (the
# `site` stage), and by hand. docs/plan/WEBSITE_PLAN.md §5.1.
#
#   1. src/site/export.py writes ../deal-lens/public/data from the warehouse
#      (read-only; the collector's writers have finished by now)
#   2. astro build writes ../deal-lens/dist
#   3. IF the site repo has an `origin`, dist is pushed to its gh-pages
#      branch as ONE orphan commit, force-pushed: the data is ~260 MB and
#      changes nightly, so keeping its history would grow the repo forever.
#      Without an origin it stops after the build and says so.
#
# launchd's PATH is /usr/bin:/bin:/usr/sbin:/sbin, so Node is found by path.
# No credential lives here: the push uses the owner's existing git setup.

set -u
REPO="$HOME/Workspace/institutional-research"
SITE="$HOME/Workspace/deal-lens"
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/v2*/bin 2>/dev/null | sort -V | tail -1)"
export PATH="$NODE_BIN:$PATH"
export RESEARCH_ENV=prod

[ -d "$SITE" ] || { echo "site_publish: no site repo at $SITE"; exit 1; }
[ -x "$NODE_BIN/npx" ] || { echo "site_publish: no Node found under ~/.nvm"; exit 1; }

"$REPO/.venv/bin/python" -m src.site.export || exit 1
( cd "$SITE" && npx --no-install astro build >/dev/null ) || { echo "site_publish: astro build failed"; exit 1; }
touch "$SITE/dist/.nojekyll"     # serve _astro/ as-is: GitHub Pages' Jekyll skips underscore paths
echo "  site built: $(du -sh "$SITE/dist" | cut -f1) in $SITE/dist"

ORIGIN="$(git -C "$SITE" remote get-url origin 2>/dev/null || true)"
if [ -z "$ORIGIN" ]; then
  echo "  site NOT published: $SITE has no origin remote (create the GitHub repo, then: git -C $SITE remote add origin <url>)"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp -R "$SITE/dist/." "$TMP/"
(
  cd "$TMP" || exit 1
  git init -q -b gh-pages
  git add -A
  git -c user.name="Deal Lens publisher" -c user.email="noreply@users.noreply.github.com" \
      commit -q -m "Snapshot $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -q -f "$ORIGIN" gh-pages:gh-pages
) || { echo "site_publish: push to $ORIGIN failed"; exit 1; }
echo "  site published to $ORIGIN (gh-pages, one orphan snapshot)"
