#!/bin/sh
# 엔딩 크레딧 레이어. 보너스 트랙(19)이 흐르는 동안 Fine(fine_frame_d.png) 아래 칸에서 아주 천천히 올라가는 롤이다.
#   credits_roll.png  : 가로 1920, 세로는 내용만큼인 투명 PNG. FilmCraft 에서 Motion 위치 키프레임으로 아래→위로 움직인다.
#   credits_cover.png : fine_frame_d.png 를 그대로 복사하되 Fine 아래 칸(FADE_TOP~FADE_BOT 에서 BOT_FADE 까지)만 투명하게 판 덮개.
#                       크레딧 위 트랙에 얹으면 크레딧이 Fine 근처에서 서서히 사라지고, 화면 맨 아래에서 서서히 나타난다.
#                       덮개가 바탕과 같은 픽셀이라 경계가 보이지 않는다.
# 글씨: 제목 줄은 side_frames.sh·fine_frame 과 같은 Times New Roman (Bold Italic / Italic),
#       곡 줄은 intro_frame.sh 와 같은 Pretendard Light (한글·영문 모두). 모두 흰색.
# 곡 목록은 ../classification.json 에서 읽고 "아티스트-곡명" 을 "nn 아티스트 - 곡명" 으로 바꾼다.
# 시퀀스 마커 이름과 다른 두 곡만 RENAME 으로 맞춘다. 18 번 곡 줄 아래에는 보조 줄 두 개(인스트 커버 출처, vocal: light)를 둔다.
#
#   ./credits_frames.sh
set -eu
cd "$(dirname "$0")"

SERIF_BI="/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf"
SERIF_I="/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"
GOTHIC="fonts/Pretendard-Light.otf"
CREDIT_SIZE=46   # compiled by: light
SIDE_SIZE=56     # side A ~ side D, bonus track
TRACK_SIZE=34    # 곡 줄
NOTE_SIZE=27     # 곡 줄 아래 보조 줄 (inst cover·vocal)
GAP_NOTE=6       # 곡 줄과 보조 줄 사이
GAP_TRACK=18     # 곡 줄 사이
GAP_HEAD=30      # 제목과 첫 곡 사이
GAP_BLOCK=110    # 묶음 사이
# 덮개의 투명 칸 (fine_frame_d.png 의 Fine 글씨는 y 478~604)
FADE_TOP=650     # 여기까지는 덮개가 불투명 — 크레딧이 보이지 않는다
FADE_BOT=740     # 여기부터 완전히 보인다
BOT_FADE=1020    # 여기부터 다시 덮개가 짙어져 1080 에서 불투명
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# 묶음 정의: 제목|첫 번호|끝 번호
python3 - ../classification.json "$TMP/tracks.txt" <<'PYEOF'
import json, sys
RENAME = {  # 시퀀스 마커 이름에 맞춘다
    14: "Stockholm Syndrome (Live From Wembley Stadium)",
    18: "Movie (Shoegaze Inst)",
}
items = json.load(open(sys.argv[1], encoding="utf-8"))["items"]
with open(sys.argv[2], "w", encoding="utf-8") as f:
    for it in items:
        n, artist = it["index"], it["artist"]
        song = it["name"][len(artist) + 1:] if it["name"].startswith(artist + "-") else it["name"]
        f.write(f"{n:02d} {artist} - {RENAME.get(n, song)}\n")
PYEOF

parts=""
k=0
add() {  # add <font> <size> <text>
  k=$((k + 1))
  magick -background none -fill white -font "$1" -pointsize "$2" label:"$3" "$TMP/l$k.png"
  parts="$parts $TMP/l$k.png"
}
gap() { k=$((k + 1)); magick -size 1x"$1" xc:none "$TMP/l$k.png"; parts="$parts $TMP/l$k.png"; }
block() {  # block <제목> <첫 번호> <끝 번호>
  gap $GAP_BLOCK
  add "$SERIF_BI" $SIDE_SIZE "$1"
  gap $GAP_HEAD
  i=$2
  while [ "$i" -le "$3" ]; do
    [ "$i" -gt "$2" ] && gap $GAP_TRACK
    add "$GOTHIC" $TRACK_SIZE "$(sed -n "${i}p" "$TMP/tracks.txt")"
    # 18 번은 유튜브 채널 '빈도시' 가 올린 비공식 슈게이즈 인스트 커버(E8-P833ptPk)이고,
    # 사이드 D 음원에서는 그 위에 light 가 직접 부른 보컬을 얹었다. 출처를 밝힌다(URL 은 넣지 않는다)
    if [ "$i" -eq 18 ]; then
      gap $GAP_NOTE; add "$GOTHIC" $NOTE_SIZE "inst cover: 빈도시 (YouTube)"
      gap $GAP_NOTE; add "$GOTHIC" $NOTE_SIZE "vocal: light"
    fi
    i=$((i + 1))
  done
}

add "$SERIF_I" $CREDIT_SIZE "compiled by: light"
block "side A" 1 5
block "side B" 6 10
block "side C" 11 14
block "side D" 15 18
block "bonus track" 19 19
# shellcheck disable=SC2086
magick $parts -background none -gravity center -append -gravity center -extent 1920x +repage "PNG32:credits_roll.png"
echo "credits_roll.png $(magick identify -format '%wx%h' credits_roll.png)"

magick \( -size 1920x$FADE_TOP xc:white \) \
  \( -size 1920x$((FADE_BOT - FADE_TOP)) gradient:white-black \) \
  \( -size 1920x$((BOT_FADE - FADE_BOT)) xc:black \) \
  \( -size 1920x$((1080 - BOT_FADE)) gradient:black-white \) \
  -append -colorspace gray "$TMP/mask.png"
magick fine_frame_d.png "$TMP/mask.png" -alpha off -compose CopyOpacity -composite "PNG32:credits_cover.png"
echo "credits_cover.png $(magick identify -format '%wx%h' credits_cover.png)"
