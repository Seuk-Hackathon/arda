/// 캘린더 (캘린더 탭) — 앱 UI 초안(2026-09-01) 조각 10.
///
/// **월 그리드를 그리지 않는다.** 05-design 캘린더 절이 못 박았다:
///
/// > ≤768px 은 월 그리드가 안 들어가므로 **주간 스트립(선택한 날이 든 한 주 7칸,
/// > 건수만) + 그날 목록**으로 떨어뜨린다(모바일 칸반 금지와 같은 근거 —
/// > 가로 스크롤로 밀어 넣지 않는다).
///
/// 그래서 이동 단위도 달이 아니라 주다. 데이터는 **확정된 일정 제안만**이고
/// (ADR-0016) 이 화면에서 등록·수정·삭제는 없다 — `GET /schedules` 조회 전용.
///
/// "내 면접만"은 권한이 아니라 필터다 — 조회는 로그인한 사람이면 전원 가능하고
/// 역할로 목록을 자르던 A3 는 폐지됐다(05-design 캘린더 절).
library;

import 'package:flutter/material.dart';

import '../auth/authed_client.dart';
import '../auth/current_user.dart';
import '../data/repositories.dart';
import '../data/schedule_repository.dart';
import '../widgets/async_view.dart';
import '../models/applicant.dart';
import '../models/interview.dart';
import '../models/stage.dart';
import '../routes.dart';
import '../theme/tokens.dart';
import '../utils/format.dart';

