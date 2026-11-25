#!/bin/sh
# 사이드 제목 레이어. 각 사이드가 시작할 때(A 는 인트로 뒤) 화면 한가운데 띄우는 1920x1080 투명 PNG 를 만든다.
# 글씨는 fine_frame.png 의 "Fine" 과 같다 — Times New Roman Bold Italic 180pt, 흰색.
# 사이드 배경·LP 위에 얹으므로 바탕은 투명(xc:none)이다.
# 사이드 B 는 배경(side_b_bg.png)이 아주 밝아 흰 글씨가 안 읽히므로 검은 글씨 side_B_black.png 를 쓴다.
#
#   ./side_frames.sh                       side_A.png ~ side_D.png ("side A" ~ "side D", 흰색) + side_B_black.png
#   LABEL=Side ./side_frames.sh            "Side A" 처럼 대문자로
#   ./side_frames.sh <사이드> <색>          한 장만: 흰색이면 side_<사이드>.png, 그 밖의 색은 side_<사이드>_<색>.png
set -eu
cd "$(dirname "$0")"

FONT="/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf"
SIZE=180
LABEL=${LABEL:-side}

frame() {  # frame <사이드> <색>
  if [ "$2" = white ]; then out="side_$1.png"; else out="side_$1_$2.png"; fi
  magick -size 1920x1080 xc:none -font "$FONT" -pointsize $SIZE -fill "$2" \
    -gravity center -annotate +0+0 "$LABEL $1" "PNG32:$out"
}

if [ $# -eq 2 ]; then
  frame "$1" "$2"
else
  for n in A B C D; do frame $n white; done
  frame B black
fi
