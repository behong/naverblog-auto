# 토스쇼핑 네이버 블로그 글 도우미

토스쇼핑 상품명과 쉐어링크를 붙여넣으면 다음 내용을 준비하는 로컬 프로그램입니다.

- 광고 수수료 안내 문구가 포함된 블로그 초안
- 상품에 맞춘 태그
- 토스 상품 페이지의 대표 이미지
- 네이버 블로그 글쓰기 바로가기

로그인 정보나 작성한 글은 외부 서버에 저장하지 않습니다. 상품 페이지를 읽기 위해 토스쇼핑에만 접속합니다.

자동 발행 작업을 연결하면 발행 이력과 실패 원인은 별도로 설정한 PostgreSQL에 저장하고, 성공·실패 알림은 선택적으로 텔레그램에 전송할 수 있습니다. 네이버 또는 제휴 서비스의 로그인 정보는 저장하지 않습니다.

## 실행

Windows에서 `start.bat`을 더블클릭합니다. 브라우저가 자동으로 열리지 않으면 다음 주소로 접속합니다.

```text
http://127.0.0.1:8765
```

종료할 때는 검은 실행 창을 닫거나 `Ctrl+C`를 누릅니다.

## Docker 실행

실행:

```powershell
cd C:\Users\Administrator\code\naverblog-auto
Copy-Item .env.example .env
docker compose up -d --build
```

배포에는 `deploy.ps1`을 사용합니다. 이 스크립트는 Total10의 `.env.docker.cutover`에서 `TOSS_OPEN_API_*` 변수만 자동으로 읽으며, Total10의 다른 환경변수는 전달하지 않습니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
```

상품 가격과 대표 이미지는 토스 production Open API만 사용합니다. 쿠키 조회 fallback은 없으며, Open API 조회 실패 시 가격을 직접 입력할 수 있습니다. API 키와 토큰은 브라우저 응답이나 로그에 포함하지 않습니다.

확인:

```text
http://127.0.0.1:8765
http://127.0.0.1:8765/health
```

중지:

```powershell
docker compose down
```

`/health`는 PostgreSQL과 production Open API 토큰 발급을 함께 검증합니다. 모든 상태가 `ok`이고 Open API 환경이 `production`이어야 배포가 성공합니다.

## Cloudflare Tunnel 연결

기존 Cloudflare Tunnel을 사용한다면 Public Hostname의 서비스 주소를 다음으로 지정합니다.

```text
http://naverblog-auto:8765
```

이 주소는 `cloudflared`가 이 Compose의 Docker 네트워크에 있을 때 사용합니다. Cloudflare Tunnel이 Windows 호스트에서 실행 중이라면 다음 주소를 사용합니다.

```text
http://127.0.0.1:8765
```

별도 cloudflared 컨테이너를 함께 실행하려면 Cloudflare에서 발급한 Tunnel 토큰을 현재 PowerShell 세션에 넣고 선택 프로필을 실행합니다.

```powershell
$env:CLOUDFLARE_TUNNEL_TOKEN="Cloudflare에서 발급한 토큰"
docker compose -f docker-compose.yml -f docker-compose.cloudflare.yml --profile cloudflare up -d --build
```

Cloudflare 대시보드의 해당 Tunnel에서 Public Hostname을 만들고 서비스 주소를 `http://naverblog-auto:8765`로 설정합니다. 외부 공개 전에는 Cloudflare Access 정책으로 본인 이메일만 허용하는 구성을 권장합니다. HTTPS 도메인에서는 이미지 포함 클립보드 복사 기능도 동작합니다.

## 사용 순서

1. 토스 쉐어링크 관리자에서 **링크 발급**을 눌러 상품명과 링크를 복사합니다.
2. 복사한 내용을 입력창에 붙여넣습니다. 가격은 토스 production Open API로 자동 조회합니다.
3. Open API 조회가 실패하면 가격을 직접 입력합니다.
4. **블로그 글 만들기**를 누릅니다.
5. 만들어진 제목과 본문을 필요한 만큼 수정합니다.
6. **네이버 열기 + 제목 복사**를 누르고 네이버 제목 칸에 붙여넣습니다.
7. 도우미 화면으로 돌아와 **2. 이미지 복사**를 누른 뒤 네이버 본문에 붙여넣습니다.
8. 다시 도우미로 돌아와 **3. 본문·태그 복사**를 누른 뒤 네이버의 이미지 아래에 붙여넣습니다.
9. 이미지 복사가 차단되면 **이미지 저장** 후 네이버 사진 첨부를 이용합니다.
10. 최종 내용을 확인하고 직접 발행합니다.

본문은 다음과 같이 짧게 생성되고, 태그는 마지막에 자동으로 붙습니다.

```text
[이미지 영역]

상품 자세히 보기
https://toss.im/_m/상품링크

✱ 이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.

#상품태그 #상품추천 #쇼핑추천 #실속구매 #토스쇼핑
```

제목은 `상품명, 용량/구성, 가격원`처럼 간단하게 생성하며 가격은 항상 마지막에 들어갑니다. 가격은 토스 production Open API에서 조회합니다. 할인과 배송 정보는 수시로 바뀔 수 있어 자동으로 넣지 않습니다. 실제 사용하지 않은 상품을 체험한 것처럼 표현하지 않도록 정보형 문장만 생성합니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

