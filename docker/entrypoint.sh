#!/bin/sh
set -eu

BUNDLED_PROMPTS_DIR="/app/bundled_prompts"
PROMPT_ACTIVE_PATH="${PROMPT_ACTIVE_FILE:-/app/prompts/active_prompt.json}"
PROMPT_VERSIONS_PATH="${PROMPT_VERSIONS_DIR:-/app/prompts/versions}"

mkdir -p "${APP_DATA_DIR:-/app/data}"
mkdir -p "$(dirname "$PROMPT_ACTIVE_PATH")"
mkdir -p "$PROMPT_VERSIONS_PATH"

if [ -d "$BUNDLED_PROMPTS_DIR/versions" ] && [ -z "$(ls -A "$PROMPT_VERSIONS_PATH" 2>/dev/null)" ]; then
  cp "$BUNDLED_PROMPTS_DIR"/versions/*.yaml "$PROMPT_VERSIONS_PATH"/
fi

if [ -f "$BUNDLED_PROMPTS_DIR/active_prompt.json" ] && [ ! -f "$PROMPT_ACTIVE_PATH" ]; then
  cp "$BUNDLED_PROMPTS_DIR/active_prompt.json" "$PROMPT_ACTIVE_PATH"
fi

exec "$@"
