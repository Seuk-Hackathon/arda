import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getApplicantToken, setApplicantToken } from '../api/client'
import { applicantAuth } from '../api/endpoints'
import type { ApplicantMe, MyApplication, MyTokenLink } from '../api/types'
import BrandMark from '../components/BrandMark'
import styles from './MyApplications.module.css'

/* 지원자 본인 화면 (ADR-0033) — 이메일 + 생년월일 8자리로 들어온다.

   **담당자 로그인(`/login`)과 완전히 다른 화면이다.** 같은 자리에 두면 지원자가
   담당자 계정으로 들어가려다 막히고, 담당자는 반대로 헤맨다. 실제로 그렇게 한 번
   막혔다 — 그래서 주소도 화면도 나눠 뒀다.

   토큰도 자리를 나눈다(`arda-applicant-token`). 한 브라우저에서 담당자로 보다가
   여기에 들어와도 서로를 덮어쓰지 않는다.

   ## 2026-09-11 — 웹 배치로

   그 전에는 폰 폭(480px) 하나로 짜서 1280px 모니터에서 가운데 띠만 있었다.
   지금은 **왼쪽에 내가 낸 지원, 오른쪽에 그 지원의 여정**이다.

   폭은 1040px 에서 자른다. 화면이 넓다고 글까지 넓힐 이유는 없다 — 지원자가
   가진 것은 지원 몇 건에 할 일 셋뿐이라, 1340px 로 펴면 한 줄에 400px 가까이
   빈 채로 버튼만 저 멀리 오른쪽에 선다. 상단 바만 끝까지 간다. */

/* ── 로컬에서 화면만 보려고 열 때 ─────────────────

   `/my?preview` 로 열면 **서버를 안 부르고** 아래 표본으로 그린다.

   이 화면은 진짜 지원자 계정(이메일 + 생년월일)이 있어야 열리는데, 그 계정은
   지원 폼에 생년월일이 생긴 2026-09-08 이후에 낸 지원서만 가진다 — 화면 하나
   고치려고 매번 지원서를 새로 내야 했다.

   **`import.meta.env.DEV` 안에 있다.** vite dev 에서만 참이고 빌드 번들에서는
   이 상수가 죽은 코드로 제거되므로 배포에 새어 나갈 수 없다 — AuthContext 의
   DEV_USER 와 같은 장치이고 같은 이유다("화면 하나 보려고 매번 로그인하지 않게").

   **표본인 것을 화면에 적는다** — 값이 어디서 왔는지는 화면이 말해야 한다. */

function inDays(n: number): string {
  return new Date(Date.now() + n * 86_400_000).toISOString()
}

const PREVIEW: ApplicantMe | null = import.meta.env.DEV
  ? {
      email: 'preview@example.invalid',
      name: '최민서',
      applications: [
        {
          id: 1,
          posting_title: '프론트엔드 개발자 (React)',
          stage_label: '면접 전형 진행 중',
          applied_at: '2026-09-09T02:00:00Z',
          aptitudes: [{ token: 'p-a1', status: 'pending', expires_at: inDays(2) }],
          schedules: [{ token: 'p-s1', status: 'proposed', expires_at: inDays(6) }],
          interviews: [],
        },
        {
          id: 2,
          posting_title: '백엔드 개발자 (Python·FastAPI)',
          stage_label: '서류 검토 중',
          applied_at: '2026-09-05T02:00:00Z',
          aptitudes: [{ token: 'p-a2', status: 'done', expires_at: null }],
          schedules: [],
          interviews: [],
        },
        {
          id: 3,
          posting_title: '데이터 엔지니어',
          stage_label: '최종 합격',
          applied_at: '2026-08-21T02:00:00Z',
          aptitudes: [{ token: 'p-a3', status: 'done', expires_at: null }],
          schedules: [{ token: 'p-s3', status: 'confirmed', expires_at: null }],
          interviews: [{ token: 'p-i3', status: 'done', expires_at: null }],
        },
        {
          id: 4,
          posting_title: 'QA 엔지니어',
          stage_label: '전형 종료',
          applied_at: '2026-07-30T02:00:00Z',
          aptitudes: [{ token: 'p-a4', status: 'done', expires_at: null }],
          schedules: [],
          interviews: [],
        },
      ],
    }
  : null