/// 테스트가 스트립과 날짜 칸을 정확히 집을 손잡이.
/// 날짜 숫자는 건수 숫자와 겹쳐서(2일 vs 2건) 글자만으로는 특정할 수 없다.
const weekStripKey = Key('calendar-week-strip');
Key dayCellKey(DateTime d) => Key('calendar-day-${d.year}-${d.month}-${d.day}');

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key, this.today, this.repository});

  /// 테스트가 날짜를 고정할 수 있게 열어 둔다. 비면 기기 오늘.
  final DateTime? today;

  /// 테스트가 가짜를 넣는 자리 (큐 8 4단계)
  final ScheduleRepository? repository;

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  late final DateTime _today = _dateOnly(widget.today ?? DateTime.now());
  late DateTime _selected = _today;

  late ScheduleRepository _repo;
  late Future<List<Interview>> _future;

  /// 지금 받아 둔 주의 일요일. 주를 옮겨 이 밖으로 나가면 다시 받는다
  late DateTime _loadedWeek;

  /// 05-design: 자기가 면접관인 건만 좁히는 **필터**. 기본은 전체.
  bool _mineOnly = false;

  static DateTime _dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

  static DateTime _sundayOf(DateTime d) =>
      _dateOnly(d).subtract(Duration(days: d.weekday % 7));

  @override
  void initState() {
    super.initState();
    _repo =
        widget.repository ??
        RepositoryScope.of(context)?.schedules ??
        ScheduleRepository(authedClient());
    _loadedWeek = _sundayOf(_selected);
    _future = _load();
  }

  /// `ignore()` 이유는 postings_screen.dart 참고
  Future<List<Interview>> _load() => _repo.week(_selected)..ignore();

  void _reload() {
    setState(() {
      _loadedWeek = _sundayOf(_selected);
      _future = _load();
    });
  }

  /// **내 것만**은 배정된 면접관 id 로 거른다. 이름으로 맞추면 동명이인이 섞인다
  List<Interview> _filter(List<Interview> items, int? myId) =>
      _mineOnly && myId != null
      ? items.where((i) => i.interviewerId == myId).toList()
      : items;

  void _moveWeek(int weeks) {
    final next = _selected.add(Duration(days: 7 * weeks));
    setState(() => _selected = next);
    // 같은 주 안에서 날짜만 옮기는 것은 이미 받아 둔 값으로 그린다
    if (_sundayOf(next) != _loadedWeek) _reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncView<List<Interview>>(
      future: _future,
      onRetry: _reload,
      // 면접이 없어도 주간 스트립과 컨트롤은 남아야 한다 — 날짜를 옮길 수
      // 있어야 "이 주만 비었다" 를 확인한다
      emptyMessage: '',
      builder: (context, items) => _body(items),
    );
  }

  Widget _body(List<Interview> items) {
    final myId = CurrentUserScope.of(context)?.id;

    // 서버는 한 주치를 한 줄로 준다. 스트립이 쓰는 "날짜 → 건수" 로 접는다
    final sunday = _sundayOf(_selected);
    final days = [for (var i = 0; i < 7; i++) sunday.add(Duration(days: i))];
    final week = <DateTime, List<Interview>>{
      for (final day in days)
        day: items.where((i) => _dateOnly(i.startAt) == day).toList(),
    };
    final selectedItems = _filter(week[_selected] ?? const [], myId);

    // 고른 날을 뺀 나머지 중 면접이 있는 날만, 날짜순
    final rest = [
      for (final day in days)
        if (day != _selected)
          if (_filter(week[day] ?? const [], myId).isNotEmpty)
            (day, _filter(week[day] ?? const [], myId)),
    ];
    final weekTotal =
        selectedItems.length +
        rest.fold(0, (sum, entry) => sum + entry.$2.length);

    return ListView(
      padding: const EdgeInsets.all(AppSpace.s4),
      children: [
        _Controls(
          rangeLabel:
              '${formatMonthDay(days.first)} – ${formatMonthDay(days.last)}',
          mineOnly: _mineOnly,
          onPrev: () => _moveWeek(-1),
          onNext: () => _moveWeek(1),
          onToggleMine: () => setState(() => _mineOnly = !_mineOnly),
          onToday: () => setState(() => _selected = _today),
        ),
        const SizedBox(height: AppSpace.s3),
        _WeekStrip(
          days: days,
          selected: _selected,
          today: _today,
          countOf: (day) => _filter(week[day] ?? const [], myId).length,
          onSelect: (day) => setState(() => _selected = day),
        ),
        const SizedBox(height: AppSpace.s5),
        _DayHeader(day: _selected, count: selectedItems.length),
        const SizedBox(height: AppSpace.s2),

        // **빈 날이 이 화면의 기본 상태다** (2026-09-15). 면접은 한 주에 몇
        // 건이고 나머지 날은 원래 비어 있다. 전에는 「면접 없음」 큰 상자 하나로
        // 끝나 화면의 60% 가 검게 남았다(실기기에서 확인).
        //
        // 이번 주에 뭔가 있으면 아래에서 보여 주므로 여기서는 한 줄만 말하고,
        // 이번 주가 통째로 비었을 때만 따로 안내한다.
        if (selectedItems.isEmpty && weekTotal == 0)
          _EmptyWeek(onNextWeek: () => _moveWeek(1))
        else if (selectedItems.isEmpty)
          const _EmptyDay()
        else
          _DayList(items: selectedItems),

        // 고른 날 말고 이번 주에 남은 것. **한 주치를 이미 받아 뒀다** —
        // `_repo.week()` 로 받아 놓고 엿새를 버리고 있었다(같은 주 안에서
        // 날짜만 옮길 때는 다시 받지도 않는다). 서버 호출이 안 늘어난다.
        if (rest.isNotEmpty) ...[
          const SizedBox(height: AppSpace.s5),
          _RestOfWeek(days: rest, sameDayAsSelected: selectedItems.isNotEmpty),
        ],
      ],
    );
  }
}

/// 주 이동 · 내 면접만 · 오늘.
///
/// 05-design 은 웹 캘린더에 "이전/다음 **달**" 을 두지만, 앱은 스트립이 한 주라
/// 이동도 주 단위다. 달을 옮기는 컨트롤을 두면 화면에 없는 날로 가 버린다.
class _Controls extends StatelessWidget {
  const _Controls({
    required this.rangeLabel,
    required this.mineOnly,
    required this.onPrev,
    required this.onNext,
    required this.onToggleMine,
    required this.onToday,
  });

  final String rangeLabel;
  final bool mineOnly;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onToggleMine;
  final VoidCallback onToday;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _RoundIcon(icon: Icons.chevron_left, label: '지난 주', onTap: onPrev),
        Text(
          rangeLabel,
          softWrap: false,
          style: const TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: AppType.h2,
            fontWeight: FontWeight.w700,
            fontFeatures: AppType.tabularNums,
            color: AppColors.text,
            shadows: AppTextShadow.heading,
          ),
        ),
        _RoundIcon(icon: Icons.chevron_right, label: '다음 주', onTap: onNext),
        const Spacer(),
        _Pill(label: '내 면접만', selected: mineOnly, onTap: onToggleMine),
        const SizedBox(width: AppSpace.s2),
        _Pill(label: '오늘', selected: false, onTap: onToday),
      ],
    );
  }
}

