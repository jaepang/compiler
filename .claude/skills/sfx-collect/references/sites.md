# 사이트별 레시피 (2026-09-09 ego-browser 로 실제 확인)

모든 코드는 `ego-browser nodejs <<'EOF' … EOF` heredoc 안에서 실행한다. 첫 줄은 항상 태스크 스페이스 재사용:
`const task = await useOrCreateTaskSpace('sfx: …')`. 페이지를 열 때는 `await openOrReuseTab(url, { wait: true, timeout: 30 }); await wait(2)`.

## 검색어 표 (한국어 → 영어)

| 요청 | 검색어 | 종류 |
|---|---|---|
| LP 바늘 올리기/내리기, 턴테이블 시작 | `vinyl needle drop`, `record player start`, `turntable needle` | oneshot |
| LP 크래클·표면 노이즈 | `vinyl crackle`, `record surface noise` | loop |
| 영화 필름 프로젝터 | `film projector`, `movie projector`, `8mm projector` | loop |
| 카세트·테이프 히스 | `tape hiss`, `cassette deck` | loop / oneshot(버튼) |
| 파도 | `ocean waves`, `sea waves beach` | ambience |
| 비 | `rain ambience`, `rain on window` | ambience |
| 카페·거리 | `cafe ambience`, `city street ambience` | ambience |
| 라디오 튜닝·잡음 | `radio tuning`, `radio static` | oneshot / loop |

## Mixkit (mixkit.co) — 1순위

- 카테고리 URL: `https://mixkit.co/free-sound-effects/<category>/` (예 `movie-projector`, `sea`, `vinyl`, `rain`). 검색은 상단 검색창(`snapshotText()` 로 ref 확인 후 `fillInput`).
- 라이선스: **Mixkit Sound Effects Free License** — 상업 이용 가능, 표기 불필요. 매니페스트 `--license "Mixkit Sound Effects Free License"`.
- 카드마다 "Download Free SFX" 버튼(`button.download-button--icon`)이 있고 `data-download--button-modal-url-value="/free-sound-effects/download/<id>/…"` 에 id 가 있다.
- **직링크**: `https://assets.mixkit.co/active_storage/sfx/<id>/<id>.wav` (WAV 만 200, `.mp3` 는 403). `curl -L -o out.wav <url>` 로 받는다.
- 카드 추출:

```js
const cards = await js(String.raw`(() => [...document.querySelectorAll('.item-grid-card')].map(c => ({
  title: (c.querySelector('h2, h3, [class*="title"]')?.innerText || c.innerText.split('\n')[0]).trim(),
  duration: (c.innerText.match(/\b\d+:\d\d\b/) || [''])[0],
  id: (c.querySelector('button.download-button--icon')?.dataset['download-ButtonModalUrlValue'] || '').match(/download\/(\d+)/)?.[1],
  page: location.href })).filter(x => x.id))()`)
```
  → `download_url = https://assets.mixkit.co/active_storage/sfx/${id}/${id}.wav`, `source_id = id`, `page_url = 카테고리 URL`.

## Pixabay (pixabay.com/sound-effects) — 2순위

- 검색 URL: `https://pixabay.com/sound-effects/search/<query%20with%20spaces>/`. 결과 카드(20개/페이지)에 제목·작성자·길이(`0:15`)·태그가 있고, 제목 링크가 상세 페이지(`/sound-effects/<slug>-<id>/`).
- 라이선스: **Pixabay Content License** — 상업 이용 가능, 표기 불필요. `--license "Pixabay Content License"`.
- 처음 열면 쿠키 모달이 뜬다. `snapshotText()` 에서 `"Reject All"` 버튼 ref 를 찾아 클릭(없으면 `xpath=//button[contains(., "Reject All")]`). 모달이 남아 있으면 그 뒤 클릭이 전부 모달에 먹힌다 — `Accept All Cookies` 텍스트가 스냅샷에서 사라졌는지 확인.
- 검색 카드 추출:

