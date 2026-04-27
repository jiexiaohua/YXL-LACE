#!/usr/bin/env bash
set -euo pipefail

# Convert assets/app.png to assets/app.icns (macOS).
# Requires: sips, iconutil (built-in on macOS).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PNG="${ROOT_DIR}/assets/app.png"
OUT="${ROOT_DIR}/assets/app.icns"

if [[ ! -f "${PNG}" ]]; then
  echo "Missing: ${PNG}" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
ICONSET="${WORKDIR}/app.iconset"
mkdir -p "${ICONSET}"

for size in 16 32 64 128 256 512; do
  sips -z "${size}" "${size}" "${PNG}" --out "${ICONSET}/icon_${size}x${size}.png" >/dev/null
  sips -z "$((size * 2))" "$((size * 2))" "${PNG}" --out "${ICONSET}/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "${ICONSET}" -o "${OUT}"
rm -rf "${WORKDIR}"

echo "Wrote: ${OUT}"

