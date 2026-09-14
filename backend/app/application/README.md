# application/ · 지원 관리 컨텍스트

> ADR-0035 4개 컨텍스트 중 **★★★ 가장 큰 스타** · 워크플로 축.
> 자연 허브: **Application** (지원서 · 단계 이력 · 채점 · 결정 · 메일).

## 여기 있는 것

지원서 접수 → 심사 → 단계 이동 → 결정까지의 흐름 전부.

| 파일 | 무엇 |
|---|---|
| `api/applications.py` | 지원자 목록·상세 CRUD (담당자 도메인) |
| `api/public.py` | 공개 지원서 폼 + 확인 메일 (지원자 도메인) |
| `api/portal.py` | 지원자 로그인 후 마이페이지 |
| `api/aptitude.py` | 인적성 검사 |
| `api/emails.py` | 담당자 메일 미리보기·발송 |
| `api/evaluations.py` | 담당자 별점·코멘트 |
| `api/notes.py` | 내부 메모 |
| `api/search.py` | 통합 검색 (이름·이메일·semantic) |
| `api/agent.py` | 아르 채팅 엔드포인트 |
| `screening.py` | 서류 채점 · 최종 점수 · 등급 계산 (순수 함수) |
| `stages.py` · `stage_service.py` | 단계 정의 · 단계 전이 규칙 |
| `agent_service.py` | 아르 백엔드 오케스트레이션 |
| `aptitude_questions.py` | 인적성 문항 데이터 |

## 여기 없는 것 (다른 컨텍스트)

- **채용공고 관리** → `hiring/`
- **면접 세션 · 질문 · 채점** → `interview/`
- **사용자 계정 · 인증** → `talent/`

## 핵심 규칙

**단계 전이는 `stage_service.apply_stage_change`** 하나만이 진실. REST · 에이전트 도구 (`change_stage`) 둘 다 이 함수를 통과한다. 이유: 09-07 실측 · 에이전트가 별도 경로로 단계 바꿀 때 메일 큐 발행이 빠져 메일이 안 나가는 사고 있었음 (`app/agent/tools/write.py:change_stage` 참고).

**심사 계산은 `screening.py` 순수 함수** — DB 를 안 만진다. 호출부가 결과를 저장. Hiring 의 가중치(`company_profile.scoring_weights`) 를 인자로 받는다.

**공개 API 는 토큰 인증만** (`api/public.py`) — 로그인 없이 링크로 접근. `Application.public_token` 이 그 자격.

## 포트/어댑터

**출력 포트** (`app/ports/output/application_repository.py`):
- `ApplicationRepository.get(id)`
- `ApplicationRepository.list_by_stage(stage)`

**어댑터** (`app/adapter/outbound/pg/application_pg_repository.py`):
- `PgApplicationRepository` (SQLAlchemy 구현)

## 흔한 경계 위반 (안 하기)

- ❌ `interview/` 안에서 `application/screening.py` 직접 import (역방향 의존)
- ❌ `stage_service` 를 우회하고 `Application.current_stage` 를 직접 SET
- ❌ 심사 계산을 API 라우터 안에서 (테스트 어려움 · `screening.py` 로 뽑기)

## 종단 검증

`backend/tests/test_pipeline_e2e.py::TestStageChangeToMailQueue` 가 REST · 에이전트 두 경로 모두 `email_logs.status=queued` 로 끝나는지 실측.
