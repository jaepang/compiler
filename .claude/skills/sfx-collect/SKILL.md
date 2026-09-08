---
name: sfx-collect
description: 플레이리스트 영상에 쓸 효과음·사운드스케이프(LP 바늘 소리, 필름 프로젝터 루프, 파도·비·카페 앰비언스, 테이프 히스 등)를 무료 사이트(Mixkit·Pixabay·Freesound)에서 ego-browser 로 찾아 내려받고, 레포의 sfx/ 라이브러리와 sfx/manifest.json(출처·라이선스·크레딧)에 등록하는 스킬. 사용자가 "효과음/SFX/앰비언스/사운드스케이프/배경 소음을 찾아줘·받아줘·수집해줘", 특정 소리 이름(바늘 올리는 소리, 프로젝터, 파도, 빗소리, 크래클…)을 말하거나, 무료 사운드 사이트·라이선스·크레딧을 물을 때, sfx/ 목록·복원·크레딧 문구를 요청할 때 — "스킬"이라고 말하지 않아도 이 스킬을 쓴다.
---

# sfx-collect — 무료 효과음 수집 → sfx/ 라이브러리

이 레포(compiler)는 유튜브 플레이리스트 영상 소스를 관리한다. 효과음은 영상 여러 개에 재사용되므로 **레포 루트 `sfx/`** 에 모으고,
오디오 파일은 gitignore, **`sfx/manifest.json` 만 커밋**한다 — `classification.json` 과 같은 철학이다: 매니페스트만 있으면
다른 머신에서 `sfx.py restore` 로 다시 받고, 크레딧 문구를 설명문에 자동으로 붙일 수 있다.

## 언제 무엇을

요청을 소리 단위로 쪼개고, 각 소리의 **종류**를 먼저 정한다. 종류가 선택 기준을 결정한다.

| 종류 | 예 | 고르는 기준 |
|---|---|---|
| `oneshot` | LP 바늘 올리기/내리기, 테이프 데크 딸깍, 카메라 셔터 | 2~10초, 시작이 명확, 잔향 꼬리가 깨끗한 것 |
| `loop` | 필름 프로젝터 구동음, 턴테이블 크래클, 테이프 히스, 빗소리 | 영상 전체에 깔린다 → 이음새가 티 안 나는 것(길이 20초 이상이면 좋다), 리듬·이벤트가 없는 균일한 소리 |
| `ambience` | 파도, 카페, 숲, 도심 | 3분 이상이면 루프 이음새 부담이 없다. 갈매기 소리처럼 튀는 이벤트가 적은 것 |

한국어 요청은 영어 검색어로 바꿔 검색한다. 자주 쓰는 대응은 `references/sites.md` 의 표에 있다 (예: LP 바늘 → `vinyl needle drop`, 필름 프로젝터 → `film projector`, 파도 → `ocean waves`).

## 사이트 우선순위와 라이선스

사용자 정책: **출처 표기가 필요 없는 것을 우선**, 표기 조건(CC BY)은 허용하되 크레딧을 기록, 수익화 금지(NC)는 거절. 로그인 없는 사이트를 우선.

1. **Mixkit** — WAV 직링크, 로그인·표기 불필요. 양은 적지만 품질이 고르다. 루프용에 특히 좋다.
2. **Pixabay** — MP3, 로그인·표기 불필요, 양이 많다. 카드에 길이가 표시된다.
3. **Freesound** — 가장 방대하다. 검색에 라이선스 필터(`CC0`)를 걸면 표기 불필요. 로그인 없이는 `-hq.mp3` 프리뷰(128kbps)만 받을 수 있고 원본(WAV/FLAC)은 로그인이 필요하다 → 프리뷰로 충분한지 판단하고, 원본이 필요하면 `handOffTaskSpace` 로 사용자에게 로그인을 부탁한다. CC BY 는 표기 문구를 반드시 기록.
4. **Zapsplat** — 로그인 + 표기 조건. 위에서 못 찾을 때만.

라이선스 문자열은 사이트마다 정해진 값을 쓴다 (`references/sites.md`). 라이선스를 확인하지 못한 파일은 등록하지 않는다 — 나중에 영상이 클레임을 받으면 되돌리기 어렵다.

## 절차

