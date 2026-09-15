import { useOutletContext } from 'react-router-dom'
import type { ApplicantMe, MyApplication, MyTokenLink } from '../api/types'

/* 지원자 웹 화면들이 **함께 쓰는 판단**만 모은 곳 (2026-09-15).

   셸(MyShell)과 현황 탭(MyApplications)이 같은 것을 물어보기 때문이다 —
   사이드바의 「인적성 검사 ①」과 현황의 줄이 서로 다른 답을 하면 안 된다.
   전에는 MyApplications.tsx 안에 있었고, 그때는 물어보는 쪽이 하나였다.

   그림은 없다. 여기 있는 것은 전부 순수 함수다. */

/* ── 탭이 셸에게서 받는 것 ───────────────────────────

   앱의 셸이 `me` 와 토큰을 탭에 넘겨주는 것과 같다(applicant_shell.dart 의
   `_body`). 탭은 서버를 다시 부르지 않는다 — 셸이 한 번 받은 것을 나눠 쓴다.

   셸(MyShell.tsx)이 아니라 여기 있는 이유: 컴포넌트만 내보내는 파일이어야
   vite 의 fast refresh 가 산다(oxlint `only-export-components`). */
export interface MyCtx {
  me: ApplicantMe
  /* 지금 보고 있는 지원. 낸 것이 하나도 없으면 null */
  app: MyApplication | null
  preview: boolean
}

export function useMy(): MyCtx {
  return useOutletContext<MyCtx>()
}

/* ── 어느 것을 여는가 ────────────────────────────────

   **앱과 한 글자도 다르면 안 된다** (mobile/lib/models/applicant_me.dart 의
   `pickLink`). 앱에서 홈과 탭이 서로 다른 세션을 골라, 홈은 "제출했어요" 를
   탭은 "기한이 지났습니다" 를 띄운 적이 있다 (2026-09-15 폰 실측).

   웹도 같은 자리에 왔다. 사이드바가 탭을 열고 현황이 줄을 그리는데, 둘이
   다른 세션을 고르면 앱에서 난 것과 똑같은 것이 난다.

   서버는 오래된 것부터 준다(`.order_by(id)` — app/talent/api/
   applicant_auth.py), 그래서 **뒤에서부터** 본다. 끝난 것(`done`)밖에 없으면
   마지막 것 — 그래야 "제출했습니다" 를 그릴 재료가 남는다. */
export function pickLink<T extends MyTokenLink>(links: T[]): T | null {
  if (links.length === 0) return null
  for (let i = links.length - 1; i >= 0; i -= 1) {
    if (links[i].status !== 'done') return links[i]
  }
  return links[links.length - 1]
}

/* ── 지원자가 보는 전형 ─────────────────────────────

   담당자 화면(ApplicantPanel)의 진행 바와 같은 칸이다. 마지막에 `결과` 를 더
   두는 이유: **아직 안 온 단계도 이름은 보여야 기다릴 수 있다.**

   ## 서버가 단계 키를 안 준다

   `/applicant/me` 는 `stage_label` 이라는 화면용 글자만 내린다 —
   "면접 전형 진행 중" 같은 것이고 `interview` 같은 키는 없다. 담당자 쪽
   (`/applications`)은 `current_stage` 를 그대로 주는데 지원자 쪽만
   STAGE_LABEL_APPLICANT_KR(app/shared/labels.py) 을 한 번 거치면서 키가
   사라진다. 그렇게 만든 이유는 `rejected` 하나다 — 담당자가 통보하기 전에
   화면이 "불합격"을 앞질러 말하지 않게 하려던 것이고, 그 판단은 지금도 맞다.

   그래서 당분간 **글자를 거꾸로 맞춰 본다.** 다섯 문구가 서로 안 겹쳐서 오늘은
   정확하다. 못 맞추면 **여정을 아예 안 그린다** — 첫 칸으로 되돌리거나 아무 데나
   찍지 않는다. 단계 글자는 머리의 알약에 그대로 나오므로 화면이 말을 잃지는
   않는다. 백엔드에 `stage` 한 줄을 요청해 두었다. */

export type LegKey = 'applied' | 'screening' | 'interview' | 'result'

export const LEGS: { key: LegKey; name: string }[] = [
  { key: 'applied', name: '접수 완료' },
  { key: 'screening', name: '서류 검토' },
  { key: 'interview', name: '면접 전형' },
  { key: 'result', name: '결과' },
]

/* app/shared/labels.py 의 STAGE_LABEL_APPLICANT_KR 을 뒤집은 것.
   **서버 문구와 한 글자도 다르면 안 된다** */
const STAGE_BY_LABEL: Record<string, string> = {
  '접수 완료': 'applied',
  '서류 검토 중': 'screening',
  '면접 전형 진행 중': 'interview',
  '최종 합격': 'accepted',
  '전형 종료': 'rejected',
}