```js
const cards = await js(String.raw`(() => [...document.querySelectorAll('[class*="audioRow"], [class*="row--"]')].map(r => {
  const a = r.querySelector('a[href*="/sound-effects/"]'); const t = r.innerText.replace(/\s+/g, ' ')
  return { title: a?.innerText.trim(), url: a?.href, duration: (t.match(/\b\d+:\d\d\b/) || [''])[0], text: t.slice(0, 160) } }).filter(x => x.url))()`)
```
- **다운로드는 브라우저로만** 된다(직링크 없음, 형식은 MP3). 상세 페이지에서:

```js
await cdp('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: '<스크래치 절대경로>' })
const snap = await snapshotText(); const lines = snap.split('\n'); const i = lines.findIndex(l => /text "Free download"/.test(l))
let ref = null; for (let k = i; k >= i - 3; k--) { const m = lines[k].match(/ref=(\d+)/); if (m) { ref = m[1]; break } }
await click('@' + ref, { label: 'download sound' }); await wait(6)
```
  → 스크래치 폴더에 `<작성자>-<슬러그>-<id>.mp3` 가 생긴다(확인: `ls`). `download_url` 은 비워 두고 `page_url` 을 기록한다(복원은 이 페이지에서 다시 클릭).

## Freesound (freesound.org) — 3순위

- 검색 URL: `https://freesound.org/search/?q=<q>&f=license:"Creative Commons 0"` (CC0 만). 표기 조건까지 허용하면 `f=license:"Attribution"` 도 추가 검색. `Attribution Noncommercial` 은 쓰지 않는다.
- 카드(`.bw-search__result` 등)에 길이·제목 링크(`/people/<user>/sounds/<id>/`)·`License: …` 텍스트가 있고, 플레이어 요소에 `data-mp3`/`data-ogg` 프리뷰 URL 이 있다. 프리뷰 HQ: `data-mp3` 의 `-lq` 를 `-hq` 로 바꾼 URL (`https://cdn.freesound.org/previews/<nnn>/<id>_<x>-hq.mp3`, 128kbps).
- 상세 페이지 정보 박스에 `Type Flac (.flac) Duration 0:15.248 Sample rate 48000.0 Hz Bit depth 24 bit` 식으로 원본 스펙이 있다.
- 원본 다운로드 링크는 `/people/<user>/sounds/<id>/download/<filename>` 이고 **로그인 없이는 "Login to download"** 다. 원본이 필요하면 `await handOffTaskSpace(task.id)` 후 사용자에게 로그인을 부탁하고, 확인을 받으면 `takeOverTaskSpace(task.id)` → `Page.setDownloadBehavior` + 다운로드 링크 클릭.
- 라이선스 문자열: `CC0 1.0` 또는 `CC BY 4.0`. CC BY 는 `--attribution "<제목> by <작성자> — freesound.org/people/<user>/sounds/<id>/ — CC BY 4.0"` 를 기록한다(다운로드 모달의 attribution 문구가 있으면 그것을 그대로).

## Zapsplat (zapsplat.com) — 예비

- 로그인 필요, 무료 계정은 표기 조건: `--license "Zapsplat Standard License" --attribution "Sound from Zapsplat.com"`. 위 세 곳에서 못 찾을 때만, 사용자 동의 후 handoff 로 로그인.

## 공통 함정

- `snapshotText()` 의 `@N` ref 는 마지막 스냅샷에서만 유효하다. 클릭 뒤에는 다시 스냅샷.
- 텍스트 노드(`text "Free download"`)에는 ref 가 없다 — 바로 위 `button [ref=…]` 줄을 찾는다.
- `drainEvents()` 로 다운로드 URL 을 잡으려 하지 말 것(네트워크 이벤트가 오지 않았다). 파일은 `Page.setDownloadBehavior` 폴더에서 확인한다. `Browser.setDownloadBehavior` 는 이 세션에서 안 된다.
- Pixabay 재생 버튼은 `<audio>` 요소를 만들지 않는다 — 프리뷰 URL 추출 불가, 다운로드로만.
