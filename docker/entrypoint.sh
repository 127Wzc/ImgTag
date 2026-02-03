#!/bin/sh
set -eu

STATIC_DIR="${STATIC_DIR:-/app/static}"
INDEX_HTML="${STATIC_DIR}/index.html"
CONFIG_JS="${STATIC_DIR}/config.js"

escape_js_string() {
  # 仅做最小转义：\ " CR LF
  # shellcheck disable=SC2001
  printf '%s' "$1" \
    | sed -e 's/\\/\\\\/g' \
          -e 's/"/\\"/g' \
          -e 's/\r/\\r/g' \
          -e 's/\n/\\n/g'
}

write_config_js() {
  mkdir -p "$STATIC_DIR"
  {
    echo 'window.__IMGTAG_CONFIG__ = window.__IMGTAG_CONFIG__ || {};'
    echo 'window.__IMGTAG_CONFIG__ = Object.assign(window.__IMGTAG_CONFIG__, {'

    # 注入所有以 VITE_ 开头的环境变量
    # 注意：这些变量会暴露给浏览器，只能放“公开配置”
    env | grep '^VITE_' | sort | while IFS= read -r line; do
      key="${line%%=*}"
      value="${line#*=}"

      if [ -n "$value" ]; then
        escaped="$(escape_js_string "$value")"
        printf '  "%s": "%s",\n' "$key" "$escaped"
      else
        printf '  "%s": null,\n' "$key"
      fi
    done

    echo '});'
  } >"$CONFIG_JS"
}

cache_bust_index_html() {
  [ -f "$INDEX_HTML" ] || return 0

  ts="$(date +%s)"
  # 将 src="/config.js" 或 src="/config.js?..." 统一改写为 src="/config.js?ts=<ts>"
  sed -i -E "s|(src=[\"']/config\\.js)(\\?[^\"']*)?([\"'])|\\1?ts=${ts}\\3|g" "$INDEX_HTML"
}

write_config_js
cache_bust_index_html

exec "$@"