function previewWanted(): boolean {
  if (PREVIEW === null) return false
  try {
    return new URLSearchParams(window.location.search).has('preview')
  } catch {
    return false
  }
}

type View =
  | { kind: 'login' }
  | { kind: 'loading' }
  | { kind: 'ready'; data: ApplicantMe }

/* ── 지원자가 보는 전형 ─────────────────────────────

   담당자 화면(ApplicantPanel)의 진행 바와 같은 칸이다. 마지막에 `결과` 를 더
   두는 이유: **아직 안 온 단계도 이름은 보여야 기다릴 수 있다.**

   ## 서버가 단계 키를 안 준다

   `/applicant/me` 는 `stage_label` 이라는 화면용 글자만 내린다 —
   "면접 전형 진행 중" 같은 것이고 `interview` 같은 키는 없다. 담당자 쪽
   (`/applications`)은 `current_stage` 를 그대로 주는데 지원자 쪽만
   STAGE_LABEL_APPLICANT_KR(app/shared/labels.py) 을 한 번 거치면서 키가
   사라진다. 그렇게 만든 이유는
   `rejected` 하나다 — 담당자가 통보하기 전에 화면이 "불합격"을 앞질러
   말하지 않게 하려던 것이고, 그 판단은 지금도 맞다.

   그래서 당분간 **글자를 거꾸로 맞춰 본다.** 다섯 문구가 서로 안 겹쳐서 오늘은
   정확하다. 못 맞추면 **여정을 아예 안 그린다** — 첫 칸으로 되돌리거나 아무 데나
   찍지 않는다. 단계 글자는 머리의 알약에 그대로 나오므로 화면이 말을 잃지는
   않는다. 백엔드에 `stage` 한 줄을 요청해 두었다. */

type LegKey = 'applied' | 'screening' | 'interview' | 'result'

