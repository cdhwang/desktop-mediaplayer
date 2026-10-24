# Web Remote Control — 아키텍처 & 데이터 흐름 문서

> **관련 파일**
> | 역할 | 파일 |
> |------|------|
> | HTTP 서버 (QTcpServer 기반) | `src/desktop_music/services/remote/http_server.py` |
> | REST API 라우팅 & 핸들러 | `src/desktop_music/services/remote/remote_service.py` |
> | 플레이어 상태 직렬화 | `src/desktop_music/services/remote/state.py` |
> | ffmpeg MP3 트랜스코딩 & LRU 캐시 | `src/desktop_music/services/remote/transcode.py` |
> | 브라우저 원격 페이지 (HTML+JS) | `src/desktop_music/services/remote/remote.html` |
> | HTML 로더 | `src/desktop_music/services/remote/web.py` |
> | 패키지 초기화 | `src/desktop_music/services/remote/__init__.py` |

---

## 1. 개요

Web Remote Control은 같은 Wi-Fi에 있는 폰, 태블릿, PC 등 **어떤 브라우저로든** 데스크탑 플레이어를 조종할 수 있는 기능이다.

- 데스크탑은 포트 **8787**에 경량 HTTP 서버를 직접 구동한다.
- 브라우저는 `http://<데스크탑-IP>:8787/` 을 열면 된다. 별도 앱 설치 불필요.
- **"Listen here"** 버튼을 누르면 브라우저가 오디오 소스가 되어 폰 스피커로 직접 들을 수 있다. 데스크탑은 뮤트된다.

---

## 2. 레이어 구조

```
브라우저 (remote.html + JS)
    │  WebSocket /ws           ← 서버 → 브라우저 실시간 푸시
    │  REST API (fetch)        ← 브라우저 → 서버 커맨드/상태
    │  GET /api/audio/{index}  ← 오디오 스트림 (MP3)
    ▼
RemoteService (remote_service.py)
    │  QTcpServer 기반 HttpServer
    │  라우팅 → 핸들러 메서드
    ▼
PlayerController / PlaylistModel
    │  Qt 시그널로 상태 변경 통보
    ▼
VLCBackend (libVLC)
```

### 핵심 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| `HttpServer` | `http_server.py` | `QTcpServer` 위에 HTTP/1.1 파서, 라우팅, WebSocket 업그레이드, Range 응답, 논블로킹 파일 스트리밍 구현 |
| `WsConnection` | `http_server.py` | RFC 6455 WebSocket 연결 1개를 표현. 서버→클라이언트 텍스트 프레임(JSON) 전송 |
| `RemoteService` | `remote_service.py` | HTTP 라우트 등록, 핸들러 구현, 오디오 클레임 상태 관리, WS 브로드캐스트 |
| `_TranscodeJob` | `remote_service.py` | `QThreadPool` 워커 — GUI 스레드를 차단하지 않고 ffmpeg 트랜스코딩을 처리 |
| `state.py` | `state.py` | `PlayerController` / `PlaylistModel` → JSON dict 직렬화 (REST 응답 & WS 페이로드 공용) |
| `TranscodeCache` | `transcode.py` | LRU 온디스크 MP3 캐시 (최대 5개), `ffmpeg` 호출 캡슐화 |

---

## 3. API 엔드포인트 목록

