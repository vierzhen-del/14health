# Galaxy Tab S9 Ultra에 14health 올리기

Tab S9는 이미 Termux + proot(Ubuntu) 위에서 n8n을 돌리는 홈서버다. 14health는
Python이라 **APK를 만들 필요 없이 같은 proot 안에 그대로 설치**하면 된다.
Syncthing이 vault를 다른 기기로 옮겨주므로 zip 내보내기도 필요 없다.

## 1. 설치

```bash
# vault를 proot 안에서 보이게 바인드 (n8n 실행할 때 쓰던 방식과 동일)
proot-distro login ubuntu --bind /storage/emulated/0/Documents/<내vault폴더>:/root/obsidian

# 저장소 받기 + 설치
cd /root && git clone https://github.com/vierzhen-del/14health.git
cd 14health && pip install -e ".[share]"

# (선택) 영수증 사진 OCR
apt install -y tesseract-ocr tesseract-ocr-kor
```

## 2. Vault 지정 — Syncthing 폴더 안으로

```bash
14health init --vault /root/obsidian/14health-vault
```

`/root/obsidian` 은 `/storage/emulated/0/Documents/<내vault폴더>` 이고, 이 폴더는
Syncthing 폴더 `<Syncthing 폴더명>` 으로 **S23U·S26에 자동 복제**된다.
즉 Tab S9에서 입력한 기록이 폰의 옵시디안에도 바로 나타난다.

> **주의** — 여러 기기에서 *동시에* 같은 노트를 고치면 Syncthing 충돌 파일
> (`*.sync-conflict-*`)이 생긴다. 14health는 노트를 임시파일에 쓴 뒤
> `os.replace` 로 바꿔치기해서 **반쯤 쓰인 파일이 동기화되는 일은 없지만**,
> 입력은 한 기기에서 하는 편이 안전하다.

## 3. 실행

```bash
# Tab S9 화면에서만 쓸 때
14health app

# 폰·PC에서 접속할 때 (Tailscale 권장)
14health app --lan
```

`--lan` 을 주면 `0.0.0.0` 에 바인딩하고 **1회용 토큰**이 붙은 주소를 출력한다:

```
14health 앱 실행 중 (LAN 공개): http://100.x.y.z:8420/?t=xxxxxxxx
```

`100.x.y.z` 는 Tab S9의 Tailscale 주소(Tailscale 기기명)다.
tailnet에 붙은 폰·PC에서 이 주소를 열면 된다. 토큰이 없으면 401이고, 한 번
열면 쿠키로 유지된다.

- **공용 와이파이에서는 `--lan` 을 쓰지 말 것** — 같은 네트워크의 아무나 시도할 수 있다.
- cloudflared 임시 터널(`trycloudflare.com`)로는 **열지 말 것**. 건강 기록이 공개 URL에 놓인다.

## 4. 백그라운드 유지

n8n과 같은 방식으로 관리한다.

```bash
# 실행
nohup 14health app --lan > ~/14health.log 2>&1 &
grep -m1 "실행 중" ~/14health.log     # 접속 주소 확인

# 중지
pkill -f "14health app"
```

배터리 최적화가 프로세스를 죽이지 않도록, Syncthing·n8n에 이미 해둔 것처럼
**설정 → 배터리 → Termux → 제한 없음**과 상시 충전을 확인한다.

## 5. Claude CLI와 함께 쓰기

proot 안에 Claude Code CLI가 이미 있으므로 저장소의 스킬을 그대로 쓸 수 있다.

```bash
cd /root/14health && claude
```

`/건강입력` `/검진분석` `/위험분석` `/대시보드` `/vault관리` 가 뜬다.
사진 판독은 tesseract보다 Claude 쪽이 정확하므로, 영수증·결과지는 `/검진분석` 을 권한다.

## 왜 APK가 아닌가

| | proot 배포 (이 문서) | Capacitor APK |
|---|---|---|
| 코드 변경 | 없음 | Python ≈1,400줄을 JS로 포팅 |
| 옵시디안 vault 쓰기 | 이미 바인드됨 | SAF 권한 처리 필요 |
| 다른 기기 동기화 | Syncthing 그대로 | 별도 구현 |
| n8n 연동 | 같은 proot 안이라 CLI 직접 호출 | HTTP 왕복 |
| 홈 화면 아이콘 | 브라우저 "홈 화면에 추가" | 진짜 앱 아이콘 |
| 완전 오프라인 | 서버가 켜져 있어야 함 | 가능 |
| Health Connect(걸음수·심박) | **불가** | 가능 |

**Health Connect 데이터가 필요해지는 시점**이 APK를 만들 이유다. 그 전까지는
proot 배포가 모든 면에서 싸고 빠르다. 자세한 내용은 `docs/APK-로드맵.md`.