const LEGS: { key: LegKey; name: string }[] = [
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

type Ending = 'none' | 'accepted' | 'rejected'
interface Where {
  idx: number
  ending: Ending
}

function whereIs(stageLabel: string): Where | null {
  const stage = STAGE_BY_LABEL[stageLabel]
  if (stage === undefined) return null
  if (stage === 'accepted') return { idx: 3, ending: 'accepted' }
  if (stage === 'rejected') return { idx: 3, ending: 'rejected' }
  return { idx: LEGS.findIndex((l) => l.key === stage), ending: 'none' }
}

function isOver(stageLabel: string): boolean {
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

interface Due {
  text: string
  near: boolean
  days: number
}

function dueOf(iso: string | null): Due | null {
  const d = daysLeft(iso)
  if (d === null) return null
  if (d <= 0) return { text: '오늘까지', near: true, days: 0 }
  /* 사흘이 경계다 — 그 아래부터 색을 준다. 늘 노랗게 두면 색이 뜻을 잃는다 */
  return { text: `${d}일 남음`, near: d <= 3, days: d }
}

/* 받침이 있으면 "을", 없으면 "를". `인적성 검사` 는 받침이 없어 "를" 다 —
   하나로 박아 두면 "검사을 해 주세요" 가 된다 */
function objectParticle(word: string): string {
  const last = word.trim().slice(-1)
  const code = last.charCodeAt(0)
  if (code < 0xac00 || code > 0xd7a3) return "을"
  return (code - 0xac00) % 28 === 0 ? "를" : "을"
}

function shortDate(iso: string): string {
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

type Tone = 'todo' | 'done' | 'none'

interface Task {
  leg: LegKey
  name: string
  state: string
  tone: Tone
  due: Due | null
  action: { text: string; href: string; strong: boolean } | null
}

const APTITUDE = '인적성 검사'

function aptitudeTask(app: MyApplication): Task {
  const first: MyTokenLink | undefined = app.aptitudes[0]
  const base = { leg: 'screening' as const, name: APTITUDE, due: null, action: null }
  if (first === undefined) return { ...base, state: '아직 없습니다', tone: 'none' }
  /* 낸 것(done)도 내려온다 — 끝난 것을 안 보여 주면 "완료"와 "아직 안 잡힘"이
     같아진다. 낸 뒤에는 다시 들어갈 곳이 없어 문을 그리지 않는다. */
  if (first.status === 'done') return { ...base, state: '제출했습니다', tone: 'done' }
  return {
    ...base,
    state: '아직 안 하셨습니다 · 먼저 해 주세요',
    tone: 'todo',
    due: dueOf(first.expires_at),
    action: { text: '검사하기', href: `/aptitude/${first.token}`, strong: true },
  }
}

function scheduleTask(app: MyApplication, aptitudeOpen: boolean): Task {
  const first: MyTokenLink | undefined = app.schedules[0]
  const base = { leg: 'interview' as const, name: '면접 시간' }
  if (first === undefined) {
    return { ...base, state: '아직 없습니다', tone: 'none', due: null, action: null }
  }
  /* 일정만 confirmed 도 내려온다 — 확정 뒤에도 "언제로 잡혔는지" 다시 볼 일이
     있어서다(면접·인적성과 다른 점). 그래서 여기만 끝난 뒤에도 문이 있다. */
  if (first.status === 'confirmed') {
    return {
      ...base,
      state: '확정됐습니다',
      tone: 'done',
      due: null,
      action: { text: '보기', href: `/schedule/${first.token}`, strong: false },
    }
  }
  return {
    ...base,
    state: aptitudeOpen ? '후보 중에서 고르시면 됩니다' : '후보 중에서 골라 주세요',
    tone: aptitudeOpen ? 'none' : 'todo',
    due: dueOf(first.expires_at),
    action: { text: '시간 고르기', href: `/schedule/${first.token}`, strong: !aptitudeOpen },
  }
}

function interviewTask(app: MyApplication, aptitudeOpen: boolean): Task {
  const base = { leg: 'interview' as const, name: 'AI 면접' }
  if (app.interviews.length === 0) {
    /* **AI 면접은 자동으로 안 생긴다.** `InterviewSession` 은 담당자가 발급할
       때만 만들어져(app/application/screening.py 의 _after_pass 에 없다)
       이 상태가 길다. 빈 줄로
       두지 않고 언제 생기는지를 적는다. */
    return {
      ...base,
      state: '아직 없습니다 · 면접 시간이 잡히면 안내드립니다',
      tone: 'none',
      due: null,
      action: null,
    }
  }
  /* **끝나지 않은 것을 먼저 본다.** 면접을 다시 낼 수 있어(재발급) 끝난 것과
     새 것이 같이 올 수 있는데, 그럴 때 지원자가 알아야 하는 것은 아직 할 일이
     남은 쪽이다. */
  const next = app.interviews.find((iv) => iv.status !== 'done')
  if (next === undefined) {
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
      href: `/interview-ai/${next.token}`,
      strong: !aptitudeOpen,
    },
  }
}

function tasksOf(app: MyApplication): Task[] {
  const apt = aptitudeTask(app)
  const aptitudeOpen = apt.tone === 'todo'
  return [apt, scheduleTask(app, aptitudeOpen), interviewTask(app, aptitudeOpen)]
}

function todoCount(app: MyApplication): number {
  return tasksOf(app).filter((t) => t.tone === 'todo').length
}

/* 지금 제일 급한 일 하나. **여러 지원을 가로질러 고른다** — 이 화면을 여는
   이유가 "뭘 해야 하지" 하나라 답도 하나여야 한다. 인적성이 먼저고,
   그 다음은 마감이 가까운 순이다(마감 없는 것은 맨 뒤). */
function topTask(me: ApplicantMe): { app: MyApplication; task: Task } | null {
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

export default function MyApplications() {
  const [view, setView] = useState<View>(() => {
    if (previewWanted() && PREVIEW !== null) return { kind: 'ready', data: PREVIEW }
    return getApplicantToken() ? { kind: 'loading' } : { kind: 'login' }
  })
  const [email, setEmail] = useState('')
  const [birth, setBirth] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /* 지금 펼친 지원. null 이면 첫 번째 — 목록이 오기 전에는 고를 수가 없다 */
  const [openId, setOpenId] = useState<number | null>(null)
  const [menu, setMenu] = useState(false)
  /* 설정 — 계정 메뉴에서 연다. 갈 곳이 여기 하나라 라우트를 따로 파지 않고
     이 화면 위에 덮는다(담당자 쪽 Settings 는 사이드바가 있어 라우트다) */
  const [settings, setSettings] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setView({ kind: 'ready', data: await applicantAuth.me(signal) })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      /* 토큰이 죽었으면 클라이언트가 이미 지웠다. 로그인 화면으로 되돌린다. */
      setView({ kind: 'login' })
    }
  }, [])

  useEffect(() => {
    if (previewWanted()) return
    if (!getApplicantToken()) return
    const ac = new AbortController()
    void load(ac.signal)
    return () => ac.abort()
  }, [load])

  /* 설정 — Esc 로 닫는다. 바깥 클릭은 스크림이 받는다 */
  useEffect(() => {
    if (!settings) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSettings(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [settings])

  /* 계정 메뉴 — 바깥을 누르거나 Esc 면 닫는다 */
  useEffect(() => {
    if (!menu) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menu])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setPending(true)
    setError(null)
    try {
      const res = await applicantAuth.login(email.trim(), birth.trim())
      setApplicantToken(res.access_token)
      setView({ kind: 'loading' })
      await load()
    } catch (err) {
      /* **사유를 지어내지 않는다.** 서버가 없는 이메일과 틀린 생년월일을 구별해
         주지 않는 것이 설계다 — 화면에서 "그런 이메일이 없습니다"라고 쓰면
         서버가 안 하기로 한 일을 화면이 대신 해 버린다. */
      setError(err instanceof ApiError ? err.message : '잠시 후 다시 시도해 주세요')
    } finally {
      setPending(false)
    }
  }

  function logout() {
    setApplicantToken(null)
    setEmail('')
    setBirth('')
    setMenu(false)
    setSettings(false)
    setView({ kind: 'login' })
  }

  /* 로그인·로딩은 **좁다.** 폼까지 1040px 로 펴면 칸 하나가 화면을 가로지른다 */
  if (view.kind !== 'ready') {
    return (
      <div className={styles.page}>
        <main className={styles.column}>
          <h1 className={styles.logo}>
            <BrandMark size={26} halo className={styles.logoMark} />
            Arda
          </h1>

          {view.kind === 'login' && (
            <form className={styles.card} onSubmit={submit}>
              <h2 className={styles.cardTitle}>지원 현황 조회</h2>
              <p className={styles.help}>
                지원할 때 쓰신 이메일과 생년월일로 확인하실 수 있습니다.
              </p>

              <label className={styles.label} htmlFor="ap-email">이메일</label>
              <input
                id="ap-email"
                className={styles.input}
                type="email"
                autoComplete="email"
                inputMode="email"
                placeholder="지원할 때 쓰신 이메일"
                value={email}
                disabled={pending}
                onChange={(e) => setEmail(e.target.value)}
              />

              <label className={styles.label} htmlFor="ap-birth">생년월일</label>
              <input
                id="ap-birth"
                className={styles.input}
                /* 숫자 8자리다. 폰에서 숫자 자판이 바로 뜨게 inputMode 를 준다 —
                   type=number 는 앞자리 0 이 사라져서 못 쓴다. */
                inputMode="numeric"
                maxLength={8}
                placeholder="19980412"
                value={birth}
                disabled={pending}
                onChange={(e) => setBirth(e.target.value.replace(/\D/g, ''))}
              />

              {error && <p className={styles.error} role="alert">{error}</p>}

              <button
                type="submit"
                className="btn btn-primary"
                disabled={pending || !email.trim() || birth.length !== 8}
              >
                {pending ? '확인 중…' : '조회하기'}
              </button>

              {/* 담당자가 잘못 들어왔을 때 나갈 길. 반대로 지원자가 담당자
                  로그인으로 흘러가지 않도록 문구를 분명히 둔다. */}
              <p className={styles.foot}>
                채용 담당자이신가요? <a className={styles.link} href="/login">담당자 로그인</a>
              </p>
            </form>
          )}

          {view.kind === 'loading' && (
            <div className={styles.card} aria-busy="true">
              <div className={styles.skeleton} style={{ width: '50%' }} />
              <div className={styles.skeleton} />
            </div>
          )}
        </main>
      </div>
    )
  }

  const me = view.data
  const apps = me.applications
  const live = apps.filter((a) => !isOver(a.stage_label))
  const over = apps.filter((a) => isOver(a.stage_label))
  const open = apps.find((a) => a.id === openId) ?? apps[0]
  const top = topTask(me)
  const initial = me.name ? me.name.charAt(0) : '?'

  return (
    <div className={styles.page}>
      {/* 상단 바만 화면 끝까지 간다 */}
      <header className={styles.topbar}>
        <h1 className={styles.logo}>
          <BrandMark size={24} halo className={styles.logoMark} />
          Arda
        </h1>
        {/* 담당자 화면에는 왼쪽 메뉴가 있어 지금 어디인지 알 수 있는데
            지원자 화면에는 메뉴가 없다 — 이 띠가 유일한 단서다 */}
        <span className={styles.divider} aria-hidden="true" />
        <span className={styles.where}>지원 현황</span>
        <span className={styles.gap} />

        <div className={styles.account} ref={menuRef}>
          <button
            type="button"
            className={`${styles.trigger} ${menu ? styles.triggerOn : ''}`}
            aria-haspopup="menu"
            aria-expanded={menu}
            aria-label={`${me.name || '내'} 계정 메뉴`}
            onClick={() => setMenu((v) => !v)}
          >
            <span className={styles.avatar} aria-hidden="true">{initial}</span>
            <span className={styles.tname}>{me.name || '지원자'}</span>
            <svg className={styles.caret} viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          {menu && (
            <div className={styles.menu} role="menu">
              <div className={styles.mWho}>
                <span className={styles.avatar} aria-hidden="true">{initial}</span>
                <span className={styles.mText}>
                  <span className={styles.mName}>{me.name || '지원자'}</span>
                  <span className={styles.mMail}>{me.email}</span>
                </span>
              </div>
              <div className={styles.sep} role="separator" />
              {/* 갈 곳이 설정 하나다 — 로그아웃은 그 안에 있다(2026-09-14).
                  메뉴와 설정 양쪽에 두면 같은 동작이 두 자리에 생긴다 */}
              <button
                type="button"
                role="menuitem"
                className={styles.mItem}
                onClick={() => {
                  setMenu(false)
                  setSettings(true)
                }}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 008 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H2a2 2 0 110-4h.09A1.65 1.65 0 004.6 8a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V2a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H22a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
                </svg>
                설정
              </button>
            </div>
          )}
        </div>
      </header>

      <main className={styles.wide}>
        {previewWanted() && (
          <p className={styles.previewNote}>
            표본 데이터입니다 — 서버를 부르지 않았습니다 (<code>?preview</code>)
          </p>
        )}

        {apps.length === 0 ? (
          <div className={styles.card}>
            <p className={styles.emptyBig}>접수된 지원이 없습니다</p>
            {/* **「그런 이메일이 없습니다」라고 쓰지 않는다** — 서버가 없는 이메일과
                틀린 생년월일을 구별해 주지 않는 것이 설계다(ADR-0033) */}
            <p className={styles.help}>지원할 때 쓰신 이메일이 맞는지 확인해 주세요.</p>
          </div>
        ) : (
          <>
            {/* 지금 할 일 하나. 없으면 조용한 띠로 바뀐다 — **대부분의 날이
                그렇다.** 빈 자리로 두면 매일 새로고침하게 된다 */}
            {top !== null && top.task.action !== null ? (
              <div className={styles.bar}>
                <span className={styles.barText}>
                  <span className={styles.barKicker}>
                    {top.task.name === APTITUDE ? '먼저 하실 일' : '지금 하실 일'}
                  </span>
                  <p className={styles.barTitle}>
                    {top.task.name}{objectParticle(top.task.name)} 해 주세요
                  </p>
                  <p className={styles.barWhere}>{top.app.posting_title || '공고'}</p>
                </span>
                {top.task.due !== null && (
                  <span className={`${styles.due} ${top.task.due.near ? styles.dueNear : ''}`}>
                    {top.task.due.text}
                  </span>
                )}
                <a className={styles.cta} href={top.task.action.href}>
                  {top.task.action.text}
                </a>
              </div>
            ) : (
              <div className={`${styles.bar} ${styles.barCalm}`}>
                <span className={styles.barText}>
                  <span className={styles.barKicker}>지금은</span>
                  <p className={styles.barTitle}>기다리시면 됩니다</p>
                  <p className={styles.barWhere}>
                    내신 것은 모두 접수됐습니다. 다음 안내는 <strong>메일로</strong> 드립니다.
                  </p>
                </span>
              </div>
            )}

            <div className={styles.cols}>
              {/* **여기는 공고 목록이 아니라 내가 낸 것들이다** — 서버가 내 이메일로
                  낸 지원만 골라 내린다(app/talent/api/applicant_auth.py).
                  공고 제목만 늘어놓으면
                  채용 사이트처럼 읽혀서, 줄마다 낸 날짜를 붙이고 진행 중·끝난 것으로
                  묶는다 */}
              <div className={styles.rail}>
                <p className={styles.railHead}>내가 낸 지원 {apps.length}건</p>

                {live.length > 0 && (
                  <>
                    <p className={styles.railGroup}>진행 중 {live.length}건</p>
                    <div className={styles.list}>
                      {live.map((a) => (
                        <RailItem key={a.id} app={a} on={a.id === open.id} onPick={setOpenId} />
                      ))}
                    </div>
                  </>
                )}

                {over.length > 0 && (
                  <>
                    <p className={styles.railGroup}>끝난 것 {over.length}건</p>
                    <div className={styles.list}>
                      {over.map((a) => (
                        <RailItem
                          key={a.id}
                          app={a}
                          on={a.id === open.id}
                          onPick={setOpenId}
                          quiet
                        />
                      ))}
                    </div>
                  </>
                )}
              </div>

              <Journey app={open} />
            </div>
          </>
        )}
      </main>

      {settings && (
        <SettingsOverlay me={me} onClose={() => setSettings(false)} onLogout={logout} />
      )}
    </div>
  )
}

/* ── 설정 ────────────────────────────────────────────

   **비밀번호 변경은 아직 눌리지 않는다.** 지원자에게는 비밀번호가 없다 —
   로그인이 이메일 + 생년월일 8자리이고(ADR-0033), `password_hash` 컬럼은
   `users`(담당자) 에만 있다. 백엔드에 요청해 두었고 올라오면 여기 폼을 연다.

   **비활성 버튼을 그냥 두지 않고 이유를 적는다** — 눌리지 않는 것이 고장인지
   아직인지 화면이 말해야 한다.

   덮개로 만든 이유: 지원자 화면에는 메뉴가 없어서 설정으로 갔다가 돌아올 길을
   따로 만들어야 한다. 덮으면 닫기만 하면 제자리다(담당자 쪽 Settings 는
   사이드바가 있어 라우트로 둔다). */
function SettingsOverlay({
  me,
  onClose,
  onLogout,
}: {
  me: ApplicantMe
  onClose: () => void
  onLogout: () => void
}) {
  return (
    <div className={styles.scrim} onClick={onClose} role="presentation">
      <div
        className={styles.sheet}
        role="dialog"
        aria-modal="true"
        aria-label="설정"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.sheetHead}>
          <h2 className={styles.sheetTitle}>설정</h2>
          <span className={styles.gap} />
          <button type="button" className={styles.x} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <div className={styles.sheetBody}>
          <section className={styles.section}>
            <h3 className={styles.sectionName}>내 정보</h3>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="set-name">이름</label>
              <input className={styles.input} id="set-name" value={me.name} readOnly />
            </div>
            <div className={styles.field}>
              {/* 이메일은 로그인 식별자다 — 담당자 설정과 같은 이유로 바꾸는 길을 두지 않는다 */}
              <label className={styles.label} htmlFor="set-mail">이메일</label>
              <input className={styles.input} id="set-mail" value={me.email} readOnly />
              <p className={styles.hint}>지원할 때 쓰신 주소입니다. 바꿀 수 없습니다.</p>
            </div>
          </section>

          <section className={styles.section}>
            <h3 className={styles.sectionName}>비밀번호</h3>
            <p className={styles.hint}>
              지금은 <strong>생년월일 8자리</strong>로 로그인합니다. 비밀번호를 정하는 기능은
              준비 중입니다.
            </p>
            <button type="button" className={styles.wideBtn} disabled>
              비밀번호 변경
            </button>
          </section>

          <section className={styles.section}>
            <button type="button" className={`${styles.wideBtn} ${styles.leave}`} onClick={onLogout}>
              로그아웃
            </button>
          </section>
        </div>
      </div>
    </div>
  )
}

