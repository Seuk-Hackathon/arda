import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { InterviewPublic } from '../api/types'
import styles from './InterviewAi.module.css'
import { AI_PHASE_LABEL, useAiInterview } from './useAiInterview'

/* AI 면접 — 지원자 화면 (ADR-0029).

   아르가 묻고, 지원자가 말하면 **버튼 없이** 다음 질문으로 넘어간다.
   서버가 소리를 듣고 말이 끝난 것을 판정한다 (`ai/lie-detection/PROTOCOL.md`).

   **판정을 여기에 띄우지 않는다.** ADR-0029 이고 소연님이 서비스 코드에도
   적어 뒀다 — 판정을 실시간으로 보여 주면 그 자체가 답변을 바꾼다.
   훅도 그 값을 상태로 들고 있지 않아서, 화면이 그리려 해도 그릴 것이 없다.

   ## 앱과 같은 구조 (2026-09-14)

   모바일 앱 `mobile/lib/screens/interview_screen.dart` 의 위젯 트리를 따라간다:

       AppTopBar (제목만)
       └─ ListView
          ├─ 공고명 (small · text-sub)
          ├─ "이름님" (h2 · semibold)
          ├─ 카메라 상자 (3:4 aspect · rounded · LIVE 점 좌상단)
          ├─ 진행 상태 (아이콘 + 문구)
          └─ 질문 · 액션

   두 채널 UX 일치가 목적. 토큰(`tokens.css` ↔ `tokens.dart`) 은 이미 공유했지만
   레이아웃이 달라 지원자가 웹 or 앱에서 다른 화면을 봤다.

   폰 세로가 기본이다. */

export default function InterviewAi() {
  const { token } = useParams<{ token: string }>()
  const { phase, question, seq, error, videoRef, leave } = useAiInterview(token ?? null)
  const [meta, setMeta] = useState<Pick<InterviewPublic, 'applicant_name' | 'posting_title'> | null>(null)

  // 공고명·이름은 REST 로 한 번만 가져온다. 소켓은 질문·상태 스트림 전용.
  useEffect(() => {
    if (!token) return
    let alive = true
    api.get<InterviewPublic>(`/public/interview/${token}`, { auth: false })
      .then((d) => { if (alive) setMeta({ applicant_name: d.applicant_name, posting_title: d.posting_title }) })
      .catch(() => {})
    return () => { alive = false }
  }, [token])

  const showLive = phase === 'listening'

  return (
    <div className={styles.page}>
      {/* 상단 바 — 앱 `AppTopBar` 와 같은 자리. 뒤로가기가 없는 이유는
          면접 중이라 안전한 종료는 아래 "면접 끝내기" 하나뿐이라서다. */}
      <header className={styles.topBar}>
        <h1 className={styles.title}>AI 면접</h1>
      </header>

      <div className={styles.body}>
        {/* 공고명 (앱: text-sub · font-sm) */}
        {meta && <p className={styles.posting}>{meta.posting_title}</p>}

        {/* "이름님" (앱: h2 · semibold · heading shadow) */}
        {meta && <h2 className={styles.name}>{meta.applicant_name}님</h2>}

        {/* 카메라 상자 — 3:4 비율, 모서리 둥글게, LIVE 점 좌상단.
            앱 `_CameraBox` 와 같은 규격. 좌우 뒤집기는 화면에만 (보내는 프레임은 안 뒤집힘). */}
        <div className={styles.cameraBox}>
          <video ref={videoRef} className={styles.cam} autoPlay playsInline muted />
          {showLive && (
            <span className={styles.liveDot} aria-hidden>
              <span className={styles.liveDotPulse} />
              LIVE
            </span>
          )}
        </div>

        {/* 진행 상태 (아이콘 + 문구). 앱 `_Live` 위젯의 상단 상태 표시. */}
        <div className={styles.state} aria-live="polite">
          <span className={`${styles.stateDot} ${phase === 'listening' ? styles.stateDotLive : ''}`} />
          {AI_PHASE_LABEL[phase]}
        </div>

        {/* 질문 자리. 화면의 주인공. */}
        <section className={styles.askWrap}>
          {phase === 'error' ? (
            <p className={styles.error} role="alert">{error}</p>
          ) : phase === 'done' ? (
            <>
              <h3 className={styles.ask}>면접이 끝났습니다</h3>
              <p className={styles.help}>참여해 주셔서 감사합니다.</p>
            </>
          ) : question ? (
            <>
              {seq !== null && <p className={styles.seq}>질문 {seq}</p>}
              <h3 className={styles.ask}>{question}</h3>
              <p className={styles.help}>
                준비되시면 그냥 말씀하시면 됩니다. 버튼을 누르지 않으셔도 됩니다.
              </p>
            </>
          ) : (
            <p className={styles.help}>아르가 첫 질문을 준비하고 있습니다…</p>
          )}
        </section>

        {/* 종료 액션. 앱은 상단 `AppTopBar.showBack` 으로 뒤로가기가 있지만
            AI 면접은 되돌릴 수 없으므로 명시적 "면접 끝내기" 버튼만 둔다. */}
        <footer className={styles.actions}>
          <button type="button" className="btn btn-secondary" onClick={leave}>
            면접 끝내기
          </button>
        </footer>
      </div>
    </div>
  )
}
