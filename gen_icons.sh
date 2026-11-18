#!/usr/bin/env bash
set -euo pipefail
ASSETS=/home/elilovescomputers/Programming/Projects/Assistant/assets
ANDROID_RES=/home/elilovescomputers/Programming/Projects/Assistant/web/android/app/src/main/res

generate() {
  local d="$1" ls="$2" fs="$3"
  magick "$ASSETS/composite.png" -resize "${ls}x${ls}" -depth 8 "$ANDROID_RES/mipmap-$d/ic_launcher.png"
  magick "$ASSETS/composite.png" -resize "${ls}x${ls}" -depth 8 "$ANDROID_RES/mipmap-$d/ic_launcher_round.png"
  magick "$ASSETS/icon-foreground.png" -resize "${fs}x${fs}" -background none -depth 8 "$ANDROID_RES/mipmap-$d/ic_launcher_foreground.png"
  echo "$d: legacy ${ls}px foreground ${fs}px"
}

generate mdpi 48 108
generate hdpi 72 162
generate xhdpi 96 216
generate xxhdpi 144 324
generate xxxhdpi 192 432
