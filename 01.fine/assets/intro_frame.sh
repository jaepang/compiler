#!/bin/sh
# 인트로 레이어. 손그림 아래에 안내 문구(한글 Pretendard Light + 영문 Times 기울임)를 둔 1920x1080 투명 PNG 를 만든다.
#   intro_card.png  : 헤드폰 그림 (intro_headphones.png)
#   intro_card2.png : LP 네 장 그림 (intro_lp4.png, Codex 로 받을 예정 — 없으면 건너뛴다)
# 그림은 검은 배경에 흰 선이라 밝기를 알파로 바꿔 배경색과 상관없이 얹을 수 있게 한다.
# 배경의 1/255 잡티도 FilmCraft 선형광 합성에서는 회색 사각형으로 보여 -level 로 완전히 투명하게 자른다.
#
#   ./intro_frame.sh                  두 장 모두
#   ./intro_frame.sh 2 <그림> <출력>   두 번째 장면만, 다른 그림으로 (후보 미리보기용)
set -eu
cd "$(dirname "$0")"

SERIF="/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"
GOTHIC="fonts/Pretendard-Light.otf"   # Pretendard Light (OFL, fonts/Pretendard-OFL.txt). 다른 맥에서도 같게 나오도록 레포에 둔다
KO_SIZE=40
EN_SIZE=38
GAP_ART=80     # 그림과 첫 줄 사이
GAP_LINE=20    # 줄 사이
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# $1 그림, $2 그림 높이(선 기준, 여백은 잘라 낸 뒤), $3 출력, $4 영문, $5… 한글 줄
card() {
  art=$1 h=$2 out=$3 en=$4
  shift 4
  magick "$art" -colorspace gray -level 2%,100% -trim +repage -resize x$h \
    -alpha copy -fill white -colorize 100 "$TMP/art.png"
  set -- "$@" ""   # 한글 줄들 다음에 영문 줄을 이어 붙이기 위한 표시
  lines=""
  i=0
  for ko in "$@"; do
    [ -z "$ko" ] && break
    i=$((i + 1))
    magick -background none -fill white -font "$GOTHIC" -pointsize $KO_SIZE label:"$ko" "$TMP/ko$i.png"
    lines="$lines $TMP/ko$i.png ( -size 1x$GAP_LINE xc:none )"
  done
  magick -background none -fill white -font "$SERIF" -pointsize $EN_SIZE label:"$en" "$TMP/en.png"
  # shellcheck disable=SC2086
  magick $lines "$TMP/en.png" -background none -gravity center -append "$TMP/text.png"
  magick "$TMP/art.png" \( -size 1x$GAP_ART xc:none \) "$TMP/text.png" -background none -gravity center -append "$TMP/block.png"
  magick -size 1920x1080 xc:none "$TMP/block.png" -gravity center -composite "$out"
}

card1() {
  card intro_headphones.png 400 intro_card.png "Best experienced with headphones" \
    "헤드폰으로 들을 때 가장 온전하게 들립니다"
}
card2() {  # $1 그림, $2 출력
  card "$1" 360 "$2" "Side A to Side D" \
    "이 영상은 A~D 네 사이드로 이루어진 앨범입니다" \
    "사이드 단위로 들어 주세요"
}

if [ "${1:-}" = 2 ]; then
  card2 "$2" "$3"
  exit
fi
card1
if [ -f intro_lp4.png ]; then
  card2 intro_lp4.png intro_card2.png
else
  echo "intro_lp4.png 가 없어 두 번째 장면은 건너뜀" >&2
fi
