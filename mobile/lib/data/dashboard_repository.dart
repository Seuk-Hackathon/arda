/// 대시보드(홈 탭)가 한 번에 받아 오는 것 (큐 8 4단계, 2026-09-03).
///
/// 블록 넷이 소스가 다 달라서 **한 번에 병렬로** 부른다. 순서대로 기다리면
/// 홈 탭을 열 때마다 왕복이 줄줄이 쌓인다 — 웹 `Dashboard.tsx` 도 같다.
///
/// **전형 현황은 진행중 공고만 센다**(2026-09-03 결정). 마감된 공고 지원자가
/// 숫자를 먹으면 "지금 뭘 해야 하나" 가 안 읽힌다. 공고 목록이 이미 공고별
/// 단계 인원과 지원자를 주므로 **요청이 하나도 더 들지 않는다.**
library;

import '../models/interview.dart';
import '../models/job_posting.dart';
import '../models/stage.dart';
import 'posting_repository.dart';
import 'schedule_repository.dart';

/// 대시보드 한 화면에 필요한 것 전부.
class DashboardData {
  const DashboardData({
    required this.todayInterviews,
    required this.weekInterviews,
    required this.openPostings,
    required this.stageCounts,
  });

  /// 오늘 확정된 면접
  final List<Interview> todayInterviews;

  /// **그 주 전체**(일요일~토요일)의 확정 면접. 오늘 것도 들어 있다.
  ///
  /// 2026-09-15 에 더했다. 홈 히어로가 오늘이 0건일 때 「이번 주에 N건」과
  /// 「가장 가까운 면접」을 말하는데, 그 둘이 여기서 나온다. **호출은 안 늘었다**
  /// — 오늘 하루를 묻던 것을 한 주로 넓힌 것뿐이다(캘린더가 이미 그렇게 쓴다).
  final List<Interview> weekInterviews;

  /// 진행중 공고 + 그 공고의 단계별 인원
  final List<PostingWithCounts> openPostings;

  /// **진행중 공고만** 합친 단계별 인원
  final Map<Stage, int> stageCounts;
}

// 2026-09-07 — applicantsByStage · scheduleStatus 를 걷었다.
// 대시보드가 단계마다 지원자 이름을 적던 블록이 없어지면서(웹과 같은 개편)
// 쓰는 곳이 사라졌다. 일정 칩을 묻던 요청 N 개도 같이 사라진다.

/// 일정 칩 하나 — 상태 + (확정이면) 그 시각.
///
/// **상태만으로는 못 그린다.** 확정은 문구 대신 시각을 적는 규칙인데
/// (`ScheduleStatus.confirmed.label` 이 빈 문자열이다), 그 시각이 오늘이 아닐 수
/// 있다. 오늘 면접 목록에서만 찾으면 **다른 날로 확정된 사람의 칩이 빈 알약이
/// 된다**(2026-09-03 실기기에서 잡은 것). 서버가 `confirmed_slot` 을 같이 주므로
/// 그걸 들고 다닌다 — 웹 `Dashboard.tsx` 의 `scheduleChip` 과 같은 처리다.
class ScheduleChip {
  const ScheduleChip(this.status, {this.confirmedAt});

  final ScheduleStatus status;

  /// 확정된 면접 시각. 확정이 아니면 null
  final DateTime? confirmedAt;
}

class DashboardRepository {
  /// 2026-09-15 까지 `ApiClient` 도 받았다 — 내 리뷰 대기 수를 직접 물었는데,
  /// 평가 현황을 지우면서 그 호출이 없어져 이제 다른 저장소만 엮는다
  const DashboardRepository(this._postings, this._schedules);
  final PostingRepository _postings;
  final ScheduleRepository _schedules;

  /// 대시보드에서 이름을 적는 인원 — 이 수만큼만 일정 상태를 묻는다.
  /// 웹은 5명이고 앱 화면은 3명이다(dashboard_screen.dart `_perStage`)
  static const namedPerStage = 3;

  Future<DashboardData> load({DateTime? today}) async {
    final day = today ?? DateTime.now();

    // 둘을 동시에 던진다. 순서대로 기다릴 이유가 없다.
    // 2026-09-15 까지 셋이었다 — `GET /interviewers/{me}/applications`(내 리뷰
    // 대기 수)가 있었는데, 평가 현황을 지우면서 그 숫자도 갈 데가 없어졌다.
    //
    // **하루가 아니라 그 주를 받는다** (2026-09-15). 홈 히어로가 「이번 주 N건」과
    // 「가장 가까운 면접」을 말해야 하는데, 하루치만 받으면 오늘이 0건일 때
    // 할 말이 없다. 캘린더가 이미 같은 단위로 부르고 있어 새 경로가 아니다.
    final (week, postings) = await (
      _schedules.week(day),
      _postings.list(),
    ).wait;

    // 파라미터 `today` 와 이름이 겹치지 않게 `dayOnly`
    final dayOnly = DateTime(day.year, day.month, day.day);
    final interviews = [
      for (final i in week)
        if (DateTime(i.startAt.year, i.startAt.month, i.startAt.day) == dayOnly)
          i,
    ];

    final open = [
      for (final p in postings)
        if (p.posting.status == PostingStatus.open) p,
    ];

    // **진행중 공고만** 합친다 (2026-09-03 결정)
    final counts = {for (final s in Stage.values) s: 0};
    for (final p in open) {
      for (final entry in p.counts.entries) {
        counts[entry.key] = counts[entry.key]! + entry.value;
      }
    }

    return DashboardData(
      todayInterviews: interviews,
      weekInterviews: week,
      openPostings: open,
      stageCounts: counts,
    );
  }
}