function RailItem({
  app,
  on,
  onPick,
  quiet = false,
}: {
  app: MyApplication
  on: boolean
  onPick: (id: number) => void
  quiet?: boolean
}) {
  const n = todoCount(app)
  const w = whereIs(app.stage_label)
  const ramp = [styles.miniS1, styles.miniS2, styles.miniS3, styles.miniS3]

  return (
    <button
      type="button"
      className={`${styles.item} ${on ? styles.itemOn : ''} ${quiet ? styles.itemQuiet : ''}`}
      aria-current={on ? 'true' : undefined}
      onClick={() => onPick(app.id)}
    >
      <span className={styles.itemTop}>
        <span className={styles.itemName}>{app.posting_title || '공고'}</span>
        {n > 0 && <span className={styles.count}>{n}</span>}
      </span>
      <span className={styles.itemStage}>{app.stage_label}</span>
      {/* 이 줄 하나가 "내가 낸 것"과 "떠 있는 공고"를 가른다 */}
      <span className={styles.itemWhen}>{shortDate(app.applied_at)} 지원</span>

      {w !== null && (
        <span className={styles.mini} aria-hidden="true">
          {LEGS.map((leg, i) => {
            let mark = ''
            if (i < w.idx) mark = ramp[i]
            else if (i === w.idx) {
              mark =
                w.ending === 'accepted'
                  ? styles.miniWin
                  : w.ending === 'rejected'
                    ? styles.miniStop
                    : styles.miniCur
            }
            return <i key={leg.key} className={`${styles.miniStep} ${mark}`} />
          })}
        </span>
      )}
    </button>
  )
}

