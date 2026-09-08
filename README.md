# 재생목록 다운로드 (yt-dlp CLI)

`playlist_dl.py` 는 brew 로 설치한 `yt-dlp` 명령을 subprocess 로 호출한다. pip 의 yt_dlp 모듈은 필요 없다.

```bash
brew install yt-dlp ffmpeg          # 이미 있으면 생략. brew 의 yt-dlp 는 썸네일 임베드용 mutagen 포함
cd ~/code/compiler
python3 playlist_dl.py --cookies-from-browser chrome --dry-run   # 분류·파일명·선택 포맷 확인 (다운로드 없음)
python3 playlist_dl.py --cookies-from-browser chrome             # 실제 다운로드 → 01.욕망은오랜병/downloads/
python3 playlist_dl.py --restore --cookies-from-browser chrome   # 다른 머신에서: classification.json 대로 그대로 다시 받기 (TUI 로 프로젝트 선택)
```

- 브라우저는 프리미엄 로그인된 쪽으로: `chrome` / `whale` / `safari` / `firefox`
- yt-dlp 가 PATH 에 없으면 `--yt-dlp /opt/homebrew/bin/yt-dlp`
- 포맷 기본값은 **YouTube 영상 제작·업로드 호환**: 음원은 AAC `.m4a`(프리미엄 256k), 영상은 H.264 + AAC `.mp4` (YouTube 권장 업로드 사양과 동일, Final Cut/Premiere/DaVinci/iMovie 에서 바로 열림)
  - 최고 품질(VP9/AV1 4K, opus)을 원하면 `--video-container mkv --audio-codec best`
- 파일명: `{nn}.{영상명(한글 우선)}.{확장자}`  예) `01.아침의 빛.m4a`, `03.병.m4a`, `12.Nothing But Thieves - Ban All the Music (Live at The O2).mp4`
- dry-run 에서 음원이 `141  mp4a.40.2 256k` 로 나오면 프리미엄 포맷이 잡힌 것. `140 … 128k` 만 나오면 쿠키가 안 읽힌 상태(카탈로그 음원 기준)
- 분류 규칙과 결과는 `playlist_dl.py` 상단 docstring 과 실행 후 생기는 `01.욕망은오랜병/classification.json` 참고
- 선택: `pip install pillow` 하면 규칙 5(스토리보드로 정지 이미지 판별)까지 동작. 이 재생목록 19곡은 규칙 1~4 로 모두 결정되므로 없어도 됨
- 오프라인 테스트: `python3 test_offline.py` (fixture_meta.json 의 실제 메타데이터 + `--load-info-json` 으로 yt-dlp 인자 검증. pillow 없으면 스토리보드 섹션은 건너뜀)
- 다른 머신에서 복원: `git clone` 후 `python3 playlist_dl.py --restore [DIR ...]`. 재생목록 조회·분류 없이 `classification.json` 의 index/name/mode/url 그대로 받으므로 재생목록이 바뀌어도 원본과 같은 파일명·포맷. DIR 생략 시 curses TUI 에서 프로젝트를 고른다(`전부 복원` 행 포함). `--only ID`·`--dry-run` 조합 가능
- git: `downloads/`·`archive_*.txt`·미디어 확장자는 `.gitignore`. 커밋되는 산출물은 각 프로젝트의 `classification.json`(복원 매니페스트)만. archive 는 머신 로컬 상태라 커밋하면 다른 머신에서 전부 스킵되니 올리지 말 것