export type Ending = 'none' | 'accepted' | 'rejected'

export interface Where {
  idx: number
  ending: Ending
}

export function whereIs(stageLabel: string): Where | null {
  const stage = STAGE_BY_LABEL[stageLabel]
  if (stage === undefined) return null
  if (stage === 'accepted') return { idx: 3, ending: 'accepted' }
  if (stage === 'rejected') return { idx: 3, ending: 'rejected' }
  return { idx: LEGS.findIndex((l) => l.key === stage), ending: 'none' }
}

export function isOver(stageLabel: string): boolean {
  const stage = STAGE_BY_LABEL[stageLabel]
  return stage === 'accepted' || stage === 'rejected'
}

/* ── 남은 날 ────────────────────────────────────────

   서버는 인적성·일정·면접에 `expires_at` 을 **셋 다 준다.** 안 쓰면
   「시간 고르기」만 있고 언제까지인지 모르는 화면이 된다. */
function daysLeft(iso: string | null): number | null {
  if (iso === null) return null
  const ms = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(ms)) return null
  return Math.ceil(ms / 86_400_000)
}

export interface Due {
  text: string
  near: boolean
  days: number
}

export function dueOf(iso: string | null): Due | null {
  const d = daysLeft(iso)
  if (d === null) return null
  if (d <= 0) return { text: '오늘까지', near: true, days: 0 }
  /* 사흘이 경계다 — 그 아래부터 색을 준다. 늘 노랗게 두면 색이 뜻을 잃는다 */
  return { text: `${d}일 남음`, near: d <= 3, days: d }
}

/* 받침이 있으면 "을", 없으면 "를". `인적성 검사` 는 받침이 없어 "를" 다 —
   하나로 박아 두면 "검사을 해 주세요" 가 된다 */
export function objectParticle(word: string): string {
  const last = word.trim().slice(-1)
  const code = last.charCodeAt(0)
  if (code < 0xac00 || code > 0xd7a3) return '을'
  return (code - 0xac00) % 28 === 0 ? '를' : '을'
}

/* 같은 이유로 주격도 필요하다 — 앱(ApplicantMissing)이 쓰는 「아직 ○○이
   없습니다」를 웹에서도 그대로 쓴다. `면접 시간 제안` 은 받침이 있어 "이" 다 */
export function subjectParticle(word: string): string {
  const last = word.trim().slice(-1)
  const code = last.charCodeAt(0)
  if (code < 0xac00 || code > 0xd7a3) return '이'
  return (code - 0xac00) % 28 === 0 ? '가' : '이'
}

