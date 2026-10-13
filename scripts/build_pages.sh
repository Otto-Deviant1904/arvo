#!/bin/sh
# Copy the single-file UI into docs/ for GitHub Pages, plus the demo roster and sample diary.
# docs/demo/run.json is a saved run; regenerate it separately with a real model run.
set -eu
cd "$(dirname "$0")/.."
mkdir -p docs/demo
cp web/index.html docs/index.html
cp data/roster.example.json docs/demo/roster.json
touch docs/.nojekyll
echo "docs/ updated from web/index.html"
