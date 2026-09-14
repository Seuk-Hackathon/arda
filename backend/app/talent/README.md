# talent/ · 사용자·계정 컨텍스트

> ADR-0035 4개 컨텍스트 중 하나 · 신원 축.
> 자연 허브: **User** (담당자 · 어드민 · 면접관 · 지원자 계정).

## 여기 있는 것

인증 · 계정 관리 · 지원자 로그인.

| 파일 | 무엇 |
|---|---|
| `api/auth.py` | 담당자·어드민·면접관 로그인 (username/password → JWT) |
| `api/users.py` | 사용자 CRUD · 권한 · 목록 조회 |
| `api/applicant_auth.py` | 지원자 로그인 (이메일 + 생년월일 8자리 · ADR-0033) |

## 여기 없는 것

- **지원서 자체** → `application/`
- **면접관 배정** (누구를 배정) → `interview/api/assignments.py`
- **회사 정보** → `hiring/`
- **면접관 가용 시간** → `interview/api/availability.py`

## 핵심 규칙

**두 개의 로그인 경로**:
- **담당자·어드민·면접관** (`api/auth.py`) — username/password + JWT. 권한 `admin` · `member`.
- **지원자** (`api/applicant_auth.py`) — 이메일 + 생년월일 (지원 시 등록한 값). ADR-0033.
두 흐름은 **JWT 발급 규격이 다름** — 지원자는 `sub=application_id`, 담당자는 `sub=user_id`.

**권한 검사**: 각 라우터의 `Depends(get_current_user)` + `require_admin` / `require_member` 데코레이터. 지원자 라우터는 `Depends(get_current_applicant)` 사용 (다른 데코레이터).

**면접관도 User 하나** — 별도 테이블 아님. `User.role` 이 `member` 인 사람이 면접관 배정 대상. 회사원 vs 외부 면접관 구분 없음 (ADR-0017).

## 포트/어댑터

**출력 포트** (`app/ports/output/talent_repository.py`):
- `TalentRepository.get_user(id)`
- `TalentRepository.find_by_username(username)`
- `TalentRepository.list_users_by_role(role)`

**어댑터** (`app/adapter/outbound/pg/talent_pg_repository.py`):
- `PgTalentRepository` (SQLAlchemy 구현)

## 흔한 경계 위반 (안 하기)

- ❌ `talent/` 안에서 `Application` · `InterviewSession` 참조 (역방향)
- ❌ 비밀번호 평문 저장 (`bcrypt` 해시만)
- ❌ 지원자 로그인 · 담당자 로그인의 JWT 를 서로 통과 (`sub` 구조가 다름)

## 종단 검증

- `test_pipeline_e2e.py::TestAppBoots::test_health_open_and_api_guarded` — 인증 없는 요청 401 반환
- `test_talent_repository.py` — Repository 포트 계약 검증
- `test_api_auth.py` — 로그인 · 토큰 · 만료 검증
