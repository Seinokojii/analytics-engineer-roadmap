#!/usr/bin/env bash
# Regenerates dbt docs and copies the static files GitHub Pages needs.
# --static (dbt >= 1.7) inlines manifest + catalog into one HTML file;
# the fallback keeps the three-file layout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/dbt_analytics"
dbt docs generate --static >/dev/null 2>&1 || dbt docs generate >/dev/null
mkdir -p "$ROOT/docs/dbt"
if [ -f target/static_index.html ]; then
  cp target/static_index.html "$ROOT/docs/dbt/index.html"
  rm -f "$ROOT/docs/dbt/manifest.json" "$ROOT/docs/dbt/catalog.json"
else
  cp target/index.html target/manifest.json target/catalog.json "$ROOT/docs/dbt/"
fi
# manifest carries the local checkout path; keep the published copy neutral
sed -i 's#/home/diyar/Downloads/Analytics Engineer roadmap#<repo>#g' "$ROOT/docs/dbt/"*
echo "dbt docs -> docs/dbt ($(du -sh "$ROOT/docs/dbt" | cut -f1))"
ls -la "$ROOT/docs/dbt"
