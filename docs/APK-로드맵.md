# APK 로드맵

**지금은 만들지 않는다.** Tab S9의 proot 배포(`tabs9-배포.md`)가 코드 변경 없이
같은 일을 하고, Syncthing·n8n·Claude CLI와도 그대로 맞물린다.

## APK를 만들 이유가 생기는 시점

1. **Health Connect 데이터가 필요할 때** — 걸음수·심박·수면·HRV는 안드로이드
   온디바이스 API라 Python에서 읽을 수 없다. 이것 하나가 유일하게 APK를 강제한다.
2. Tab S9를 켜두지 않고도 폰 단독으로 쓰고 싶을 때
3. 가족 구성원 각자가 자기 폰에서 독립적으로 입력해야 할 때

이 중 하나라도 실제 필요가 생기기 전에는 착수 비용이 회수되지 않는다.

## 만들 때의 구성

**Capacitor** (웹 UI를 그대로 감싸므로 `app.html`을 재사용할 수 있다)

```
14health-app/
├── www/            app.html + 포팅한 JS 로직
├── android/        Capacitor가 생성 (Gradle 프로젝트)
└── capacitor.config.ts
```

### 포팅 대상 (약 1,400줄)

| 모듈 | 줄수 | 난이도 | 비고 |
|---|---:|---|---|
| `vault.py` | ~300 | 중 | frontmatter 파싱/쓰기 → `js-yaml` + Filesystem |
| `parse.py` | ~330 | 중 | 정규식 위주라 거의 그대로 옮겨짐 |
| `recommend.py` | ~180 | 하 | YAML을 JSON으로 바꿔 번들 |
| `analysis.py` | ~250 | 중 | 순수 계산 |
| `relations.py` | ~130 | 하 | 순수 계산 |
| `calendar_index.py` | ~90 | 하 | 순수 계산 |
| `insurance.py` | ~150 | 하 | 순수 계산 |

`webapp.py`·`cli.py`는 옮기지 않는다(서버가 사라지므로).

### 플러그인

- **@capacitor/filesystem** — 옵시디안 vault 폴더 읽기/쓰기.
  안드로이드 11+ 는 **SAF(Storage Access Framework)** 로 사용자가 폴더를 직접
  골라줘야 한다. `/storage/emulated/0/Documents/<내vault폴더>` 를 선택하면
  Syncthing 폴더와 같은 곳이라 기존 동기화가 그대로 이어진다.
- **온디바이스 OCR** — 둘 중 택1
  - *ML Kit Text Recognition* (한국어 지원, 정확·빠름, 네이티브 플러그인 필요)
  - *tesseract.js* (WASM, 순수 JS, 한국어 traineddata 약 15MB 번들)
- **Health Connect** — `androidx.health.connect` 를 감싸는 커스텀 플러그인.
  읽기 권한(`READ_STEPS`, `READ_HEART_RATE`, `READ_SLEEP`)을 선언한다.

### 빌드 환경

이 컨테이너에 **Java 21 · Gradle 8.14 · Node 22**가 이미 있다. Android SDK
(command-line tools + platform 34 + build-tools)만 받으면 `./gradlew assembleDebug`
로 APK가 나온다. 서명 없이 사이드로드하면 되므로 Play 스토어 심사는 불필요하다.

> **Play 스토어에 올릴 경우** Health Connect 데이터 타입 사용에 Google 승인이
> 필요하다. 가족끼리 사이드로드로 쓴다면 해당되지 않는다.

### 예상 순서

1. Capacitor 스캐폴드 + `app.html` 이식, 로컬 스토리지로 동작 확인
2. Filesystem/SAF로 vault 읽기·쓰기 (여기가 가장 까다롭다)
3. 계산 모듈 포팅 + Python 테스트를 JS로 옮겨 동등성 확인
4. OCR 플러그인
5. Health Connect 플러그인 — **이 단계가 APK의 존재 이유**
6. 서명·배포(가족 기기에 사이드로드)

## 그때까지의 대안

- 폰에서 쓰기: `14health app --lan` + Tailscale (`tabs9-배포.md`)
- 홈 화면 아이콘: 브라우저의 "홈 화면에 추가"
- 걸음수 등: 삼성헬스/구글핏 앱에서 직접 확인하고, 필요하면 검진 입력에 수동 기록
