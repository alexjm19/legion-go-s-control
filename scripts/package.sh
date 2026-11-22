#!/usr/bin/env bash
# Build and package the plugin as a Decky-installable zip in out/.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=legion-go-s-control
VER=$(python3 -c 'import json;print(json.load(open("package.json"))["version"])')
npx -y pnpm@9 install --frozen-lockfile >/dev/null
npx -y pnpm@9 run build >/dev/null
rm -rf out && mkdir -p "out/$NAME/dist"
cp dist/index.js "out/$NAME/dist/"
cp main.py plugin.json package.json LICENSE README.md "out/$NAME/"
(cd out && zip -qr "$NAME-v$VER.zip" "$NAME")
sha256sum "out/$NAME-v$VER.zip"
