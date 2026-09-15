import Aptitude from './Aptitude'
import InterviewAi from './InterviewAi'
import Schedule from './Schedule'
import { pickLink, subjectParticle, useMy } from './myApplicant'
import styles from './MyShell.module.css'

/* 셸의 탭 셋 — 인적성 · 면접 시간 · AI 면접 (2026-09-15).

   **화면을 새로 만들지 않는다.** 메일 링크가 착지하는 `/aptitude/:token` 과
   **같은 컴포넌트**를 셸 안에서 열 뿐이다. 두 벌을 만들면 한쪽만 고치는 날이
   온다 — 실제로 앱에서 홈과 탭이 갈려 서로 다른 말을 한 적이 있다.

   셸이 이 셋을 **살려 둔 채 감춘다**(MyShell 의 `.pane`). 라우트로 갈아
   끼우지 않는 이유는 그쪽에 있다.

   달라지는 것은 둘뿐이다:
   - 토큰을 주소(`useParams`)가 아니라 **셸이** 준다 (`token` prop)
   - 자기 배경과 100vh 를 접는다 (`nested` prop) — 셸이 이미 오로라와 높이를
     들고 있어서, 안 접으면 화면 안에 화면이 한 장 더 깔린다

   앱의 셸이 탭에 토큰을 나눠 주는 것과 같은 구조다
   (mobile/lib/screens/applicant_shell.dart 의 `_body`). */

/* 아직 받은 적 없는 탭. **오류처럼 그리지 않는다** — 담당자가 아직 안 보낸
   것이지 지원자가 뭘 잘못한 게 아니다. 앱(ApplicantMissing)과 같은 문구다. */
function Missing({ what }: { what: string }) {
  return (
    <p className={styles.missing}>
      {`아직 ${what}${subjectParticle(what)} 없습니다.\n담당자가 보내면 여기에 나타납니다.`}
    </p>
  )
}

export function MyAptitude() {
  const { app } = useMy()
  const link = app === null ? null : pickLink(app.aptitudes)
  if (link === null) return <Missing what="인적성 검사" />
  /* 토큰이 바뀌면 화면을 새로 만든다 — `key` 가 없으면 지원을 갈아탈 때
     앞 지원의 답이 남는다(컴포넌트 안의 useState 가 살아 있어서) */
  return <Aptitude key={link.token} token={link.token} nested />
}

export function MySchedule() {
  const { app } = useMy()
  const link = app === null ? null : pickLink(app.schedules)
  if (link === null) return <Missing what="면접 시간 제안" />
  return <Schedule key={link.token} token={link.token} nested />
}

export function MyInterview() {
  const { app } = useMy()
  const link = app === null ? null : pickLink(app.interviews)
  if (link === null) return <Missing what="AI 면접" />
  return <InterviewAi key={link.token} token={link.token} nested />
}