### 3.1 페이지

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/` | 원격 조종 HTML 페이지 (≡ `/remote`) |
| `GET` | `/remote` | 위와 동일 |

### 3.2 상태 읽기

| 메서드 | 경로 | 응답 |
|--------|------|------|
| `GET` | `/api/ping` | `{"ok": true, "app": "desktop-music"}` |
| `GET` | `/api/state` | 플레이어 상태 스냅샷 (아래 §4.1 참고) |
| `GET` | `/api/playlist` | 플레이리스트 전체 (아래 §4.2 참고) |
| `GET` | `/api/cover/{index}` | 트랙의 앨범아트 이미지 바이너리 (JPEG/PNG 등) |
| `GET` | `/api/audio/{index}` | 트랙을 MP3로 트랜스코딩한 오디오 스트림 (Range 지원) |

### 3.3 커맨드 전송

| 메서드 | 경로 | 요청 바디 | 설명 |
|--------|------|-----------|------|
| `POST` | `/api/command/{id}` | — | 단순 커맨드 실행 (아래 §4.4 참고) |
| `POST` | `/api/volume` | `{"value": 0..100}` | 볼륨 변경 |
| `POST` | `/api/seek` | `{"fraction": 0.0..1.0}` 또는 `{"ms": int}` | 탐색 |
| `POST` | `/api/play` | `{"index": int}` | 플레이리스트에서 특정 트랙 재생 |
| `POST` | `/api/remove` | `{"index": int}` | 플레이리스트에서 트랙 제거 |

### 3.4 브라우저 오디오 모드 (Listen here)

| 메서드 | 경로 | 요청 바디 | 설명 |
|--------|------|-----------|------|
| `POST` | `/api/audio/claim` | `{"token": str}` (선택) | 브라우저가 오디오 소스 권한 요청 |
| `POST` | `/api/audio/release` | `{"token": str}` (선택) | 오디오 권한 반환, 데스크탑 오디오 복원 |
| `POST` | `/api/remote/state` | `{"position_ms", "length_ms", "state", "token"}` | 브라우저 재생 상태를 데스크탑에 역방향 동기화 (하트비트 겸용) |

### 3.5 WebSocket

| 경로 | 방향 | 설명 |
|------|------|------|
| `GET /ws` (Upgrade) | 양방향 | 서버 → 브라우저: 상태+플레이리스트 JSON 푸시. 브라우저 → 서버: 현재 미사용 (향후 확장 가능) |

---

## 4. 데이터 형식 (JSON 계약)

### 4.1 상태 스냅샷 (`/api/state` 응답, WS 푸시 페이로드)

```jsonc
{
  "state": "playing",       // "playing" | "paused" | "stopped" | "ended" | …
  "position_ms": 42000,     // 현재 재생 위치 (ms)
  "length_ms":   183000,    // 트랙 전체 길이 (ms)
  "volume": 80,             // 0..100
  "muted": false,
  "shuffle": false,
  "repeat": "none",         // "none" | "all" | "one"
  "rate": 1.0,              // 재생 속도
  "current_index": 3,       // 현재 트랙 인덱스 (-1: 없음)
  "remote_mode": false,     // true이면 브라우저가 오디오 소스
  "current": {              // null 가능
    "index": 3,
    "title": "Bohemian Rhapsody",
    "raw_title": "Bohemian Rhapsody",
    "artist": "Queen",
    "duration_ms": 355000,
    "playing": true,
    "is_cue_track": false,
    "has_cover": true
  }
}
```

**remote_mode 시 position_ms/state**: 브라우저가 `POST /api/remote/state`로 보고한 값이 우선 사용된다 (데스크탑 VLC가 뮤트·정지 상태이기 때문).

WS 푸시에는 추가로 `"playlist"` 키가 포함될 수 있다.

### 4.2 플레이리스트 (`/api/playlist`)

```jsonc
{
  "count": 12,
  "current_index": 3,
  "tracks": [
    {
      "index": 0,
      "title": "Artist - Title",     // display_title 또는 파일명 폴백
      "raw_title": "Title",
      "artist": "Artist",
      "duration_ms": 240000,
      "playing": false,
      "is_cue_track": false,
      "has_cover": true
    }
    // …
  ]
}
```

### 4.3 클레임 응답 (`/api/audio/claim`)

```jsonc
{
  // 상태 스냅샷(§4.1) 필드 모두 포함 +
  "audio_token": "abc123…",   // 이후 모든 클레임 관련 요청에 첨부
  "resume_ms": 15200,         // 클레임 직전 데스크탑 재생 위치
  "resume_playing": true      // 클레임 직전 재생 중이었는지 여부
}
```

### 4.4 지원 커맨드 (`POST /api/command/{id}`)

```
play_pause  stop  next  previous
seek_forward  seek_backward  seek_forward_long  seek_backward_long
volume_up  volume_down  mute
toggle_shuffle  cycle_repeat
rate_up  rate_down  rate_reset
```

---

## 5. 시나리오별 데이터 흐름

### 시나리오 A — 기본 원격 조종 (폰에서 트랙 선택)

```
폰 브라우저                        데스크탑 (RemoteService)         VLC
    │  WebSocket 연결 /ws              │                               │
    │ ────────────────────────────── ► │                               │
    │                                  │ 현재 스냅샷 즉시 푸시            │
    │ ◄ ─────────────────────────────  │                               │
    │  applyState() / renderPlaylist() │                               │
    │                                  │                               │
    │  POST /api/play {"index": 5}     │                               │
    │ ────────────────────────────── ► │ controller.play_row(5)        │
    │                                  │ ─────────────────────────── ► │
    │                                  │ media_changed 시그널           │
    │                                  │ ─ WS 브로드캐스트 (state+pl) ─►│
    │ ◄ ─────────────────────────────  │                               │
    │  applyState(): nowTitle 업데이트  │                               │