export function shortDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}.${mm}.${dd}`
}

/* ── 할 일 한 가지 ──────────────────────────────────

   **어느 단계에 매다는지가 이 화면의 판단이다.**
   - 인적성은 **서류**다. 서버가 `applied · screening` 에서만 보내고
     「이후 단계는 목적(서류검토 참고)이 지났다」고 적혀 있다 — 서류 판단 재료다.
   - 면접 시간 · AI 면접은 **면접**이다.

   순서도 화면이 정한다. 서버에는 게이트가 없어서(인적성과 일정 제안이 서류
   통과 순간에 같이 나간다) 둘 다 열려 있는데, 인적성을 늦게 내면 쓸모가 준다.
   그래서 안 끝났으면 그것을 위로 올리고 면접 일은 **흰 버튼을 빼** 한 단계
   조용하게 둔다. **잠그지는 않는다** — 서버가 허용하는 것을 화면이 막으면
   눌러도 안 되는 버튼이 생긴다. */

export type Tone = 'todo' | 'done' | 'none'

/* 사이드바 탭 하나. 이름이 곧 주소다 — `/my/<tab>` */
export type TabKey = 'aptitude' | 'schedule' | 'interview'

export interface Task {
  tab: TabKey
  leg: LegKey
  name: string
  state: string
  tone: Tone
  due: Due | null
  action: { text: string; strong: boolean } | null
}

export const APTITUDE = '인적성 검사'

/* 할 일 줄의 문이 **토큰 주소(`/aptitude/<token>`)가 아니라 탭을 가리킨다**
   (2026-09-15). 같은 화면이지만 탭으로 들어가면 사이드바가 옆에 남아 돌아올
   길이 있다. 토큰 주소는 메일 링크 착지점으로 그대로 살아 있다.

   **주소를 Task 가 들고 있지 않다.** 어느 지원의 할 일인지는 그리는 쪽이 알고
   Task 는 모른다 — 급한 일 띠는 지원을 가로질러 고르기 때문에(topTask), 띠가
   고른 것과 지금 펼친 지원이 다를 수 있다. 그때 `/my/aptitude` 로만 보내면
   **다른 지원의 인적성이 열린다.** 그래서 주소는 늘 지원 번호를 달고 나간다. */
export function tabHref(tab: TabKey, appId: number): string {
  return `/my/${tab}?app=${appId}`
}

function aptitudeTask(app: MyApplication): Task {
  const open = pickLink(app.aptitudes)
  const base = {
    tab: 'aptitude' as const,
    leg: 'screening' as const,
    name: APTITUDE,
    due: null,
    action: null,
  }
  if (open === null) return { ...base, state: '아직 없습니다', tone: 'none' }
  /* 낸 것(done)도 내려온다 — 끝난 것을 안 보여 주면 "완료"와 "아직 안 잡힘"이
     같아진다. 낸 뒤에는 다시 들어갈 곳이 없어 문을 그리지 않는다. */
  if (open.status === 'done') return { ...base, state: '제출했습니다', tone: 'done' }
  return {
    ...base,
    state: '아직 안 하셨습니다 · 먼저 해 주세요',
    tone: 'todo',
    due: dueOf(open.expires_at),
    action: { text: '검사하기', strong: true },
  }
}

function scheduleTask(app: MyApplication, aptitudeOpen: boolean): Task {
  const open = pickLink(app.schedules)
  const base = { tab: 'schedule' as const, leg: 'interview' as const, name: '면접 시간' }
  if (open === null) {
    return { ...base, state: '아직 없습니다', tone: 'none', due: null, action: null }
  }
  /* 일정만 confirmed 도 내려온다 — 확정 뒤에도 "언제로 잡혔는지" 다시 볼 일이
     있어서다(면접·인적성과 다른 점). 그래서 여기만 끝난 뒤에도 문이 있다. */
  if (open.status === 'confirmed') {
    return {
      ...base,
      state: '확정됐습니다',
      tone: 'done',
      due: null,
      action: { text: '보기', strong: false },
    }
  }
  return {
    ...base,
    state: aptitudeOpen ? '후보 중에서 고르시면 됩니다' : '후보 중에서 골라 주세요',
    tone: aptitudeOpen ? 'none' : 'todo',
    due: dueOf(open.expires_at),
    action: { text: '시간 고르기', strong: !aptitudeOpen },
  }
}

function interviewTask(app: MyApplication, aptitudeOpen: boolean): Task {
  const base = { tab: 'interview' as const, leg: 'interview' as const, name: 'AI 면접' }
  const next = pickLink(app.interviews)
  if (next === null) {
    /* **AI 면접은 자동으로 안 생긴다.** `InterviewSession` 은 담당자가 발급할
       때만 만들어져(app/application/screening.py 의 _after_pass 에 없다)
       이 상태가 길다. 빈 줄로 두지 않고 언제 생기는지를 적는다. */
    return {
      ...base,
      state: '아직 없습니다 · 면접 시간이 잡히면 안내드립니다',
      tone: 'none',
      due: null,
      action: null,
    }
  }
  /* 끝나지 않은 것을 먼저 본다(`pickLink`). 면접을 다시 낼 수 있어(재발급)
     끝난 것과 새 것이 같이 올 수 있는데, 그럴 때 지원자가 알아야 하는 것은
     아직 할 일이 남은 쪽이다. 전부 끝났으면 마지막 것이 온다. */
  if (next.status === 'done') {
    return { ...base, state: '완료했습니다', tone: 'done', due: null, action: null }
  }
  const going = next.status === 'in_progress'
  return {
    ...base,
    state: going ? '진행 중입니다' : '아직 시작하지 않았습니다',
    tone: aptitudeOpen ? 'none' : 'todo',
    due: dueOf(next.expires_at),
    action: {
      text: going ? '이어서 보기' : '면접 보기',
      strong: !aptitudeOpen,
    },
  }
}

export function tasksOf(app: MyApplication): Task[] {
  const apt = aptitudeTask(app)
  const aptitudeOpen = apt.tone === 'todo'
  return [apt, scheduleTask(app, aptitudeOpen), interviewTask(app, aptitudeOpen)]
}

export function todoCount(app: MyApplication): number {
  return tasksOf(app).filter((t) => t.tone === 'todo').length
}

/* 지금 제일 급한 일 하나. **여러 지원을 가로질러 고른다** — 이 화면을 여는
   이유가 "뭘 해야 하지" 하나라 답도 하나여야 한다. 인적성이 먼저고,
   그 다음은 마감이 가까운 순이다(마감 없는 것은 맨 뒤). */
export function topTask(me: ApplicantMe): { app: MyApplication; task: Task } | null {
  const open: { app: MyApplication; task: Task }[] = []
  for (const app of me.applications) {
    for (const task of tasksOf(app)) {
      if (task.tone === 'todo' && task.action !== null) open.push({ app, task })
    }
  }
  if (open.length === 0) return null
  const rank = (t: Task) => (t.name === APTITUDE ? 0 : 1)
  const left = (t: Task) => (t.due === null ? Number.MAX_SAFE_INTEGER : t.due.days)
  open.sort((a, b) => rank(a.task) - rank(b.task) || left(a.task) - left(b.task))
  return open[0]
}
