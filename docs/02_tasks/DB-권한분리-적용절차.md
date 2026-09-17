# 운영 DB 권한 분리 적용 절차 (이슈 #7 · ADR-0028 1.6단계)

> 작성: woojeongalex (백엔드) · 2026-09-17 · **적용: 2026-09-22(월) 09:00~09:30 KST, suvisdev 와 함께**
> 합의: suvisdev 회신(09-17) — 이행 계정 A안 · ADR-0028 문구 좁히기 · DB 비밀번호 재발급 같이 · **학원 온프레미스 제외**
> 대상: AWS 운영(`api.seuk.suvisdev.cloud`)만

## 무엇이 바뀌나 — 쉬운 말로

지금 앱은 DB 에 **관리자(`postgres`)** 로 붙는다. 그래서 지워지면 안 되는 제출물 지문 장부(`document_anchors`)의 잠금을 **앱이 스스로 풀 수 있다.**

적용 뒤에는 이렇게 나뉜다.

| 누가 | 계정 | 할 수 있는 것 |
|---|---|---|
| 앱(api 컨테이너) | **`arda_app`** | 일반 표 읽기·쓰기 · **장부는 넣기·읽기만** · 표 만들기 불가 · 이행 기록 변경 불가 |
| 배포 스크립트의 이행 단계 | `postgres` | 표 만들기·고치기 · 권한 맞추기 |

**이 작업이 막는 것과 못 막는 것**
- 막는다: 웹에서 뚫린 앱 코드가 장부를 고치거나 지우는 것
- 못 막는다: **서버 셸을 가진 사람**. root 는 `docker exec db psql` 로 비밀번호 없이 관리자가 된다. 그 부분은 ADR-0028 1.7단계(잠금 해제 감시·기록)의 몫이다

## 기존 절차(#7·ADR-0028)에서 바뀐 점

| 기존 | 바뀐 것 | 이유 |
|---|---|---|
| `ARDA_APP_DB_ROLE` 넣고 `alembic upgrade head` → `0007` 이 장부 권한 회수 | **`scripts/apply_db_privileges.py` 를 배포마다 실행** | 운영 DB 는 이미 `0007` 을 지나서 다시 안 돈다. 권한 회수가 조용히 안 된다 |
| `GRANT ... ON ALL TABLES` 한 번 | 위 스크립트가 **`ALTER DEFAULT PRIVILEGES`** 도 건다 | 한 번만 주면 이후 이행이 만든 새 표를 앱이 못 읽는다 |
| 이행도 `DATABASE_URL`(앱) 로 | **`MIGRATION_DATABASE_URL`**(관리자) 이 있으면 이행이 그것을 쓴다 (`alembic/env.py`) | 앱 계정은 표를 만들 권한이 없어 다음 스키마 변경 때 자동 배포가 멈춘다 |

## 로컬 검증 결과 (2026-09-17)

**순정 postgres 16 (`arda_split`)** — 이행만으로 만든 DB

| 확인 | 결과 |
|---|---|
| 롤 미설정 → 스크립트 건너뜀 | exit 0 |
| 적용 · 한 번 더 적용 | exit 0 · 같은 결과 |
| 관리자 연결 없이 앱 롤로만 실행 | exit 1 (안내 문구) |
| 없는 롤 | exit 1 |
| 분리 뒤 **앱 롤만으로** `alembic upgrade head` | **실패** — `permission denied for schema public` (A안이 필요한 이유) |
| 분리 뒤 `MIGRATION_DATABASE_URL` 로 이행 (0025→0026) | 성공 · 새 표 소유자 `postgres` · **앱이 바로 읽고 씀**(기본 권한) |

**앱 롤로 기능 흐름 18/18**
- 되는 것: 접수(지원서·이력·메일 기록·**장부 INSERT**) · 로그인 · 상세 조회 · 단계 변경 · 면접 세션 발급 · 무결성 확인 · 장부 사슬 온전 · `file_blobs` 쓰기
- 거부되는 것: 장부 UPDATE·DELETE·TRUNCATE · **장부 잠금 끄기**(`must be owner`) · 표 만들기 · 이행 기록 변경
- 분리 뒤 관리자가 만든 새 표를 앱이 쓴다(시퀀스 포함)

**pgvector 이미지(pg17)** — 운영과 같은 확장 구성
- 앱 롤로 **기동(lifespan) 통과**, `/health` 200
- 확장 켜기 경고 없음 · 임베딩 표 읽기·쓰기 권한 있음
- 스키마 비교 스크립트 "같다"

