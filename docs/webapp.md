# 로컬 웹앱 (`14health app`)

`src/health14/webapp.py` + `src/health14/templates/app.html` — 표준 라이브러리 `http.server` 만 사용하는
`127.0.0.1` 전용 GUI.

## 동작

- 최초 실행 시 `/api/state` 의 `hasVault` 가 false면 Vault 생성 화면을 보여준다.
- 생성 후에는 config에 경로가 저장되어 재실행해도 다시 뜨지 않는다.

## 구조 원칙

CLI(`intake.py`, `vault.py`, `analysis.py` 등)를 그대로 재사용하는 **얇은 API 레이어**다.
새 로직은 가능한 한 CLI 모듈에 추가하고 webapp은 호출만 하도록 유지한다.

## 템플릿 제약

`templates/dashboard.html`, `templates/app.html` 은 **단일 자립형**이다 —
외부 CDN·폰트·API 참조를 추가하지 말 것.
