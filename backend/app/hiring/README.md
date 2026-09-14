# hiring/ · 채용공고 컨텍스트

> ADR-0035 4개 컨텍스트 중 하나 · 채용 정책 축.
> 자연 허브: **JobPosting** (회사 · 단계 정의 · 심사 규칙 · 가중치).

## 여기 있는 것

채용공고 정의 · 회사 프로파일 · 심사 가중치.

| 파일 | 무엇 |
|---|---|
| `api/postings.py` | 공고 CRUD · 마감일 · 공개 링크 |
| `company.py` | 회사 정보 조회 (`company_profile` 테이블 · 이름·서명 등) |

## 여기 없는 것

- **지원 관리 · 심사 실행** → `application/`
- **면접 세션** → `interview/`
- **사용자 계정** → `talent/`
- **심사 계산 자체** (가중치 → 점수) — hiring 은 **가중치를 제공만**, 실제 계산은 `application/screening.py` 에서

## 핵심 규칙

**심사 가중치는 `company_profile.scoring_weights`** — 회사당 하나. Application 이 채점할 때 이 값을 가져다 씀. hiring 은 값을 **읽기만** 제공.

**회사명은 `hiring/company.py::name_for(db)`** 하나만이 진실. 메일 서명(`app/shared/mail.py::build_signature`) 이 이 함수를 통과. 09-10 이전엔 환경변수 `COMPANY_NAME` 이 primary 였는데 DB 로 이관. 폴백만 env.

**공고 공개 링크는 `posting.public_token`** — 로그인 없이 지원 폼 접근. 마감일 지나면 서버가 접수 거부.

## 포트/어댑터

**출력 포트** (`app/ports/output/hiring_repository.py`):
- `HiringRepository.get_posting(id)`
- `HiringRepository.list_open_postings()`
- `HiringRepository.get_scoring_weights(company_id)`

**어댑터** (`app/adapter/outbound/pg/hiring_pg_repository.py`):
- `PgHiringRepository` (SQLAlchemy 구현)

## 흔한 경계 위반 (안 하기)

- ❌ `hiring/` 안에서 `Application` 을 참조 (역방향 의존 — Application 이 Hiring 을 참조하는 게 정방향)
- ❌ 회사명을 하드코딩 · env 로만 (`company.name_for(db)` 를 통해서만)
- ❌ 심사 가중치를 hiring 에서 직접 계산 · hiring 은 값 제공만

## 종단 검증

- `test_pipeline_e2e.py::TestScoringChain` — 가중치 → 심사 점수 → 등급 계산 흐름
- `test_hiring_repository.py` — Repository 포트 계약 검증
