# 공개 네이버 초안 입력 확장 프로그램 설계

## 목표와 범위

확장 프로그램은 공개 사이트 `https://blogauto.hongzi.us/`에서 생성한 초안을, **확장 프로그램을 스스로 설치한 사용자**의 네이버 글쓰기 화면에 입력하는 보조 기능이다. 지원 범위는 제목·본문·원본 대표 이미지의 입력 시도와 결과 확인이며, 네이버의 게시·저장·예약·공개 상태 변경 버튼은 호출하거나 조작하지 않는다. 사용자는 최종 결과를 검토하고 직접 발행한다.

## 권한 모델

Manifest V3 확장 프로그램은 다음의 최소 권한을 사용한다.

| 영역 | 권한·대상 | 목적 |
|---|---|---|
| 확장 내부 상태 | `storage` | 10분 동안만 초안 데이터를 보관하고 네이버 입력 뒤 폐기 |
| 공개 도우미 | `https://blogauto.hongzi.us/*` 콘텐츠 스크립트 | 공개 사이트가 DOM `postMessage`로 전송한 초안을 확장 내부로 전달 |
| 네이버 에디터 | `https://blog.naver.com/*`, `https://m.blog.naver.com/*` 콘텐츠 스크립트 | 제목·본문 입력 대상 및 이미지 업로드 입력 요소 탐색 |
| 이미지 전달 | `https://blogauto.hongzi.us/*` host permission | 공개 도우미가 제공한 프록시 이미지 URL만 확장 서비스 워커가 내려받음 |

이 설계는 공개 웹페이지가 확장 프로그램에 직접 메시지를 보낼 수 있도록 허용 목록을 선언하거나, 동일한 호스트에서만 동작하는 콘텐츠 스크립트와 `window.postMessage()` 브리지를 사용하는 Chrome 공식 모델에 따른다. 외부 확장 ID를 웹페이지에 하드코딩하지 않아도 되며, 설치하지 않은 방문자에게는 아무 동작도 하지 않는다. [1] [2]

## 초안 전달과 안전장치

공개 도우미 페이지는 제목, 본문, 태그, 원본 이미지 프록시 URL, 생성 시각을 JSON 구조로 브리지에 전송한다. 브리지는 페이지의 origin을 엄격히 검사하고, 서비스 워커는 문자열 길이·HTTPS·허용 호스트·10분 만료 시간을 검증한 후 `chrome.storage.session`에 저장한다. 네이버 콘텐츠 스크립트는 구조 점검용 테스트 입력과 삭제·원복을 수행한 뒤 실제 값을 입력하고 DOM 값을 재확인한다. 제목 또는 본문 대상이 발견되지 않거나 원복 검증에 실패하면 입력을 멈추고 페이지 위에 실패 사유를 표시한다.

이미지는 `input[type=file]` 기반의 첨부 요소가 준비된 경우에만 `DataTransfer`로 전달한다. 이미지 입력 요소를 찾지 못하면 텍스트 입력 성공과 별개로 이미지 실패를 분명히 표기하고 사용자에게 기존의 이미지 저장·수동 첨부 흐름을 안내한다. 초안은 성공·실패 뒤 서비스 워커에서 폐기하며, 확장 프로그램은 어떤 경우에도 게시·저장·예약·공개 버튼을 탐색하거나 클릭하지 않는다.

## 공개 배포

Chrome Web Store 공개 배포는 확장 프로그램 ZIP 업로드, 스토어 설명·개인정보·배포 정보 작성, 검토 제출 및 승인 후 게시가 필요하다. 이 절차는 소유자 계정에서 수행되어야 하므로 본 구축에서는 로컬 테스트용 unpacked 확장 프로그램과 스토어 업로드용 ZIP을 준비한다. 실제 업로드·검토 제출은 사용자 확인 후에만 진행한다. [3]

## 참고 문헌

[1] [Chrome Developers — Content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)

[2] [Chrome Developers — externally_connectable](https://developer.chrome.com/docs/extensions/reference/manifest/externally-connectable)

[3] [Chrome Developers — Publish in the Chrome Web Store](https://developer.chrome.com/docs/webstore/publish)