## 자동 발행 이력과 오류 알림

`.env`에 다음 서버 전용 값을 설정합니다. 실제 비밀번호와 토큰은 저장소에 커밋하거나 브라우저 코드에 넣지 않습니다.

```dotenv
DATABASE_URL=postgresql://사용자:비밀번호@DB주소:5432/데이터베이스
AUTOMATION_API_TOKEN=충분히-긴-무작위-토큰
DB_MAX_RETRIES=3
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

서비스 시작 시 `automation_runs`, `blog_posts` 테이블과 조회용 인덱스를 자동 생성합니다. `platform`은 `toss`, `coupang`, `threads`를 지원합니다. PostgreSQL 계정에는 해당 데이터베이스의 테이블·인덱스 생성 및 읽기/쓰기 권한이 필요합니다.

모든 자동화 API 요청에는 아래 헤더가 필요합니다.

```text
Authorization: Bearer <AUTOMATION_API_TOKEN>
Content-Type: application/json
```

작업 시작 또는 단계 변경 기록:

```http
POST /api/automation/runs

{
  "run_id": "선택 사항 UUID; 재시도할 때 같은 값 사용",
  "job_name": "coupang-daily-3",
  "platform": "coupang",
  "status": "STARTED",
  "step": "상품 후보 조회",
  "retry_count": 0,
  "context": {}
}
```

상품 및 발행 결과 기록:

```http
POST /api/automation/posts

{
  "platform": "coupang",
  "product_id": "상품 고유 ID",
  "product_name": "상품명",
  "normal_price": 14900,
  "sale_price": 3640,
  "conditional_price": 1270,
  "price_condition": "와우쿠폰 적용 시",
  "affiliate_url": "https://...",
  "naver_category": "개이득 쿠팡쇼핑",
  "naver_post_url": "https://blog.naver.com/...",
  "status": "PUBLISHED",
  "metadata": {}
}
```

중복 확인은 `GET /api/automation/posts/check?platform=coupang&product_id=...`, 최근 실행 조회는 `GET /api/automation/runs/recent?limit=20`을 사용합니다. 같은 `platform + product_id`는 새 행을 계속 만들지 않고 갱신하므로 재시도 중 중복 발행을 막을 수 있습니다.

오류 상태(`FAILED`, `AUTH_REQUIRED`, `PRICE_MISMATCH`, `IMAGE_FAILED`, `EDITOR_FAILED`, `PUBLISH_UNKNOWN`)는 DB에 저장한 뒤 텔레그램으로 알립니다. `PUBLISHED`도 게시물 URL과 함께 완료 알림을 보냅니다. 텔레그램 전송 실패가 DB 기록을 취소하지는 않습니다.

환경값을 넣은 뒤 배포 및 DB 연결 상태까지 한 번에 확인하려면 관리자 PowerShell에서 실행합니다.

```powershell
cd C:\Users\Administrator\code\naverblog-auto
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
```

## 네이버 스마트에디터 안전 게이트

자동 발행 기능을 연결하기 전에 반드시 다음 사전 검증을 통과해야 합니다. 이 명령은 **새 네이버 글쓰기 탭만** 열고, 제목과 본문에 임의의 테스트 문구를 키보드 방식으로 입력한 뒤 DOM 반영을 확인하고 삭제·원복합니다. 상품 선택, 제휴 링크 발급, 이미지 업로드, 임시저장, 발행은 수행하지 않습니다.

```powershell
cd C:\Users\Administrator\code\naverblog-auto
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m automation.preflight_cli
```

처음에는 `.env`에 `AUTOMATION_HEADLESS=false`를 유지합니다. 전용 `data\browser-profile`에 로그인 세션이 없으면 브라우저에서 사용자가 직접 로그인한 뒤 창을 닫고 명령을 다시 실행합니다. 프로그램은 아이디·비밀번호를 읽거나 기록하지 않습니다. 이미 사용 중인 개인 브라우저 세션을 사용하려면 사용자가 Chrome의 DevTools 원격 디버깅을 직접 시작한 뒤 `AUTOMATION_CDP_URL`만 설정할 수 있습니다.

성공 시 JSON의 `ok`가 `true`이고, 로컬 API 및 `data\automation_history.csv`에 통과 이력이 기록됩니다. 실패 시 `EDITOR_FAILED`로 기록되고 텔레그램 오류 알림에는 상품명(없는 경우 `-`), 실패 단계, 재시도 횟수, 필요한 조치가 포함됩니다.

> 사전 검증이 실패하거나 제목·본문이 완전히 빈 상태로 원복되지 않으면, 어떤 자동 발행 작업도 활성화하지 마세요.

## 현재 안전 구현 범위

이 패치에는 토스·쿠팡·Threads의 본문 템플릿 및 필수 고지 검증, CSV 이력의 민감정보 가림, 그리고 네이버 편집기 사전 검증만 포함합니다. 실제 제휴 사이트의 상품 선택·링크 발급·게시 버튼 선택자는 현행 로그인된 화면에서 사전 검증을 통과한 뒤 별도 보정해야 합니다. 화면 구조가 바뀌거나 이미지·가격·링크·카테고리 검증이 하나라도 실패하면 `PUBLISH` 단계로 넘어가지 않도록 설계해야 합니다.
