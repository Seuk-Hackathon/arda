import { Link } from 'react-router-dom'
import type { MyApplication } from '../api/types'
import {
  APTITUDE,
  LEGS,
  objectParticle,
  shortDate,
  tabHref,
  tasksOf,
  topTask,
  whereIs,
  type LegKey,
  type Task,
  useMy,
  type Where,
} from './myApplicant'
import styles from './MyApplications.module.css'

/* 지원자 셸의 **현황 탭** (`/my`) — 앱의 홈(applicant_summary_screen.dart) 자리.

   ## 2026-09-15 — 셸이 생기면서 반으로 줄었다

   전에는 이 파일이 화면 전체였다: 로그인 판정 · 상단 바 · 계정 메뉴 · 설정
   덮개 · 왼쪽 지원 목록 · 오른쪽 여정. 사이드바가 생기면서 앞의 넷은
   [MyShell](./MyShell.tsx) 로, 왼쪽 목록은 사이드바의 「보고 있는 지원」으로
   갔다. 여기 남은 것은 **급한 일 띠 하나와 펼친 지원의 여정**이다.

   판단(어느 세션을 여는가 · 어느 단계에 매다는가 · 남은 날)은
   [myApplicant.ts](./myApplicant.ts) 에 있다 — 사이드바의 할 일 개수와 이
   화면의 줄이 같은 답을 해야 해서다.

   **폭은 화면을 쓴다.** 가운데 1040px 섬으로 두면 넓은 모니터에서 양옆이 비어
   화면 한가운데 몰린 것처럼 보인다. 대신 여정에 상한을 둔다 — 넓어지는 것은
   여백이지 줄이 아니다. */

export default function MyApplications() {
  const { me, app, preview } = useMy()
  const top = topTask(me)

  return (
    <main className={styles.wide}>
      {preview && (
        <p className={styles.previewNote}>
          표본 데이터입니다 — 서버를 부르지 않았습니다 (<code>?preview</code>)
        </p>
      )}

      {app === null ? (
        <div className={styles.card}>
          <p className={styles.emptyBig}>접수된 지원이 없습니다</p>
          {/* **「그런 이메일이 없습니다」라고 쓰지 않는다** — 서버가 없는 이메일과
              틀린 생년월일을 구별해 주지 않는 것이 설계다(ADR-0033) */}
          <p className={styles.help}>지원할 때 쓰신 이메일이 맞는지 확인해 주세요.</p>
        </div>
      ) : (
        <>
          {/* 지금 할 일 하나. 없으면 조용한 띠로 바뀐다 — **대부분의 날이
              그렇다.** 빈 자리로 두면 매일 새로고침하게 된다.

              **여러 지원을 가로질러 고른다**(topTask). 그래서 띠가 가리키는 것이
              지금 펼친 지원이 아닐 수 있고, 그때 문은 그쪽 지원으로 데려간다 */}
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
              <Link className={styles.cta} to={tabHref(top.task.tab, top.app.id)}>
                {top.task.action.text}
              </Link>
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

          <Journey app={app} />
        </>
      )}
    </main>
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
            <TaskRow key={t.name} task={t} appId={app.id} />
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
                    <TaskRow key={t.name} task={t} appId={app.id} />
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

function TaskRow({ task, appId }: { task: Task; appId: number }) {
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
     뿐이라 링크 안에 링크가 생기지 않는다.

     문은 **탭**을 가리킨다(`/my/aptitude`) — 토큰 주소로 보내면 사이드바가
     사라져 돌아올 길이 뒤로 가기뿐이 된다 */
  return task.action !== null ? (
    <Link
      className={`${styles.task} ${task.tone === 'todo' ? styles.taskLive : ''}`}
      to={tabHref(task.tab, appId)}
    >
      {body}
    </Link>
  ) : (
    <div className={styles.task}>{body}</div>
  )
}
