# interview/ · 면접 컨텍스트

> ADR-0035 4개 컨텍스트 중 **★★ 두 번째** · 세션 중심.
> 자연 허브: **InterviewSession** (턴 · 질문 프로브 · 답변 · 채점 · 오디오 · 거짓말 분석).

## 여기 있는 것

면접 관리자 배정 · 일정 조율 · 세션 실행 · 채점 · 실시간 소켓.

| 파일 | 무엇 |
|---|---|
| `api/assignments.py` | 면접관 배정 (누구를 · 누가) |
| `api/availability.py` | 면접관 가용 시간 등록·조회 |
| `api/schedules.py` | 후보 시각 제안 → 지원자 선택 |
| `api/interviews.py` | 면접 세션 CRUD · 담당자 시점 (680 줄) |
| `api/interview_rtc.py` | 실시간 소켓 (WebSocket) · 오디오·프레임 수신 |
| `api/scoring.py` | 면접 채점 API |
| `session_service.py` | 세션 생성·상태 전이 |
| `schedule_service.py` | 일정 제안 생성 로직 |
| `scoring.py` | 답변 점수 계산 (LLM 위임 + 룰) |
| `lie_analysis.py` | 거짓말 탐지 서비스 호출 (별도 ai/lie-detection) |
| `pacing.py` | 진행 보조 문구 생성 |

## 여기 없는 것

- **지원 관리 · 심사** → `application/`
- **채용공고** → `hiring/`
- **면접관 계정 자체** → `talent/`
- **거짓말 탐지 모델 · 표정 판정** → `ai/lie-detection/` (별도 서비스)
- **음성 STT** → `ai/lie-detection/` 안 (Whisper)

## 핵심 규칙

**세션 상태 전이는 `session_service`** 하나만이 진실. `pending` → `in_progress` → `done`. 상태 되돌리기 없음 · `done` 은 최종.

**실시간 소켓은 `interview_rtc.py`** — 모듈 레벨 상태(`_ROOMS` dict) 를 들고 있다. 이관 시 실전 확인 필요 (**ADR-0035 후속 1순위**).

**채점은 두 벌**:
- `scoring.py::answers_score` — LLM 이 답변 점수 매김 (Ollama·Anthropic 스위치)
- `lie_analysis.py` — 별도 ViT·음성 분석 서비스 결과 조회
두 결과를 합쳐 `interview_scores` 저장. **합격 판단은 사람 몫** (ADR-0026 결정 4).

**공개 API 는 토큰 인증만** (`api/interviews.py::/public/interview/<token>`) — 지원자 링크 진입점. `InterviewSession.token`.

## 포트/어댑터

**출력 포트** (`app/ports/output/interview_repository.py`):
- `InterviewRepository.get(id)`
- `InterviewRepository.list_finished_by_application(app_id)`

**어댑터** (`app/adapter/outbound/pg/interview_pg_repository.py`):
- `PgInterviewRepository` (SQLAlchemy 구현)

## 흔한 경계 위반 (안 하기)

- ❌ `shared/api/internal.py → interview_rtc.py` **역방향 의존** (현재 4곳 있음 · ADR-0035 후속 1순위 로 정리 예정)
- ❌ `application/` 안에서 `interview/scoring.py` 직접 import (역방향)
- ❌ `interview_rtc.py` 의 `_ROOMS` 를 다른 모듈이 참조

## 종단 검증

- `test_pipeline_e2e.py::TestPortsAndAdapters` — Repository 갈아끼우기 검증
- `test_api_interview_rtc.py` — 소켓 연결·해제·프레임 수신
- `test_pipeline_e2e.py::TestScoringChain` — 서류 → 면접 → 최종 → 등급 계산 순서
