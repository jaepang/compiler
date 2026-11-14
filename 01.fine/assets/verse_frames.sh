#!/bin/sh
# Fine 뒤에 띄우는 말씀(개역개정) 레이어. 1920x1080 투명 PNG 를 만든다 —
# 로마서 7:24·25 는 25절이 나타날 때 24절이 움직이지 않도록 둘 다 최종 위치에 미리 배치하고,
# 그다음 화면인 요한복음 3:3 은 혼자 세로 가운데에 둔다. 가로 위치는 모두 같다.
set -eu
cd "$(dirname "$0")"

SERIF="/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"
MYEONGJO="$HOME/Library/Fonts/NotoSerifKR[wght].ttf"   # 본명조 (Noto Serif KR, OFL)
[ -f "$MYEONGJO" ] || MYEONGJO="/Library/Fonts/NotoSerifKR[wght].ttf"
SIZE=42
REF_W=290      # "Romans 7:24" 칸
TEXT_W=1300    # 말씀 칸 (넘치면 줄바꿈)
GAP=56         # 24절과 25절 사이
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

V24="오호라 나는 곤고한 사람이로다 이 사망의 몸에서 누가 나를 건져내랴"
V25="우리 주 예수 그리스도로 말미암아 하나님께 감사하리로다 그런즉 내 자신이 마음으로는 하나님의 법을, 육신으로는 죄의 법을 섬기노라"
J33="예수께서 대답하여 이르시되 진실로 진실로 네게 이르노니 사람이 거듭나지 아니하면 하나님의 나라를 볼 수 없느니라"

# 글꼴마다 label 윗여백(ascent)이 달라 위쪽 정렬로는 밑선이 어긋난다 — 'H' 잉크 바닥으로 밑선 위치를 재서 맞춘다.
baseline() {  # $1 font -> 첫 줄 밑선의 y
  magick -background none -fill white -font "$1" -pointsize $SIZE label:H -format '%@\n' info: |
    sed -E 's/^[0-9]+x([0-9]+)\+[0-9]+\+([0-9]+)$/\1 \2/' | { read h y; echo $((h + y)); }
}
SHIFT=$(( $(baseline "$MYEONGJO") - $(baseline "$SERIF") ))

block() {  # $1 ref, $2 text, $3 out
  magick -background none -fill white -font "$SERIF" -pointsize $SIZE \
    label:"$1" -gravity west -extent ${REF_W}x \
    -gravity north -splice 0x$SHIFT "$TMP/ref.png"  # -size 를 주면 label 이 칸에 맞춰 글자를 키운다
  magick -background none -fill white -font "$MYEONGJO" -pointsize $SIZE \
    -interline-spacing 18 -size ${TEXT_W}x caption:"$2" "$TMP/text.png"
  magick "$TMP/ref.png" "$TMP/text.png" -background none -gravity north +append "$3"
}
block "Romans 7:24" "$V24" "$TMP/b24.png"
block "Romans 7:25" "$V25" "$TMP/b25.png"
block "John 3:3" "$J33" "$TMP/j33.png"

H24=$(magick identify -format %h "$TMP/b24.png")
H25=$(magick identify -format %h "$TMP/b25.png")
H33=$(magick identify -format %h "$TMP/j33.png")
X=$(( (1920 - REF_W - TEXT_W) / 2 ))
Y24=$(( (1080 - H24 - GAP - H25) / 2 ))
Y25=$(( Y24 + H24 + GAP ))
Y33=$(( (1080 - H33) / 2 ))

magick -size 1920x1080 xc:none "$TMP/b24.png" -geometry +$X+$Y24 -composite verse24.png
magick -size 1920x1080 xc:none "$TMP/b25.png" -geometry +$X+$Y25 -composite verse25.png
magick -size 1920x1080 xc:none "$TMP/j33.png" -geometry +$X+$Y33 -composite john3_3.png