```

### 시나리오 B — 볼륨 / seek 변경

```
폰 브라우저                        RemoteService                   VLC
    │                                  │                               │
    │  볼륨 슬라이더 드래그 후 change      │                               │
    │  POST /api/volume {"value": 60}  │                               │
    │ ────────────────────────────── ► │ controller.set_volume(60)     │
    │                                  │ ─────────────────────────── ► │
    │  응답: 최신 스냅샷                 │ volume_changed 시그널          │
    │ ◄ ─────────────────────────────  │ ─ WS 브로드캐스트 ────────── ► │
    │  applyState(): vol 슬라이더 갱신   │                               │
    │                                  │                               │
    │  seek 바 드래그 후 change          │                               │
    │  POST /api/seek {"fraction":0.5} │                               │
    │ ────────────────────────────── ► │ controller.seek_to_fraction() │
    │                                  │ ─ seeked 시그널 → WS 브로드캐스트│
    │ ◄ ─────────────────────────────  │                               │
```

### 시나리오 C — "Listen here" (브라우저 오디오 클레임)

```
폰 브라우저                  RemoteService              VLC          ffmpeg
    │                           │                         │              │
    │  POST /api/audio/claim    │                         │              │
    │  {"token": "abc123"}      │                         │              │
    │ ─────────────────────── ► │ set_remote_mode(True)  │              │
    │                           │ ─── VLC 뮤트 ────────► │              │
    │  응답: {audio_token,       │                         │              │
    │         resume_ms: 15200, │                         │              │
    │         resume_playing: T}│                         │              │
    │ ◄ ─────────────────────── │                         │              │
    │                           │                         │              │
    │  GET /api/audio/5         │                         │              │
    │  (audio.src = URL)        │                         │              │
    │ ─────────────────────── ► │ _TranscodeJob 실행      │              │
    │                           │ ─────────────────────────────────── ► │
    │                           │                         │  ffmpeg 트랜스코딩 |
    │                           │ ◄ ───────────────────────────────── ── │
    │  206 Partial Content      │                         │              │
    │  (MP3 스트림, Range 지원)  │                         │              │
    │ ◄ ─────────────────────── │                         │              │
    │  <audio> 재생 시작         │                         │              │
    │  currentTime = 15.2       │                         │              │
    │                           │                         │              │
    │  ─ 1초마다 하트비트 ──────►│ set_remote_report()    │              │
    │  POST /api/remote/state   │ (position_ms 미러링)    │              │
    │  {token, position_ms,     │                         │              │
    │   length_ms, state}       │                         │              │
    │                           │                         │              │
    │  트랙 종료 → command("next")│                         │              │
    │ ─────────────────────── ► │ controller.dispatch()  │              │
    │                           │ ─ media_changed → WS ──►│              │
    │ ◄ ─────────────────────── │                         │              │
    │  applyState(): 다음 트랙   │                         │              │
    │  loadIndex(new_index)     │                         │              │
```

### 시나리오 D — 클레임 해제 & 데스크탑 오디오 복원

```
폰 브라우저                  RemoteService              VLC
    │                           │                         │
    │  POST /api/audio/release  │                         │
    │  {"token": "abc123"}      │                         │
    │ ─────────────────────── ► │ set_remote_mode(False) │
    │                           │ ─── VLC 언뮤트 ───────► │
    │  응답: {audio_token: null} │                         │
    │ ◄ ─────────────────────── │                         │
    │  audio.pause()            │                         │
    │  Listen here 버튼 리셋    │                         │
```

### 시나리오 E — 클레임 자동 만료 (브라우저 탭 닫힘)

```
폰 브라우저                  RemoteService
    │  (탭 닫힘 / 네트워크 단절)  │
    │                           │ _CLAIM_TIMEOUT_S = 6.0s 동안 하트비트 없음
    │                           │
    │                           │ _expire_stale_claim() (2초 주기 QTimer)
    │                           │ → _release_claim()
    │                           │ → set_remote_mode(False)  VLC 언뮤트
```

### 시나리오 F — WebSocket 실시간 위치 동기화 (데스크탑 소스 모드)

```
RemoteService                       폰 브라우저
    │  10초마다 _drift_timer 발동      │
    │  build_state_snapshot() 호출    │
    │  position_ms 포함               │
    │  WS 브로드캐스트ㅡ────────────► │
    │                                 │ desktopPos / desktopLen 갱신
    │                                 │ rAF 루프가 보간하여 seek 바 부드럽게 이동
    │                                 │
    │  state_changed / seeked 시그널  │
    │  → 즉시 WS 브로드캐스트 ─────── ► │
    │                                 │ applyState(): seek 바 스냅
