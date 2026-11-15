#!/bin/bash
# Re-render every figure in this folder as a PNG with a transparent background, from its HTML, with headless Firefox.
#   bash docs/figures/render.sh              every figure
#   bash docs/figures/render.sh attrition    only the figures drawn from attrition.html (any page name works)
# Each page is shot twice, on white and on black (its #bg=... hash), and transparent.py turns the pair into one
# transparent PNG. Text is dark: the PNGs are for light slides.
#   pipeline_full.png, pipeline_stakeholders.png        3840x2160 (16:9)
#   pipeline_stakeholders_step1..5.png                  the same chart with one step in focus, for walking through it
#   attrition.png (all hospitals), attrition_by_set.png 3200x1520
#   cost_waterfall.png (model cost per hospital, prompt v2 to the final run, no judge) 3200x1360
#   prompt_anatomy.png (what the model is sent and sends back, shortened and annotated) 3840x2160
#   privacy_hosts.png (who can read the prompts: Kimi on Bedrock, Claude on Anthropic's API, Claude on Bedrock) 3840x2160
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
FF=/Applications/Firefox.app/Contents/MacOS/firefox
PROFILE="$(mktemp -d)"; TMP="$(mktemp -d)"
trap 'rm -rf "$PROFILE" "$TMP"' EXIT

ONLY="${1:-}"
shot() {  # shot HTML_NAME OUT_NAME WIDTH HEIGHT [EXTRA_HASH_PARAMS]
  [ -z "$ONLY" ] || [ "$ONLY" = "$1" ] || return 0
  for bg in ffffff 000000; do
    "$FF" --headless --profile "$PROFILE" --screenshot "$TMP/$bg.png" --window-size="$3,$4" \
      "file://$DIR/$1.html#bg=$bg${5:+&$5}" >/dev/null 2>&1
  done
  uv run --no-project --with pillow --with numpy python -I "$DIR/transparent.py" "$TMP/ffffff.png" "$TMP/000000.png" "$DIR/$2.png"
}

shot pipeline_full pipeline_full 3840 2160
shot pipeline_stakeholders pipeline_stakeholders 3840 2160
for i in 1 2 3 4 5; do shot pipeline_stakeholders "pipeline_stakeholders_step$i" 3840 2160 "focus=$i"; done
shot attrition attrition 3200 1520 "view=combined"
shot attrition attrition_by_set 3200 1520 "view=split"
shot cost_waterfall cost_waterfall 3200 1360
shot prompt_anatomy prompt_anatomy 3840 2160
shot privacy_hosts privacy_hosts 3840 2160
