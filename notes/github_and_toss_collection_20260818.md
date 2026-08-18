# GitHub 업로드 및 토스 초기 수집 기록

현재 프로젝트는 공개 GitHub 저장소 [behong/naverblog-auto](https://github.com/behong/naverblog-auto)에 업로드됐다. 공개 전 `.env`, 모든 `.env.*`, 브라우저 프로필, 과거 백업, 테스트 캐시, 진단 로그, 참고 화면 자료, 과거 버전별 배포 ZIP을 제외했다. 공개 저장소에는 최신 `naver-draft-assistant-beta.zip`만 포함한다.

초기 커밋은 `Initial public release: Toss shopping Naver draft assistant`이며, 토스 목록 수집 모듈과 내부 인증 API를 더한 최신 공개 커밋은 `f12bce8`이다. 공개 저장소 화면에서 최신 커밋과 `toss_collector.py`, `scripts/collect_toss_products.py`, 관련 테스트가 확인됐다.

토스 공식 Sharelink Open API 문서 기준으로 `GET /openapi/products/best-selling`과 `GET /openapi/products/today-deals`을 사용한다. 목록의 `productUrl`은 추적되지 않는 일반 링크이므로 게시에는 사용하지 않는다. 추후 `POST /openapi/links`와 `sharelink:write` 권한으로 발급한 `shortUrl` 또는 `originUrl`만 게시 후보 링크로 사용한다.

운영 컨테이너에서 2026-08-18 KST에 `best-selling` 첫 페이지 30건을 실제 수집해 PostgreSQL에 저장했다. 이 단계는 링크를 발급하거나 글을 저장·발행하지 않는다.

내부 인증 API 기반은 다음과 같다.

| API | 인증 | 기능 |
|---|---|---|
| `GET /api/automation/toss/products?source=best-selling&limit=30` | Bearer 자동화 토큰 | 저장된 수집 목록 조회 |
| `POST /api/automation/toss/collect` | Bearer 자동화 토큰 | 수동 새로 수집 |

다음 단계는 내부 전용 화면에서 저장된 후보를 검토하고, 사용자가 선택한 상품에 대해서만 쉐어링크를 발급해 저장하는 것이다.


## 내부 수집 화면 배포 검증

`https://blogauto.hongzi.us/internal-toss.html`이 정상적으로 배포됐다. 화면은 접근 토큰 입력 전에는 상품 후보를 비워 둔다. 토큰 없이 `GET /api/automation/toss/products?source=best-selling&limit=1`를 호출한 결과는 HTTP 401 및 `{"ok": false, "error": "unauthorized"}`였으며, 상품 데이터는 반환되지 않았다.

내부 페이지에는 `noindex,nofollow,noarchive` 메타 태그를 적용하고 `robots.txt`에도 `/internal-toss.html`을 제외했다. 페이지는 정적 파일이므로 주소 자체는 알 수 있지만, 저장 목록 조회와 수동 수집은 Bearer 자동화 토큰을 가진 요청만 수행할 수 있다.


## 웹 기반 관리자 최초 설정 전환

사용자에게 보이지 않는 PowerShell 입력 방식은 중단했다. 공개 배포된 `https://blogauto.hongzi.us/admin/setup` 페이지에서 기존 내부 접근 토큰으로 최초 인증한 뒤 새 관리자 비밀번호를 설정하도록 전환했다. 페이지에는 기존 토큰·새 비밀번호·확인 비밀번호가 모두 password input으로만 표시된다.

최초 설정 API `POST /api/admin/setup`는 기존 Bearer 자동화 토큰이 없을 때 HTTP 401 및 `{"ok": false, "error": "unauthorized"}`를 반환한다. 따라서 공개 URL을 아는 것만으로는 관리자 비밀번호를 설정하거나 변경할 수 없다. 비밀번호 원문은 저장하지 않고 PBKDF2 해시만 `admin_settings` 테이블에 저장하며, 변경 시 기존 관리자 세션을 모두 무효화한다.