class _RoundIcon extends StatelessWidget {
  const _RoundIcon({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: label,
      child: Material(
        color: Colors.transparent,
        shape: const CircleBorder(),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          highlightColor: AppColors.bgSunken,
          splashColor: AppColors.bgSunken,
          // §9 터치 타깃 44
          child: SizedBox(
            width: AppLayout.minTouchTarget,
            height: AppLayout.minTouchTarget,
            child: Icon(icon, size: 24, color: AppColors.textSub),
          ),
        ),
      ),
    );
  }
}

/// 알약 버튼 — 켜지면 연두 워시 + 잎 글자(05-design §1).
class _Pill extends StatelessWidget {
  const _Pill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      child: Material(
        color: selected ? AppColors.sproutSoft : AppColors.bgSunken,
        borderRadius: AppShape.pill,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          highlightColor: AppColors.sunkenHover,
          splashColor: AppColors.sunkenHover,
          child: Container(
            height: 32,
            padding: const EdgeInsets.symmetric(horizontal: AppSpace.s3),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: AppShape.pill,
              border: Border.all(
                color: selected ? AppColors.sprout : AppColors.border,
                width: AppShape.borderW,
              ),
            ),
            child: Text(
              label,
              softWrap: false,
              style: TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.sm,
                fontWeight: selected ? AppType.wSemiBold : AppType.wRegular,
                color: selected ? AppColors.leaf : AppColors.textSub,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 주간 스트립 — 한 주 7칸, **건수만**.
///
/// 월 그리드가 셀에 면접 3건까지 적고 넘치면 `+N건` 으로 접는 것과 달리,
/// 스트립은 숫자 하나만 놓는다. 45dp 칸에 이름이 들어가지 않는다.
class _WeekStrip extends StatelessWidget {
  const _WeekStrip({
    required this.days,
    required this.selected,
    required this.today,
    required this.countOf,
    required this.onSelect,
  });

  final List<DateTime> days;
  final DateTime selected;
  final DateTime today;
  final int Function(DateTime) countOf;
  final ValueChanged<DateTime> onSelect;

  static const _labels = ['일', '월', '화', '수', '목', '금', '토'];

  @override
  Widget build(BuildContext context) {
    return Container(
      key: weekStripKey,
      padding: const EdgeInsets.all(AppSpace.s2),
      decoration: BoxDecoration(
        color: AppColors.bgElev,
        borderRadius: AppShape.card,
        border: Border.all(color: AppColors.border, width: AppShape.borderW),
        boxShadow: AppShadow.card,
      ),
      child: Row(
        children: [
          for (var i = 0; i < days.length; i++)
            Expanded(
              child: _DayCell(
                key: dayCellKey(days[i]),
                day: days[i],
                weekdayLabel: _labels[i],
                count: countOf(days[i]),
                isSelected: days[i] == selected,
                isToday: days[i] == today,
                onTap: () => onSelect(days[i]),
              ),
            ),
        ],
      ),
    );
  }
}

class _DayCell extends StatelessWidget {
  const _DayCell({
    super.key,
    required this.day,
    required this.weekdayLabel,
    required this.count,
    required this.isSelected,
    required this.isToday,
    required this.onTap,
  });

  final DateTime day;
  final String weekdayLabel;
  final int count;
  final bool isSelected;
  final bool isToday;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    // **일요일 적갈을 뺐다** (2026-09-15). §1 은 적갈을 불합격·실패에만 쓴다.
    // 종이 달력의 관습을 빌려 오느라 예외를 하나 만들어 뒀던 자리인데,
    // 그 관습 때문에 "이 날 뭔가 잘못됐다"로 읽힐 여지가 더 컸다.

    return Semantics(
      button: true,
      selected: isSelected,
      label: '${formatDate(day)} 면접 $count건',
      excludeSemantics: true,
      // **선택 표시를 한 톤 낮췄다** (2026-09-15). 전에는 밝은 시안 채움이라
      // 화면에서 제일 센 요소였는데, 그 날이 0건일 때가 많아 "여기 뭔가 있다"로
      // 잘못 읽혔다. 워시 + 아래 심지는 사이드바 활성 표시와 같은 언어다
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: isSelected
              ? AppColors.accentSoft
              : isToday
              ? AppColors.bgSunken
              : Colors.transparent,
          borderRadius: AppShape.ctl,
          border: isSelected
              ? Border.all(color: AppColors.accent, width: AppShape.borderW)
              : null,
        ),
        child: Material(
          color: Colors.transparent,
          borderRadius: AppShape.ctl,
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            highlightColor: AppColors.bgSunken,
            splashColor: AppColors.bgSunken,
            child: SizedBox(
              // §9 터치 타깃 44
              // 요일·날짜·건수 세 줄 + §9 터치 타깃 44. 44+12 로는 6px 넘친다
              height: AppLayout.minTouchTarget + AppSpace.s5,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    weekdayLabel,
                    style: TextStyle(
                      fontFamily: AppType.fontFamily,
                      fontSize: AppType.caption,
                      color: AppColors.textSub,
                    ),
                  ),
                  const SizedBox(height: AppSpace.s1),
                  Text(
                    '${day.day}',
                    style: TextStyle(
                      fontFamily: AppType.fontFamily,
                      fontSize: AppType.num,
                      fontWeight: isSelected || isToday
                          ? AppType.wSemiBold
                          : AppType.wRegular,
                      fontFeatures: AppType.tabularNums,
                      color: isSelected || isToday
                          ? AppColors.text
                          : AppColors.textSub,
                    ),
                  ),
                  const SizedBox(height: AppSpace.s1),
                  // **0 은 숫자로 안 찍는다** (2026-09-15). 일곱 칸에 0 이 줄지어
                  // 서면 노이즈만 된다 — 웹 대시보드가 이미 쓰는 규칙이다
                  // ("0 건인 날은 막대를 그리지 않는다. 없는 것과 적은 것은 다르다").
                  // 자리는 점으로 남긴다: 빼 버리면 칸 높이가 날마다 달라진다
                  SizedBox(
                    height: AppType.caption + 2,
                    child: count == 0
                        ? Center(
                            child: Container(
                              width: 4,
                              height: 4,
                              decoration: const BoxDecoration(
                                shape: BoxShape.circle,
                                color: AppColors.border,
                              ),
                            ),
                          )
                        : Text(
                            '$count',
                            style: const TextStyle(
                              fontFamily: AppType.fontFamily,
                              fontSize: AppType.caption,
                              fontWeight: AppType.wSemiBold,
                              fontFeatures: AppType.tabularNums,
                              color: AppColors.accentText,
                            ),
                          ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 이번 주가 통째로 비었을 때.
///
/// **왜 비었는지와 다음에 뭘 할지를 말한다.** 화면이 "없다"만 말하고 끝나면
/// 담당자는 앱이 고장 난 것인지 정말 없는 것인지 모른다. 일정은 지원자가
/// 후보 시간에서 고를 때 잡히므로(ADR-0016) 이 화면에서 만들 수 있는 것이
/// 없다 — 그 사실도 같이 적는다.
class _EmptyWeek extends StatelessWidget {
  const _EmptyWeek({required this.onNextWeek});

  final VoidCallback onNextWeek;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpace.s4),
      decoration: BoxDecoration(
        borderRadius: AppShape.card,
        border: Border.all(
          color: AppColors.borderSoft,
          width: AppShape.borderW,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '이번 주는 면접이 없어요',
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: AppType.sm,
              fontWeight: AppType.wSemiBold,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: AppSpace.s1),
          const Text(
            '확정된 일정이 생기면 여기에 나타나요.\n'
            '일정은 지원자가 후보 시간에서 고르면 잡힙니다.',
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: AppType.caption,
              height: 1.6,
              color: AppColors.textSub,
            ),
          ),
          const SizedBox(height: AppSpace.s3),
          // §1: 주 동작 버튼은 흰 판 + 어두운 글자
          Material(
            color: AppColors.accentFill,
            borderRadius: AppShape.ctl,
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onNextWeek,
              child: Container(
                constraints: const BoxConstraints(
                  minHeight: AppLayout.minTouchTarget,
                ),
                padding: const EdgeInsets.symmetric(horizontal: AppSpace.s4),
                alignment: Alignment.center,
                child: const Text(
                  '다음 주 보기',
                  style: TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.caption,
                    fontWeight: FontWeight.w700,
                    color: AppColors.onAccent,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 고른 날을 뺀 이번 주의 나머지.
///
/// **한 주치를 이미 받아 두고 엿새를 버리고 있었다** — `_repo.week()` 가
/// 일요일~토요일을 통째로 주는데 화면은 고른 날 하나만 그렸다. 서버 호출을
/// 늘리지 않고 빈 자리를 채울 수 있는 유일한 재료다.
///
/// 05-design 캘린더 절의 "주간 스트립 + 그날 목록" 구조는 그대로다 — 이것은
/// 그날 목록을 **대신하는 것이 아니라 아래에 더하는 것**이다.
class _RestOfWeek extends StatelessWidget {
  const _RestOfWeek({required this.days, required this.sameDayAsSelected});

  /// (날짜, 그날 면접들). 날짜순으로 들어온다
  final List<(DateTime, List<Interview>)> days;

  /// 고른 날에도 면접이 있었는가. 제목 문구가 갈린다
  final bool sameDayAsSelected;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Text(
              sameDayAsSelected ? '이번 주 남은 것' : '이번 주 다른 날',
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.caption,
                fontWeight: AppType.wSemiBold,
                letterSpacing: 0.4,
                color: AppColors.textSub,
              ),
            ),
            const SizedBox(width: AppSpace.s2),
            const Expanded(
              child: Divider(height: 1, color: AppColors.borderSoft),
            ),
          ],
        ),
        for (final (day, items) in days) ...[
          const SizedBox(height: AppSpace.s3),
          _RestDay(day: day, items: items),
        ],
      ],
    );
  }
}

/// 나머지 주의 하루 — 왼쪽에 날짜, 오른쪽에 그날 목록.
class _RestDay extends StatelessWidget {
  const _RestDay({required this.day, required this.items});

  final DateTime day;
  final List<Interview> items;

  static const _labels = ['월', '화', '수', '목', '금', '토', '일'];

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 40,
          child: Padding(
            padding: const EdgeInsets.only(top: AppSpace.s3),
            child: Column(
              children: [
                Text(
                  '${day.day}',
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.num,
                    fontWeight: AppType.wSemiBold,
                    fontFeatures: AppType.tabularNums,
                    color: AppColors.text,
                  ),
                ),
                Text(
                  _labels[day.weekday - 1],
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: 10,
                    color: AppColors.textSub,
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(width: AppSpace.s2),
        Expanded(child: _DayList(items: items)),
      ],
    );
  }
}

class _DayHeader extends StatelessWidget {
  const _DayHeader({required this.day, required this.count});

  final DateTime day;
  final int count;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          formatDate(day),
          style: const TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: AppType.sm,
            fontWeight: AppType.wSemiBold,
            fontFeatures: AppType.tabularNums,
            color: AppColors.text,
          ),
        ),
        const Spacer(),
        Text(
          formatItemCount(count),
          style: const TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: AppType.sm,
            fontFeatures: AppType.tabularNums,
            color: AppColors.textSub,
          ),
        ),
      ],
    );
  }
}

