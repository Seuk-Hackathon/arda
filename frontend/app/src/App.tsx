import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { AuthProvider } from './auth/AuthContext'
import { ToastProvider } from './components/Toast'
import { RightPanelProvider } from './components/RightPanel'
import DiveTransition from './components/DiveTransition'
import RequireAuth from './auth/RequireAuth'
import Login from './pages/Login'
import Apply from './pages/Apply'
import Schedule from './pages/Schedule'
// Interview 컴포넌트는 옛 파일 업로드 흐름 (`./pages/Interview.tsx`).
// 2026-09-14 부터 `/interview/:token` 라우트는 `InterviewAi` 를 씀. Interview.tsx
// 파일은 남겨 두었지만 (텍스트 fallback 검토용) import 는 뺐다 — TS 미사용 에러 방지.
import InterviewRoom from './pages/InterviewRoom'
import InterviewLive from './pages/InterviewLive'
import InterviewAi from './pages/InterviewAi'
import InterviewWatch from './pages/InterviewWatch'
import MyShell from './pages/MyShell'
import Aptitude from './pages/Aptitude'
import SetPassword from './pages/SetPassword'
import Dashboard from './pages/Dashboard'
import Postings from './pages/Postings'
import PostingApplicants from './pages/PostingApplicants'
import Applicants from './pages/Applicants'
import Interviews from './pages/Interviews'
import Summary from './pages/Summary'
import SummaryDetail from './pages/SummaryDetail'
import Settings from './pages/Settings'
import More from './pages/More'
/* three.js 를 초기 번들에서 빼기 위해 이 페이지도 지연 로드한다 (Sidebar 의 ArViewer 와 같은 청크) */
const ArDemo = lazy(() => import('./pages/ArDemo'))

/* 캘린더는 08/31 에 /interviews 에서 /calendar 로 옮겼다. 옛 경로로 들어오면
   쿼리(?slot= 같은 딥링크)를 그대로 달고 새 경로로 보낸다. */
function LegacyCalendarRedirect() {
  const { search } = useLocation()
  return <Navigate to={`/calendar${search}`} replace />
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
      {/* 오른쪽 패널은 한 번에 하나 — 아르와 그날 일정이 같은 자리를 쓴다 */}
      <RightPanelProvider>
      {/* 로그인 → 대시보드 접속 시퀀스. 흰빛이 화면 교체를 건너 살아남아야
          하므로 라우트 밖에 둔다 */}
      <DiveTransition>
      <Routes>
        {/* 루트는 대시보드로. 비로그인은 RequireAuth 가 /login 으로 보낸다 */}
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/login" element={<Login />} />
        {/* 공개 지원 폼 (C1). 지원자는 로그인이 없으므로 RequireAuth·Layout 밖이다. */}
        <Route path="/apply/:token" element={<Apply />} />
        {/* 지원자 비밀번호 설정 — 메일 링크 착지점 (2026-09-16).
            **경로를 서버가 조립한다** (`{PUBLIC_APP_BASE_URL}/set-password/<token>`)
            — 바꾸려면 백엔드와 같이 바꿔야 한다. 처음 정하기·재설정·재발급이
            모두 이 한 경로다. */}
        <Route path="/set-password/:token" element={<SetPassword />} />
        {/* 지원자용 면접 일정 선택 — 메일 링크 착지점 (ADR-0016). 마찬가지로 로그인 밖 */}
        <Route path="/schedule/:token" element={<Schedule />} />
        {/* 지원자용 AI 면접 — 메일 링크 착지점. 로그인 밖.
            2026-09-14: 옛 파일 업로드 흐름 (`<Interview />`) 을 앱(`mobile/lib/screens/
            interview_screen.dart`) 과 같은 실시간 소켓 흐름 (`<InterviewAi />`) 으로
            교체. 메일에서 오는 링크가 앱 링크와 같은 UX 를 주게. 옛 Interview 컴포넌트는
            남겨 두었다 (텍스트 fallback 검토 시 재활용). */}
        <Route path="/interview/:token" element={<InterviewAi />} />
        {/* 지원자 본인 화면 (ADR-0033) — 이메일 + 생년월일로 들어온다.
            **담당자 로그인(`/login`)과 다른 자리다.** 같은 화면에 두면 지원자가
            담당자 계정으로 들어가려다 막힌다. 토큰도 자리를 나눠 뒀다.

            2026-09-15: 앱(ApplicantShell)처럼 **셸 + 탭**이 됐다. 셸이
            `/applicant/me` 를 한 번 부르고 탭에 나눠 준다. 아래 토큰 라우트
            (`/aptitude/:token` 등)는 **그대로 산다** — 메일 링크 착지점이고,
            로그인 없이 토큰만 들고 오는 사람이 있다. */}
        {/* 셸 하나가 `/my` 아래를 통째로 받는다. 탭마다 라우트를 파면
            라우터가 화면을 갈아 끼우는데, 그러면 인적성에서 답하던 것이
            날아가고 AI 면접이 끊긴다 — 셸이 탭을 살려 두는 이유는
            MyShell.tsx 에 적어 두었다. */}
        <Route path="/my/*" element={<MyShell />} />
        {/* 지원자 쪽 실시간 면접 — 면접관과 얼굴을 보고 말한다.
            채용자 쪽은 /interview-room/:sessionId 다. 로그인 밖 — 토큰이 곧 자격. */}
        <Route path="/interview-live/:token" element={<InterviewLive />} />
        {/* AI 면접 — 아르가 묻고 얼굴을 실시간으로 본다 (ADR-0029).
            지원자 쪽. 로그인 밖 — 토큰이 곧 자격이다. */}
        <Route path="/interview-ai/:token" element={<InterviewAi />} />
        {/* 사전 성향 설문 — 메일 링크의 토큰 접근 (ADR-0027) */}
        <Route path="/aptitude/:token" element={<Aptitude />} />
        {/* 아르 3D 모션 검토용. 내비 미노출·데이터 접근 없음 → 로그인 게이트 밖 */}
        <Route
          path="/dev/ar"
          element={
            <Suspense fallback={null}>
              <ArDemo />
            </Suspense>
          }
        />
        <Route element={<RequireAuth />}>
          {/* 채용자용 실시간 면접방. **로그인은 필요하지만 Layout 밖이다** —
              사이드바가 있으면 지원자 얼굴이 그만큼 작아지고, 면접 중에
              다른 데로 새는 길이 화면에 남는다. */}
          <Route path="/interview-room/:sessionId" element={<InterviewRoom />} />
          {/* AI 면접이 도는 동안 담당자가 판정을 보는 화면. 카메라를 켜지 않는다. */}
          <Route path="/interview-watch/:sessionId" element={<InterviewWatch />} />
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/postings" element={<Postings />} />
            <Route path="/postings/:id" element={<PostingApplicants />} />
            <Route path="/applicants" element={<Applicants />} />
            <Route path="/calendar" element={<Interviews />} />
            {/* 옛 경로. 북마크·메일 링크가 깨지지 않게 남긴다 */}
            <Route path="/interviews" element={<LegacyCalendarRedirect />} />
            <Route path="/summary" element={<Summary />} />
            <Route path="/summary/:applicationId" element={<SummaryDetail />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/more" element={<More />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
      </DiveTransition>
      </RightPanelProvider>
      </ToastProvider>
    </AuthProvider>
  )
}
