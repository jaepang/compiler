#!/bin/sh
# 사이드 제목 레이어. 각 사이드가 시작할 때(A 는 인트로 뒤) 화면 한가운데 띄우는 1920x1080 투명 PNG 를 만든다.
# 글씨는 fine_frame.png 의 "Fine" 과 같다 — Times New Roman Bold Italic 180pt, 흰색.
# 사이드 배경·LP 위에 얹으므로 바탕은 투명(xc:none)이다.
#
#   ./side_frames.sh            side_A.png ~ side_D.png ("side A" ~ "side D")
#   LABEL=Side ./side_frames.sh  "Side A" 처럼 대문자로
set -eu
cd "$(dirname "$0")"

FONT="/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf"
SIZE=180
LABEL=${LABEL:-side}

for n in A B C D; do
  magick -size 1920x1080 xc:none -font "$FONT" -pointsize $SIZE -fill white \
    -gravity center -annotate +0+0 "$LABEL $n" "PNG32:side_$n.png"
done