---

## 당일 절차

### 0. 사전 (09-19 리허설 뒤 ~ 09-21)

- [x] 이 PR 머지 확인 — `scripts/apply_db_privileges.py` · `alembic/env.py` 가 운영 이미지에 들어가 있어야 한다(#295, 09-17 머지). 롤이 비어 있으면 둘 다 **아무 동작도 바꾸지 않는다**
- [x] **배포 서비스 계정 = `ubuntu`** (09-17 suvisdev 확인, `systemctl cat arda-deploy.service`) → **`.env.migrate` 는 `ubuntu:ubuntu 600`**. `root:root` 로 두면 배포 스크립트가 못 읽어 멈춘다. `ubuntu` 는 docker 그룹이라 이미 root 와 같은 권한이다 — 막을 대상이 아니다
- [ ] **CI 에 "모델과 이행 결과 비교" 스텝** — 적용 뒤에는 이행 누락이 곧 api 기동 실패다. 09-17 PR 로 추가(스크립트는 #292, CI 한 줄은 별도 PR)
- [ ] 비밀번호 관리자에 새 항목 두 개: `arda-db-admin`(postgres) · `arda-db-app`(arda_app)
  - **팀 공용 도구는 정해진 적이 없다**(09-17 확인). 각자 쓰는 비밀번호 관리자에 둔다 — ADR-0028 에 따라 관리자 비밀번호는 **woojeongalex(평시)·suvisdev(응급)** 두 사람만
  - **전달은 채팅·md·커밋·이슈로 하지 않는다.** 당일 2단계에서 suvisdev 가 생성해 넣을 때 **화면을 같이 보며** 각자 자기 관리자에 저장한다

### 1. 백업 (09:00)

```bash
ssh arda
~/backup-arda-db.sh        # 수동 1회. 로그 끝에 "완료" 확인
```

### 2. 관리자 비밀번호 재발급 + 앱 롤 생성

```bash
cd ~/arda
docker compose -p arda -f infra/docker-compose.prod.yml exec db psql -U postgres -d arda
```

```sql
-- 비밀번호는 비밀번호 관리자에서 생성해 붙여 넣는다. 여기·채팅·커밋에 남기지 않는다
ALTER ROLE postgres PASSWORD '<새 관리자 비밀번호>';
CREATE ROLE arda_app LOGIN PASSWORD '<새 앱 비밀번호>';
\q
```

- `~/arda/.env` 의 `DB_PASSWORD` 도 새 관리자 비밀번호로 바꾼다. db 컨테이너는 **처음 만들 때만** 이 값을 읽으므로 지금 당장 영향은 없지만, 어긋나 두면 나중에 헷갈린다

### 3. 이행용 파일

```bash
install -m 600 -o ubuntu -g ubuntu /dev/null ~/arda/.env.migrate   # 배포 서비스 계정 = ubuntu (09-17 확인)
nano ~/arda/.env.migrate
# 한 줄: MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<새 관리자 비밀번호>@db:5432/arda
```

### 4. 앱 연결 바꾸기

`~/arda/backend/.env`

```bash
DATABASE_URL=postgresql+psycopg://arda_app:<새 앱 비밀번호>@db:5432/arda
ARDA_APP_DB_ROLE=arda_app
```

**관리자 비밀번호는 이 파일에 두지 않는다.**

### 5. 권한 맞추기 → 앱 재기동

```bash
cd ~/arda
set -a; . ./.env.migrate; set +a
docker compose -p arda -f infra/docker-compose.prod.yml run --rm -e MIGRATION_DATABASE_URL api \
  /app/.venv/bin/python scripts/apply_db_privileges.py
# → "arda_app 권한 확인 — ..." 와 exit 0 이어야 한다
docker compose -p arda -f infra/docker-compose.prod.yml up -d --force-recreate api
unset MIGRATION_DATABASE_URL
```

### 6. 확인 (5분)

```bash
# 앱이 정말 arda_app 으로 붙었나
docker compose -p arda -f infra/docker-compose.prod.yml exec db psql -U postgres -d arda -tAc \
  "select usename, count(*) from pg_stat_activity where datname='arda' group by 1"
# api 컨테이너 환경에 관리자 비밀번호가 없나 (아무것도 안 나와야 한다)
docker compose -p arda -f infra/docker-compose.prod.yml exec api env | grep -i -E "MIGRATION|postgres:" || echo OK
curl -sf https://api.seuk.suvisdev.cloud/health
```

- [ ] 웹에서: 로그인 → 지원자 목록 → 상세(이력서 열기) → 단계 변경 1건 → 메일 기록 생성
- [ ] 공개 지원 폼으로 시험 접수 1건 → 상세 화면의 **무결성 "확인됨"**
- [ ] 아르 채팅 한 번(요약·검색)

### 7. 배포 스크립트 반영 (suvisdev)

아래 diff 를 서버 `~/deploy-arda.sh` 와 저장소 `infra/deploy-arda.sh` 에 같은 커밋으로 넣는다. **넣은 뒤 문서 한 줄짜리 PR 을 머지해 자동 배포가 이 경로를 한 번 타는지 본다.**

```diff
 # 스키마 이행 (기동 전에) — 컬럼 추가/변경은 create_all 이 못 함. #17
+# 앱 롤 분리(#7, 2026-09-22) 뒤: 이행과 권한 맞추기는 관리자 연결로 한다.
+# 값은 파일에서 읽어 이 셸에만 두고, compose 에는 이름만 넘긴다(-e 이름) — 명령줄(ps)에
+# 비밀번호가 찍히지 않는다. 파일이 없으면 지금과 똑같이 동작한다.
+MIGRATE_FILE=/home/ubuntu/arda/.env.migrate
+MIGRATE_ARGS=()
+if [ -e "$MIGRATE_FILE" ]; then
+  if [ ! -r "$MIGRATE_FILE" ]; then
+    echo "$(date -Is) deploy FAIL: $MIGRATE_FILE 를 읽을 수 없다 (소유자·권한 확인)" >> "$LOG"
+    exit 1
+  fi
+  MIGRATION_DATABASE_URL="$(grep -E '^MIGRATION_DATABASE_URL=' "$MIGRATE_FILE" | head -1 | cut -d= -f2-)"
+  export MIGRATION_DATABASE_URL
+  MIGRATE_ARGS=(-e MIGRATION_DATABASE_URL)
+fi
 echo "$(date -Is) alembic upgrade..." >> "$LOG"
-docker compose -p arda -f infra/docker-compose.prod.yml run --rm api /app/.venv/bin/alembic upgrade head >> "$LOG" 2>&1
+docker compose -p arda -f infra/docker-compose.prod.yml run --rm "${MIGRATE_ARGS[@]}" api /app/.venv/bin/alembic upgrade head >> "$LOG" 2>&1
+echo "$(date -Is) db privileges..." >> "$LOG"
+docker compose -p arda -f infra/docker-compose.prod.yml run --rm "${MIGRATE_ARGS[@]}" api /app/.venv/bin/python scripts/apply_db_privileges.py >> "$LOG" 2>&1
+unset MIGRATION_DATABASE_URL
```

- 파일을 `source` 로 실행하지 않고 `grep` 으로 한 줄만 꺼낸다 — 파일에 무엇이 들어 있든 셸 명령으로 실행되지 않는다
- 권한 스크립트는 롤이 비어 있으면 바로 0 으로 끝나므로, **이 diff 를 09-22 전에 넣어도 무해하다**

---

## 되돌리기 (5분)

문제가 나면 **앱 연결만 관리자로 되돌린다.** 권한·롤은 남겨 둬도 해가 없다.

```bash
# ~/arda/backend/.env
DATABASE_URL=postgresql+psycopg://postgres:<관리자 비밀번호>@db:5432/arda
ARDA_APP_DB_ROLE=
```

```bash
docker compose -p arda -f infra/docker-compose.prod.yml up -d --force-recreate api
```

- 되돌린 뒤 원인을 채널에 남긴다
- `.env.migrate` 는 그대로 둬도 된다(이행이 관리자로 도는 것은 같다)

## 알아 둘 것

- **분리 뒤에는 앱이 표를 만들지 못한다.** 모델에 표를 추가하고 이행을 빠뜨리면, 지금까지는 기동 때 `create_all` 이 조용히 만들어 줬지만 이제는 **기동이 실패**한다. 그래서 `scripts/check_schema_drift.py`(CI 한 줄 대기)가 더 중요해진다
- `scripts/create_admin.py` 처럼 `create_all` 을 부르는 스크립트는 서버에서 돌릴 때 관리자 연결로 돌린다
- 백업(`backup-arda-db.sh`)은 db 컨테이너 안에서 `POSTGRES_USER` 로 뜨므로 영향이 없다
- 학원 온프레미스는 심사(09-20~10-17)가 끝난 뒤 같은 절차로 별건 진행한다