/// 그날 목록 — 시각 · 지원자 · 공고 · 면접관.
///
/// 05-design 은 이 목록을 테이블로 두지만 §9 가 "테이블은 카드형"이라 카드 행으로 편다.
/// 같은 시각이 여러 건이면 시각은 첫 행에만 적는다 — "같은 시간대는 슬롯으로 묶고
/// 대표는 그 슬롯에서 가장 이른 면접"(캘린더 절)의 앱 표기다.
class _DayList extends StatelessWidget {
  const _DayList({required this.items});

  final List<Interview> items;

  @override
  Widget build(BuildContext context) {
    final sorted = [...items]..sort((a, b) => a.startAt.compareTo(b.startAt));

    return Container(
      decoration: BoxDecoration(
        color: AppColors.bgElev,
        borderRadius: AppShape.card,
        border: Border.all(color: AppColors.border, width: AppShape.borderW),
        boxShadow: AppShadow.card,
      ),
      child: Column(
        children: [
          for (var i = 0; i < sorted.length; i++)
            _Row(
              interview: sorted[i],
              // 앞 건과 같은 시각이면 시각을 다시 적지 않는다
              showTime: i == 0 || sorted[i].startAt != sorted[i - 1].startAt,
              first: i == 0,
            ),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({
    required this.interview,
    required this.showTime,
    required this.first,
  });

  final Interview interview;
  final bool showTime;
  final bool first;

  /// 05-design 캘린더 절(2026-09-01): "**행 클릭 = 그 지원자의 상세 패널**".
  ///
  /// 웹은 `/postings/{공고}?applicant={지원}` 으로 보내 공고의 지원자 화면이 그
  /// 사람을 연 채로 뜨게 한다. 앱은 상세가 별도 화면이라 곧장 그리로 간다.
  ///
  /// **껍데기만 만들어 넘긴다.** `GET /schedules` 는 지원자 id·이름·공고명만
  /// 주고 나머지(단계·이메일·경력)는 안 준다. 상세 화면이 어차피 id 로 다시
  /// 받으므로, 머리에 잠깐 쓸 이름과 id 만 채우면 된다.
  ///
  /// 단계는 `면접` 으로 둔다 — 확정된 면접이 잡힌 사람이라 맞고, 상세가 오면
  /// 진짜 값으로 바뀐다.
  void _openDetail(BuildContext context) {
    final stub = Applicant(
      id: interview.applicationId,
      jobPostingId: 0,
      name: interview.applicantName,
      email: '',
      currentStage: Stage.interview,
      createdAt: interview.startAt,
    );

    Navigator.pushNamed(
      context,
      Routes.applicantDetail,
      arguments: (stub, interview.postingTitle),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        border: first
            ? null
            : const Border(
                top: BorderSide(
                  color: AppColors.borderSoft,
                  width: AppShape.borderW,
                ),
              ),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: () => _openDetail(context),
          // §5: 모바일은 hover 없음 전제 — press 만 정의한다
          highlightColor: AppColors.bgSunken,
          splashColor: AppColors.bgSunken,
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpace.s4,
              vertical: AppSpace.s3,
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 48,
                  child: Text(
                    showTime ? formatTime(interview.startAt) : '',
                    softWrap: false,
                    style: const TextStyle(
                      fontFamily: AppType.fontFamily,
                      fontSize: AppType.num,
                      fontWeight: AppType.wSemiBold,
                      fontFeatures: AppType.tabularNums,
                      color: AppColors.leaf,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpace.s3),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        interview.applicantName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontFamily: AppType.fontFamily,
                          fontSize: AppType.body,
                          fontWeight: AppType.wSemiBold,
                          color: AppColors.text,
                        ),
                      ),
                      const SizedBox(height: AppSpace.s1),
                      Text(
                        interview.postingTitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontFamily: AppType.fontFamily,
                          fontSize: AppType.caption,
                          color: AppColors.textSub,
                        ),
                      ),
                      const SizedBox(height: AppSpace.s1),
                      Text(
                        '면접관 ${interview.interviewerName}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontFamily: AppType.fontFamily,
                          fontSize: AppType.caption,
                          color: AppColors.textSub,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 면접이 없는 날. 05-design §6 의 빈 상태 — 웹 대시보드가 쓰는 문구를 그대로 쓴다.
/// 고른 날만 비었을 때 — **상자를 그리지 않는다** (2026-09-15).
///
/// 전에는 높이 100px 가 넘는 빈 카드였다. 비어 있다는 말을 하려고 큰 면을
/// 그리면 허전함이 오히려 커진다. 아래에 이번 주 다른 날이 이어지므로
/// 여기서는 한 줄이면 된다.
class _EmptyDay extends StatelessWidget {
  const _EmptyDay();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: AppSpace.s1),
      child: Text(
        '이 날은 면접이 없어요.',
        style: TextStyle(
          fontFamily: AppType.fontFamily,
          fontSize: AppType.sm,
          color: AppColors.textSub,
        ),
      ),
    );
  }
}
