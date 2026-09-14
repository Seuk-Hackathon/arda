import { useEffect, useState } from 'react'
import { summary as summaryApi } from '../api/endpoints'
import type { SummaryApplicant, SummaryPosting } from '../api/types'
import styles from './Summary.module.css'

/* 종합 평가 (2026-09-14) — 공고별 지원자 · 서류 + 면접 자동 점수 · 등급 · 요약.

   담당자가 "이 공고의 지원자들이 어느 수준이고 누가 강한가" 를 **한 눈에** 본다.
   지원자 상세는 카드 클릭 시 /applicants 로 이동 (기존 패널 재사용).

   왜 새 페이지가 필요했나:
     `/applicants` 는 지원자 목록 + 우측 패널이라 지원자 하나씩만 상세하게 본다.
     "공고별 전체 지원자를 서로 비교하며 훑는" 경험이 없었다. 자동 심사 · 면접
     점수 · 요약을 각각 다른 화면에 흩뿌려 놔 총평이 안 잡혔다. 이 페이지가
     그 총평을 조립한다.
*/

export default function Summary() {
  const [state, setState] = useState<
    | { kind: 'loading' }
    | { kind: 'ready'; data: SummaryPosting[] }
    | { kind: 'error'; message: string }
  >({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    summaryApi
      .list(controller.signal)
      .then((data) => setState({ kind: 'ready', data }))
      .catch((err) => {
        if (err?.name === 'AbortError') return
        setState({ kind: 'error', message: err?.message ?? '불러오지 못했습니다' })
      })
    return () => controller.abort()
  }, [])

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <h1 className={styles.title}>종합 평가</h1>
        <p className={styles.sub}>공고별 지원자 · 서류 + 면접 자동 점수 · 종합 등급 · 요약</p>
      </header>

      {state.kind === 'loading' && <p className={styles.state}>불러오는 중…</p>}
      {state.kind === 'error' && <p className={styles.err}>{state.message}</p>}
      {state.kind === 'ready' && (
        state.data.length === 0 ? (
          <p className={styles.state}>아직 공고가 없습니다.</p>
        ) : (
          <div className={styles.postings}>
            {state.data.map((p) => (
              <PostingBlock key={p.id} posting={p} />
            ))}
          </div>
        )
      )}
    </div>
  )
}

function PostingBlock({ posting }: { posting: SummaryPosting }) {
  const [expanded, setExpanded] = useState(true)

  const graded = posting.applicants.filter((a) => a.final_score !== null).length
  const avgFinal = posting.applicants.length
    ? posting.applicants
        .filter((a) => a.final_score !== null)
        .reduce((s, a) => s + (a.final_score ?? 0), 0) /
      (posting.applicants.filter((a) => a.final_score !== null).length || 1)
    : 0

  return (
    <section className={styles.posting}>
      <header className={styles.postingHead}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          <span className={styles.chev} aria-hidden>{expanded ? '▾' : '▸'}</span>
          <span className={styles.postingTitle}>{posting.title}</span>
          <span className={`${styles.badge} ${styles[`status_${posting.status}`] ?? ''}`}>
            {posting.status === 'open' ? '진행 중' : posting.status === 'closed' ? '마감' : posting.status}
          </span>
        </button>
        <div className={styles.stats}>
          <span>지원자 <strong>{posting.applicant_count}</strong>명</span>
          <span>평가 완료 <strong>{graded}</strong>명</span>
          {graded > 0 && (
            <span>평균 종합 <strong>{avgFinal.toFixed(1)}</strong>점</span>
          )}
        </div>
      </header>

      {expanded && (
        posting.applicants.length === 0 ? (
          <p className={styles.state}>지원자가 아직 없습니다.</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>지원자</th>
                <th className={styles.numCol}>서류</th>
                <th className={styles.numCol}>면접</th>
                <th className={styles.numCol}>종합</th>
                <th className={styles.numCol}>등급</th>
                <th>단계</th>
                <th>요약 · 강점 · 우려</th>
              </tr>
            </thead>
            <tbody>
              {posting.applicants.map((a) => (
                <ApplicantRow key={a.id} applicant={a} />
              ))}
            </tbody>
          </table>
        )
      )}
    </section>
  )
}

function ApplicantRow({ applicant: a }: { applicant: SummaryApplicant }) {
  const stageLabel: Record<string, string> = {
    applied: '접수', screening: '서류', interview: '면접',
    accepted: '합격', rejected: '불합격',
  }
  return (
    <tr className={styles.row}>
      <td>
        <div className={styles.name}>{a.name}</div>
        <div className={styles.email}>{a.email}</div>
      </td>
      <td className={styles.num}>
        {a.doc_score !== null ? (
          <span className={a.doc_decision === 'pass' ? styles.ok : a.doc_decision === 'reject' ? styles.bad : ''}>
            {a.doc_score}
          </span>
        ) : <span className={styles.dim}>—</span>}
      </td>
      <td className={styles.num}>
        {a.interview_ai_score !== null ? a.interview_ai_score : <span className={styles.dim}>—</span>}
      </td>
      <td className={styles.num}>
        {a.final_score !== null ? <strong>{a.final_score.toFixed(1)}</strong> : <span className={styles.dim}>—</span>}
      </td>
      <td className={styles.num}>
        {a.grade ? (
          <span className={`${styles.grade} ${styles[`grade_${a.grade}`] ?? ''}`}>{a.grade}</span>
        ) : <span className={styles.dim}>—</span>}
      </td>
      <td>{stageLabel[a.current_stage] ?? a.current_stage}</td>
      <td>
        <details className={styles.details}>
          <summary className={styles.detailsSummary}>
            {a.ai_summary ? a.ai_summary.slice(0, 80) + (a.ai_summary.length > 80 ? '…' : '') : '요약 없음'}
          </summary>
          <div className={styles.detailsBody}>
            {a.ai_summary && (
              <p className={styles.summary}>{a.ai_summary}</p>
            )}
            {a.strengths.length > 0 && (
              <div className={styles.pointsWrap}>
                <span className={styles.pointsLabel}>강점</span>
                <ul className={styles.points}>
                  {a.strengths.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}
            {a.concerns.length > 0 && (
              <div className={styles.pointsWrap}>
                <span className={`${styles.pointsLabel} ${styles.concernLabel}`}>우려</span>
                <ul className={styles.points}>
                  {a.concerns.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}
          </div>
        </details>
      </td>
    </tr>
  )
}
