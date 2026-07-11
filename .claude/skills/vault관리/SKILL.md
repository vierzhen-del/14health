---
name: vault관리
description: 옵시디안 vault 경로 설정, 기기변경용 전체 내보내기(zip)·가져오기, 노션 이력 동기화. "vault 내보내줘", "새 컴퓨터로 옮기고 싶어", "노션에 이력 정리해줘" 등의 요청에 사용.
---

# vault관리 — 경로·이동·노션 이력

## 경로 설정

```bash
14health init --vault <경로>          # 새 vault 생성 + 경로 등록
14health config set vault <경로>      # 기존 옵시디안 vault 연결 (재생성 없음)
14health config show                  # 현재 설정 확인
```

vault 경로는 **저장소(git) 밖**이어야 한다. 경로가 저장소 안이면 경고하고 다른 경로를 권한다.

## 기기변경 — 내보내기/가져오기

```bash
14health export                       # <vault>/90-내보내기/14health-vault-<날짜>.zip
14health import <zip> --vault <새경로>  # 압축 해제 + vault 경로 자동 전환
```

zip 하나만 새 기기로 옮기면 기존 데이터를 그대로 이어서 쓸 수 있다고 안내한다.

## 노션 이력 동기화 (마스킹된 이력만)

두 가지 방법이 있다:

1. **Notion MCP 사용 (권장)**: `14health log` 로 로컬 이력을 읽고, 노션의
   "14health 이력" 데이터베이스에 행을 추가한다.
   **화이트리스트 필드만 허용**: 제목(마스킹) · 날짜 · 대상(관계호칭) ·
   작업유형 · 옵시디안링크. **절대 금지**: 건강 수치, 증상, 처방약, 실명,
   분석 본문 — 어떤 형태로도 노션에 포함하지 않는다. 제목에 숫자 수치가
   있으면 제거한 뒤 올린다.
2. **CLI 동기화**: 사용자가 노션 integration 토큰을 설정한 경우
   ```bash
   14health config set notion_token <토큰>
   14health config set notion_database_id <DB ID>
   14health log --sync-notion
   ```

동기화 후 "노션에는 이력 요약만, 상세 내용은 옵시디안에" 원칙을 사용자에게 상기시킨다.