```

---

## 6. 오디오 스트리밍 & 캐시 상세

### 6.1 트랜스코딩 흐름

1. 브라우저가 `<audio src="/api/audio/5">` 설정 → `GET /api/audio/5` 요청
2. `RemoteService._h_audio()` → `TrackRef(path, start_ms, end_ms)` 생성
3. `_TranscodeJob`을 `QThreadPool` 워커에 투입 (GUI 스레드 비차단)
4. 워커에서 `TranscodeCache.get_or_create()` 호출:
   - **캐시 히트**: 파일 mtime 터치 후 즉시 경로 반환
   - **캐시 미스**: `ffmpeg -i input.flac -c:a libmp3lame -q:a 2 output.mp3` 실행 → 완료 후 캐시 디렉터리에 저장 → LRU 초과 시 오래된 파일 삭제
5. 워커가 `req.respond_later(Response.file(...))` 호출 → QueuedConnection으로 GUI 스레드에 전달
6. `HttpServer._send_file()` → `_FileStreamer`로 비차단 청크 스트리밍 (256 KB 하이워터마크, `bytesWritten` 시그널 구동)
7. `Range: bytes=N-M` 헤더 지원 → `206 Partial Content` 응답으로 브라우저 seek 동작

**캐시 키**: `sha1(path | mtime | size | start_ms | end_ms)` → 파일 교체 시 자동 무효화

**캐시 위치**: `~/.cache/desktop-music/stream/` (최대 5개 MP3)

### 6.2 Cue Sheet 트랙

`track.start_ms` / `track.end_ms` 값이 있으면 ffmpeg 명령에 `-ss start -t duration`이 추가되어 해당 세그먼트만 트랜스코딩된다.

---

## 7. 오디오 클레임 동시성 제어

```
_claim_token  : str | None   현재 클레임 보유자의 토큰
_claim_seen   : float        마지막 하트비트의 monotonic 타임스탬프
_CLAIM_TIMEOUT_S = 6.0       이 시간 동안 하트비트 없으면 클레임 만료
_CLAIM_SWEEP_MS = 2000       만료 체크 주기 (QTimer)
```

- **한 번에 한 클라이언트만** 클레임 가능. 두 번째 클라이언트가 시도하면 `409 Conflict`.
- 토큰은 브라우저가 `crypto.randomUUID()`로 생성하여 이후 모든 `/api/remote/state`, `/api/audio/release` 요청에 첨부한다.
- 클레임 보유자만 `set_remote_report()`를 통해 데스크탑 UI의 위치 미러를 갱신할 수 있다.

---

## 8. WebSocket 푸시 트리거

`RemoteService._connect_signals()`에서 다음 Qt 시그널을 WS 브로드캐스트에 연결한다:

| 시그널 (PlayerController) | 트리거 조건 |
|---------------------------|-------------|
| `state_changed` | 재생/일시정지/중지 상태 변화 |
| `media_changed` | 트랙 변경 |
| `volume_changed` | 볼륨 변경 |
| `play_mode_changed` | shuffle/repeat 변경 |
| `seeked` | 데스크탑에서 seek 발생 |

| 시그널 (PlaylistModel) | 트리거 조건 |
|------------------------|-------------|
| `rowsInserted` / `rowsRemoved` | 플레이리스트 항목 추가/제거 |
| `dataChanged` | 트랙 메타데이터 변경 |
| `modelReset` / `layoutChanged` | 플레이리스트 전체 갱신 |

추가로 **10초 주기 `_drift_timer`**가 WS 브로드캐스트를 트리거하여 브라우저 seek 바를 정기적으로 보정한다.

---

## 9. 스레딩 모델

| 스레드 | 담당 |
|--------|------|
| **Qt GUI 스레드** | `HttpServer`, `RemoteService`, 모든 라우트 핸들러, WebSocket 송수신, Qt 시그널 처리 |
| **QThreadPool 워커** | `_TranscodeJob.run()` (ffmpeg 호출). GUI 스레드를 절대 차단하지 않음 |

워커 스레드에서 완성된 응답은 `_deferred` (QueuedConnection 시그널)로 GUI 스레드에 안전하게 전달된다.

---

## 10. 보안 고려사항

- 인증 없음 — 신뢰하는 로컬 네트워크에서만 활성화 권고
- `_MAX_REQUEST_BYTES = 1 MiB` 제한으로 메모리 소진 방어
- `Access-Control-Allow-Origin: *` 설정 (LAN 전용 제어 채널)
- 앨범아트·오디오 응답에 `Cache-Control: no-store`를 적용하여 인덱스 변경 후 브라우저 캐시 오염 방지
