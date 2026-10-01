#!/usr/bin/env bash
# Publish assets/ as the single commit of the orphan `assets` branch, replacing the previous one,
# so that git keeps only the current media. Pushing triggers the Pages deploy workflow.
# Usage: ./publish_assets.sh [remote]   (default: origin)
set -euo pipefail
cd "$(dirname "$0")"
remote=${1:-origin}

# Refuse to publish broken or unreferenced assets.
refs=$(grep -rhoE '(\.\./)?assets/[^"]+' --include='*.html' . | sed 's#^\.\./##' | sort -u)
bad=0
for p in $refs; do [ -e "$p" ] || { echo "broken path: $p" >&2; bad=1; }; done
for f in assets/*; do grep -qxF "$f" <<< "$refs" || { echo "unreferenced: $f" >&2; bad=1; }; done
[ "$bad" = 0 ] || exit 1

# Build the tree in a throwaway index, so the main checkout stays untouched.
export GIT_INDEX_FILE
GIT_INDEX_FILE=$(mktemp -u)
trap 'rm -f "$GIT_INDEX_FILE"' EXIT
git --work-tree=assets add -A -f
# A push only triggers the workflows contained in the pushed commit, so ship the deploy workflow too.
wf=.github/workflows/pages.yml
git update-index --add --cacheinfo "100644,$(git hash-object -w "$wf"),$wf"
tree=$(git write-tree)

if git fetch -q "$remote" assets 2>/dev/null && [ "$(git rev-parse FETCH_HEAD^{tree})" = "$tree" ]; then
  echo "assets unchanged, nothing to publish"
  exit 0
fi
commit=$(git commit-tree "$tree" -m "assets $(date -u +%Y-%m-%dT%H:%MZ)")
git push -f "$remote" "$commit:refs/heads/assets"