1. **계획을 한 줄로 알린다**: 소리별 종류·검색어·1순위 사이트. 사용자가 이미 구체적으로 지시했으면 바로 진행한다.
2. **ego-browser 로 검색**. 태스크 스페이스는 요청 하나에 하나(`useOrCreateTaskSpace('sfx: <요청 요약>')`)를 만들고 heredoc 마다 재사용한다. 사이트별 URL 패턴·DOM 추출 코드·다운로드 방법은 **`references/sites.md` 를 먼저 읽고** 그대로 쓴다 — 셀렉터는 실제로 검증된 것이라 추측으로 바꾸지 않는다.
3. **후보 고르기**: 검색 결과에서 제목·길이·라이선스·페이지 URL 을 뽑아 종류 기준에 맞는 1~3개를 고른다. 길이는 카드/페이지의 표기를 믿되, 받은 뒤 ffprobe 로 실측한다. 사용자가 여러 개 중 고르길 원하면 후보 표를 보여주고 멈춘다; 아니면 최선 1개를 받고 대안은 표로만 남긴다.
4. **다운로드**: Mixkit·Freesound 프리뷰는 `curl -L -o` 로 직접, Pixabay 는 브라우저 다운로드(`Page.setDownloadBehavior` 로 폴더 지정 후 "Free download" 클릭). 스크래치 폴더에 받는다.
5. **등록**: `python3 .claude/skills/sfx-collect/scripts/sfx.py add <파일> --kind … --category … --source … --page-url … --license … [--download-url …] [--attribution …] --tags …`. 스크립트가 `sfx/<category>/<slug>.<ext>` 로 옮기고 ffprobe 로 길이·샘플레이트를 기록한다. 파일명은 슬러그(영문·숫자·하이픈)로 통일해 GarageBand·Resolve 에서 보기 쉽게 한다. `--wav` 를 주면 48kHz WAV 로 변환해 넣는다(GarageBand 는 mp3 도 받지만 루프 편집엔 WAV 가 편하다).
6. **검증**: 등록 출력의 길이가 종류 기준에 맞는지, `mean_volume` 이 -60dB 보다 크면(무음 파일 아님) OK. 루프는 앞뒤 1초 라우드니스가 비슷한지 `sfx.py check` 로 본다.
7. **보고**: 받은 소리 표(파일·길이·출처·라이선스·크레딧 필요 여부), 크레딧이 필요한 항목의 문구(`sfx.py credits`), GarageBand 에 넣는 법 한 줄(Finder 에서 `sfx/<category>/` 파일을 트랙으로 드래그). 대안 후보와 못 찾은 소리를 솔직히 적는다.
8. **마무리**: 스크래치 파일 정리, `completeTaskSpace(task.id, { keep: false })`. 매니페스트 변경은 커밋한다(오디오는 gitignore 라 안 들어간다).

## 지키는 것

- 계정 생성·약관 동의·결제·로그인 입력은 하지 않는다. 로그인이 필요하면 `handOffTaskSpace` 로 넘기고 사용자가 "계속" 하면 `takeOverTaskSpace` 로 재개한다.
- 사이트가 "user is controlling" 을 내면 멈추고 사용자에게 묻는다.
- 같은 소리를 이미 `sfx/manifest.json` 에 갖고 있으면(태그·종류 일치) 새로 받지 않고 알려준다 — `sfx.py list --tags …` 로 먼저 확인.
- 검색 결과가 애매하면 여러 사이트에서 후보를 넓게 모으고, 억지로 하나를 고르지 않는다. "적당한 게 없다"는 것도 결과다.
- 저작권 표기가 있는 상업 라이브러리(Envato Elements·Artlist 등)·유료 사이트의 미리듣기 파일은 받지 않는다.

## 파일 배치

```
sfx/
  manifest.json          커밋. items[]: id, kind, category, tags, file, source, source_id, page_url, download_url, license,
                         attribution_required, attribution, duration, sample_rate, added, note
  vinyl/…  film/…  nature/…  room/…   오디오 (gitignore). category 는 소리 성격 기준 짧은 영문 폴더명
```

`sfx.py` 하위 명령: `add`(등록), `list [--tags …]`, `credits [--all]`(설명문용 문구), `restore`(download_url 있는 항목 재다운로드; Pixabay 처럼 브라우저 다운로드만 되는 항목은 page_url 을 안내), `check <id|file>`(길이·볼륨·루프 이음새).