function Journey({ app }: { app: MyApplication }) {
  const w = whereIs(app.stage_label)
  const tasks = tasksOf(app)

  return (
    <div className={styles.detail}>
      <div className={styles.detailHead}>
        <h2 className={styles.detailTitle}>{app.posting_title || '공고'}</h2>
        <span className={styles.gap} />
        <span
          className={`${styles.pill} ${
            w?.ending === 'accepted'
              ? styles.pillWin
              : w?.ending === 'rejected'
                ? styles.pillEnd
                : ''
          }`}
        >
          {app.stage_label}
        </span>
        <span className={styles.when}>{shortDate(app.applied_at)} 지원</span>
      </div>

      {/* 문구를 못 맞추면 여정을 안 그린다 — 틀린 여정은 없는 것보다 나쁘다.
          단계 글자는 위 알약에 이미 있으므로 화면이 말을 잃지는 않는다 */}
      {w === null ? (
        <div className={styles.journey}>
          {tasks.map((t) => (
            <TaskRow key={t.name} task={t} />
          ))}
        </div>
      ) : (
        <div className={styles.journey}>
          {LEGS.map((leg, i) => {
            const here = i === w.idx
            const past = i < w.idx
            const mine = tasks.filter((t) => t.leg === leg.key)
            const tone = here
              ? w.ending === 'accepted'
                ? styles.legWin
                : w.ending === 'rejected'
                  ? styles.legStop
                  : styles.legHere
              : past
                ? styles.legPast
                : ''

            return (
              <div key={leg.key} className={`${styles.leg} ${tone}`}>
                <span className={styles.legRail} aria-hidden="true">
                  <span className={styles.node}>
                    {past || (here && w.ending !== 'none') ? '✓' : ''}
                  </span>
                  {i < LEGS.length - 1 && <span className={styles.wire} />}
                </span>
                <span className={styles.legBody}>
                  <span className={styles.legRow}>
                    <span className={styles.legName}>{legName(leg, here, w)}</span>
                    <span className={styles.legNote}>
                      {legNote(leg.key, i, here, w, mine.filter((t) => t.tone === 'todo').length, app)}
                    </span>
                  </span>
                  {mine.map((t) => (
                    <TaskRow key={t.name} task={t} />
                  ))}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function legName(leg: { key: LegKey; name: string }, here: boolean, w: Where): string {
  if (leg.key !== 'result' || !here) return leg.name
  if (w.ending === 'accepted') return '최종 합격'
  if (w.ending === 'rejected') return '전형 종료'
  return leg.name
}

function legNote(
  key: LegKey,
  i: number,
  here: boolean,
  w: Where,
  todo: number,
  app: MyApplication,
): string {
  if (key === 'applied') return shortDate(app.applied_at)
  if (key === 'result') {
    if (w.ending === 'accepted') return '담당자가 따로 연락드립니다'
    if (w.ending === 'rejected') return '이 공고의 전형이 끝났습니다'
    return '면접이 끝나면 메일로 알려 드립니다'
  }
  if (here) return todo > 0 ? `지금 여기 · 하실 일 ${todo}개` : '지금 여기'
  if (i < w.idx) return '통과'
  /* 아직 안 온 단계. **이름만 두지 않고 어떻게 오는지 적는다** — 안 적으면
     매일 이 화면을 새로고침하게 된다 */
  return key === 'interview' ? '서류를 통과하면 안내드립니다' : ''
}

function TaskRow({ task }: { task: Task }) {
  const stateTone =
    task.tone === 'todo' ? styles.stateTodo : task.tone === 'done' ? styles.stateDone : ''

  const body = (
    <>
      <span className={styles.taskName}>{task.name}</span>
      <span className={`${styles.taskState} ${stateTone}`}>{task.state}</span>
      <span className={`${styles.taskDue} ${task.due?.near ? styles.dueNear : ''}`}>
        {task.due?.text ?? ''}
      </span>
      {task.action !== null ? (
        <span className={`${styles.go} ${task.action.strong ? styles.goStrong : ''}`}>
          {task.action.text}
        </span>
      ) : (
        <span className={styles.tick}>{task.tone === 'done' ? '✓' : '—'}</span>
      )}
    </>
  )

  /* 갈 곳이 있으면 **줄 전체가 문**이다 — 안쪽 것은 버튼처럼 보이는 표시일
     뿐이라 링크 안에 링크가 생기지 않는다 */
  return task.action !== null ? (
    <a
      className={`${styles.task} ${task.tone === 'todo' ? styles.taskLive : ''}`}
      href={task.action.href}
    >
      {body}
    </a>
  ) : (
    <div className={styles.task}>{body}</div>
  )
}
