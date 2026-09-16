import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { applicantAuth, passwordProblem } from '../api/endpoints'
import styles from './SetPassword.module.css'

/* 지원자 비밀번호 설정 — 메일 링크 착지점 (2026-09-16, 백엔드 PR #268).
   로그인 없음. 주소의 토큰이 곧 인증이다. Aptitude.tsx 와 같은 껍데기 패턴.

   ## 한 경로가 셋을 겸한다

   처음 정하기·잊어버려서 다시 정하기·링크가 죽어 다시 받기가 **모두 이 화면**
   이다(백엔드 결정 4번). 그래서 화면이 "설정"인지 "재설정"인지 묻지 않는다 —
   지원자에게는 어차피 같은 일이다.

   ## 실패 문구를 나누지 않는다

   만료된 링크와 이미 쓴 링크가 **같은 410, 같은 문구**다. 서버가 굳이 하나로
   묶은 것을 화면이 "이미 쓰셨네요"라고 갈라 말하면, 그 링크가 실재했다는 것이
   새어 나간다. 문구는 하나다 — 「만료됐거나 이미 사용한 링크입니다」.

   ## 앱에는 이 화면이 없다

   앱 매니페스트에 딥링크가 없어서(`LAUNCHER` 뿐) 메일 링크는 브라우저로 열린다.
   앱은 **로그인만** 비밀번호를 받는다. 두 벌을 만들 이유가 없다. */

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; email: string }
  /** 만료됐거나 이미 썼다. **둘을 나누지 않는다** */
  | { kind: 'dead' }
  | { kind: 'error'; message: string }

export default function SetPassword() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()

  /* 라우트가 `:token` 을 요구하므로 빈 토큰은 사실상 안 온다. 그래도 갈라
     두되 **렌더 중에 정한다** — 효과 안에서 동기로 setState 하면 렌더가
     한 번 더 돈다(oxlint `set-state-in-effect`). */
  const [state, setState] = useState<LoadState>(() =>
    token ? { kind: 'loading' } : { kind: 'dead' },
  )
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!token) return
      try {
        const got = await applicantAuth.passwordToken(token, signal)
        setState({ kind: 'ready', email: got.email })
      } catch (err) {
        if (signal?.aborted) return
        if (err instanceof ApiError && err.status === 410) {
          setState({ kind: 'dead' })
          return
        }
        setState({
          kind: 'error',
          message: err instanceof ApiError ? err.message : '잠시 후 다시 시도해 주세요',
        })
      }
    },
    [token],
  )

  useEffect(() => {
    const ac = new AbortController()
    void load(ac.signal)
    return () => ac.abort()
  }, [load])

  /* 화면이 먼저 막는다 — 서버도 422 로 막지만, 다 치고 제출한 뒤에 알게 되면
     처음부터 다시 쳐야 한다. **글자 수가 아니라 바이트다**(bcrypt 72). */
  const problem = password === '' ? null : passwordProblem(password)
  const mismatch = again !== '' && password !== again

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    setError(null)
    const bad = passwordProblem(password)
    if (bad) {
      setError(bad)
      return
    }
    if (password !== again) {
      setError('두 번 입력한 비밀번호가 다릅니다')
      return
    }
    setPending(true)
    try {
      await applicantAuth.setPassword(token, password)
      setDone(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) {
        // 보는 중에 죽었다 — 다른 창에서 먼저 썼거나 기한이 지났다
        setState({ kind: 'dead' })
        return
      }
      setError(err instanceof ApiError ? err.message : '잠시 후 다시 시도해 주세요')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <h1 className={styles.logo}>
          아르<span className={styles.seed}>다</span>
        </h1>

        {state.kind === 'loading' && (
          <div className={styles.card}>
            <div className={styles.skeleton} />
            <div className={styles.skeleton} />
          </div>
        )}

        {state.kind === 'dead' && (
          <div className={`${styles.card} ${styles.cardDanger}`}>
            <h2 className={styles.cardTitle}>만료됐거나 이미 사용한 링크입니다</h2>
            <p className={styles.body}>
              비밀번호 설정 링크는 7일 동안만 쓸 수 있고, 한 번 쓰면 사라집니다.
              로그인 화면에서 링크를 다시 받으실 수 있습니다.
            </p>
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.primary}
                onClick={() => navigate('/login?as=applicant')}
              >
                링크 다시 받기
              </button>
            </div>
          </div>
        )}

        {state.kind === 'error' && (
          <div className={`${styles.card} ${styles.cardDanger}`}>
            <h2 className={styles.cardTitle}>불러오지 못했습니다</h2>
            <p className={styles.body}>{state.message}</p>
            <div className={styles.actions}>
              <button type="button" className={styles.primary} onClick={() => void load()}>
                다시 시도
              </button>
            </div>
          </div>
        )}

        {state.kind === 'ready' && done && (
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>비밀번호를 정했습니다</h2>
            <p className={styles.body}>
              이제 <strong>{state.email}</strong> 과(와) 이 비밀번호로 로그인하실 수
              있습니다. 앱에서도 같은 비밀번호를 쓰시면 됩니다.
            </p>
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.primary}
                onClick={() => navigate('/login?as=applicant', { replace: true })}
              >
                로그인하러 가기
              </button>
            </div>
          </div>
        )}

        {state.kind === 'ready' && !done && (
          <form className={styles.card} onSubmit={submit}>
            <h2 className={styles.cardTitle}>비밀번호 정하기</h2>
            <p className={styles.body}>
              <strong>{state.email}</strong> 계정에 쓸 비밀번호입니다.
            </p>

            <label className={styles.field}>
              <span className={styles.label}>비밀번호</span>
              <input
                className={styles.input}
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={pending}
              />
              {/* 규칙을 미리 적는다 — 틀리고 나서 알려 주는 것보다 낫다 */}
              <span className={problem ? styles.hintBad : styles.hint}>
                {problem ?? '8자 이상 64자 이하 (한글은 24자까지)'}
              </span>
            </label>

            <label className={styles.field}>
              <span className={styles.label}>한 번 더</span>
              <input
                className={styles.input}
                type="password"
                autoComplete="new-password"
                value={again}
                onChange={(e) => setAgain(e.target.value)}
                disabled={pending}
              />
              {mismatch && <span className={styles.hintBad}>두 번 입력한 비밀번호가 다릅니다</span>}
            </label>

            {error && <p className={styles.error}>{error}</p>}

            <div className={styles.actions}>
              <button
                type="submit"
                className={styles.primary}
                disabled={pending || password === '' || problem !== null || password !== again}
              >
                {pending ? '정하는 중…' : '비밀번호 정하기'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
