#!/bin/sh
# 엔딩 크레딧 롤. 1:24:09:20 에 순수 검정 위로 Fine 이 컷인하고, 그 아래 크레딧과 함께 화면 위로 아주 천천히 올라간다.
#   credits_roll.png : 가로 1920, 세로는 내용만큼인 투명 PNG. FilmCraft 에서 Motion 위치 키프레임으로 아래→위로 움직인다.
#                      Fine 은 fine_frame.png 의 Fine 과 같은 크기(Times New Roman Bold Italic 180pt)이고,
#                      PNG 맨 위를 화면 맨 위(y 0)에 두었을 때 Fine 과 compiled by: light 두 줄의 잉크가 화면 세로 가운데에 오도록
#                      FINE_SHIFT 만큼 위로 올렸다(기존 Fine 프레임보다 94px 위).
# 글씨: 제목 줄은 Times New Roman (Bold Italic / Italic), 곡 줄은 intro_frame.sh 와 같은 Pretendard Light. 모두 흰색.
# 곡 목록은 ../classification.json 에서 읽고 "아티스트-곡명" 을 "nn 아티스트 - 곡명" 으로 바꾼다.
# 시퀀스 마커 이름과 다른 두 곡만 RENAME 으로 맞춘다. 18 번 곡 줄 아래에는 보조 줄 두 개(인스트 커버 출처, vocal: light)를 둔다.
# 맨 밑에는 credits_spiral.png(1672x941 투명 PNG, 썸네일과 같은 흰 점묘 나선)를 GAP_SPIRAL 띄워 가운데에 붙인다.
#   원본의 보이는 부분(검정 위 합성 밝기 1 이상, x 443~1199 · y 84~883)만 잘라 높이 SPIRAL_H 로 줄인다.
#   그 밖은 alpha 1~9 의 옅은 번짐뿐이라 검정 위에서 0 으로 사라진다. 롤이 끝나면 나선이 화면 세로 가운데에 홀로 남는다.
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
FINE_SIZE=180    # Fine (fine_frame.png 와 같다 — 글씨 잉크는 y 478~604)
FINE_SHIFT=94    # Fine 을 1080 한가운데에서 올리는 양. Fine 잉크 478~603·compiled by 749~790 → 384~696 (가운데 540)
HEAD_H=$((740 - FINE_SHIFT))  # Fine 칸의 높이. 그 아래에 compiled by 를 붙인다
GAP_SPIRAL=360   # bonus track 곡 줄과 나선 사이 — 롤 끝에 나선이 가운데 오면 bonus 묶음은 화면 위로 막 빠져나가 있다
SPIRAL_H=620     # 나선 높이 (원본 800px 에서 줄인다 — 업스케일 없음)
INTRO_H=$((1080 - GAP_BLOCK))  # Fine·compiled by 칸의 높이 — 컷인 때 화면에는 이 둘만 보이고 side A 는 화면 바로 아래에서 시작한다
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
credit=$parts
parts=""
block "side A" 1 5
block "side B" 6 10
block "side C" 11 14
block "side D" 15 18
block "bonus track" 19 19
magick -size 1920x1080 xc:none -font "$SERIF_BI" -pointsize $FINE_SIZE -fill white \
  -gravity center -annotate +0-$FINE_SHIFT Fine -gravity north -crop 1920x$HEAD_H+0+0 +repage "$TMP/head.png"
# shellcheck disable=SC2086
magick "$TMP/head.png" $credit -background none -gravity north -append -extent 1920x$INTRO_H +repage "$TMP/intro.png"
# shellcheck disable=SC2086
magick $parts -background none -gravity center -append -gravity center -extent 1920x +repage "$TMP/body.png"
# 나선은 body 와 따로 붙인다 — body 에 넣으면 -extent 1920x 의 세로 정렬이 바뀌어 위쪽 크레딧이 14px 밀린다
magick -size 1920x$((GAP_SPIRAL + SPIRAL_H)) xc:none \
  \( credits_spiral.png -crop 757x800+443+84 +repage -resize x$SPIRAL_H \) \
  -gravity north -geometry +0+$GAP_SPIRAL -composite "$TMP/spiral.png"
magick "$TMP/intro.png" "$TMP/body.png" "$TMP/spiral.png" -background none -gravity north -append +repage "PNG32:credits_roll.png"
echo "credits_roll.png $(magick identify -format '%wx%h' credits_roll.png)"
