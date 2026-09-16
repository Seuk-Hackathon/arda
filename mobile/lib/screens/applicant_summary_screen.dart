/// 지원자 홈 — "내가 지금 뭘 해야 하지" 하나에 답한다 (2026-09-15 개편).
///
/// ## 왜 다시 짰나
///
/// 그 전에는 **같은 크기 카드가 쭉 쌓인 목록**이었다. 지원자가 앱을 켜는
/// 이유는 할 일 하나인데, 그 답이 다른 것들과 같은 무게로 섞여 있었다.
///
/// 지금은 **제일 급한 것 하나가 화면 위 3분의 1**을 쓴다. 지원이 여럿이어도
/// 하나만 고른다 — 답이 둘이면 답이 아니다.
///
/// ## 규칙 셋 (개편 전과 같다)
///
/// 1. **끝난 줄에는 버튼을 그리지 않는다** — 눌러도 막히는 문이 된다.
/// 2. **그래도 줄은 남긴다** — 없애면 "완료"와 "아직 안 잡힘"이 같은 화면이
///    된다(앱 실측에서 나온 것이다).
/// 3. **색은 거들 뿐이고 글자가 늘 같이 있다** — 점만 보고 판단하게 두지
///    않는다(05-design §1).
///
/// ## 새로 더한 것
///
/// - **마감** — 서버가 `expiresAt` 을 셋 다 주는데 안 쓰고 있었다. 사흘
///   아래부터 색을 준다: 늘 노랗게 두면 색이 뜻을 잃는다.
/// - **단계 막대** — 「면접 전형 진행 중」 글자 한 줄만으로는 앞에 뭘 지나왔고
///   뒤에 뭐가 남았는지 모른다.
///
/// **서버를 따로 부르지 않는다.** 셸이 받은 `GET /applicant/me` 하나에 단계도
/// 토큰도 상태도 다 들어 있다.
library;

import 'package:flutter/material.dart';

import '../models/applicant_me.dart';
import '../theme/tokens.dart';
import '../utils/format.dart';
import 'applicant_shell.dart';

/// 할 일이 있는가. **색은 거들 뿐이고 글자가 늘 같이 있다**
enum _Tone { todo, done, quiet }

/// 한 줄이 화면에 내보이는 것. 어느 탭으로 가는지까지 같이 들고 있다
class _Line {
  const _Line({
    required this.tab,
    required this.label,
    required this.state,
    required this.action,
    this.tone = _Tone.quiet,
    this.due,
  });

  final ApplicantTab tab;
  final String label;

  /// 지금 어떤지 — 한 줄
  final String state;

  /// 눌렀을 때 무엇을 하게 되는지. 빈 문자열이면 버튼을 안 그린다
  final String action;

  final _Tone tone;

  /// 남은 날. 없으면 마감이 없는 것이다
  final _Due? due;
}

/// 남은 날. **사흘이 경계다** — 그 아래부터 색을 준다
class _Due {
  const _Due(this.days);

  final int days;

  bool get near => days <= 3;

  String get text => days <= 0 ? '오늘까지' : '$days일 남음';
}

_Due? _dueOf(DateTime? at) {
  if (at == null) return null;
  final days = at.difference(DateTime.now()).inHours / 24;
  return _Due(days.ceil());
}

/// 지원자가 보는 전형. 담당자 화면의 진행 바와 같은 칸이다.
///
/// **서버가 단계 키를 안 준다** — `stageLabel` 이라는 화면용 글자만 온다
/// (`rejected` 를 "불합격"으로 앞질러 말하지 않으려던 것이고 그 판단은 맞다).
/// 그래서 글자를 거꾸로 맞춘다. 다섯 문구가 서로 안 겹쳐 오늘은 정확하다.
/// **못 맞추면 막대를 아예 안 그린다** — 첫 칸으로 되돌리거나 아무 데나 찍지
/// 않는다. 글자는 카드 머리에 그대로 나오므로 화면이 말을 잃지 않는다.
const _legNames = ['접수', '서류', '면접', '결과'];

const _stageByLabel = <String, int>{
  '접수 완료': 0,
  '서류 검토 중': 1,
  '면접 전형 진행 중': 2,
  '최종 합격': 3,
  '전형 종료': 3,
};

/// 마지막 칸이 합격인가 종료인가. 진행 중이면 null
String? _endingOf(String label) => switch (label) {
  '최종 합격' => 'win',
  '전형 종료' => 'stop',
  _ => null,
};

class ApplicantSummaryScreen extends StatelessWidget {
  const ApplicantSummaryScreen({
    super.key,
    required this.me,
    required this.onOpen,
    required this.onRefresh,
  });

  final ApplicantMe me;

  /// 탭을 옮겨 준다 — 요약은 자기가 어느 셸에 앉아 있는지 몰라야 한다
  final ValueChanged<ApplicantTab> onOpen;

  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (me.applications.isEmpty) {
      return const ApplicantMissing(what: '지원 내역');
    }

    /* 지금 제일 급한 일 하나. **여러 지원을 가로질러 고른다** — 이 화면을 여는
       이유가 하나라 답도 하나여야 한다. 인적성이 먼저고, 그 다음은 마감이
       가까운 순이다(마감 없는 것은 맨 뒤). */
    final open = <({MyApplication app, _Line line})>[];
    for (final app in me.applications) {
      for (final line in _linesOf(app)) {
        if (line.tone == _Tone.todo && line.action.isNotEmpty) {
          open.add((app: app, line: line));
        }
      }
    }
    open.sort((a, b) {
      int rank(_Line l) => l.label == '인적성 검사' ? 0 : 1;
      int left(_Line l) => l.due?.days ?? 9999;
      final byRank = rank(a.line).compareTo(rank(b.line));
      return byRank != 0 ? byRank : left(a.line).compareTo(left(b.line));
    });
    final top = open.isEmpty ? null : open.first;

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpace.s4,
          AppSpace.s2,
          AppSpace.s4,
          AppSpace.s5,
        ),
        children: [
          _Greeting(name: me.name),
          const SizedBox(height: AppSpace.s5),

          if (top != null)
            _NowCard(app: top.app, line: top.line, onOpen: onOpen)
          else
            const _CalmCard(),
          const SizedBox(height: AppSpace.s5),

          for (final app in me.applications) ...[
            _ApplicationBlock(app: app, onOpen: onOpen),
            const SizedBox(height: AppSpace.s3),
          ],
        ],
      ),
    );
  }
}

/// 인사. 이름이 목록의 한 줄이 아니라 화면의 머리다
class _Greeting extends StatelessWidget {
  const _Greeting({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '안녕하세요',
          style: TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: AppType.sm,
            color: AppColors.textSub,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          '$name 님',
          style: const TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: 24,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.5,
            color: AppColors.text,
            shadows: AppTextShadow.heading,
          ),
        ),
      ],
    );
  }
}

/// **지금 하실 일 하나.** 화면 위 3분의 1을 쓴다 — 이 화면을 여는 이유다
class _NowCard extends StatelessWidget {
  const _NowCard({required this.app, required this.line, required this.onOpen});

  final MyApplication app;
  final _Line line;
  final ValueChanged<ApplicantTab> onOpen;

  @override
  Widget build(BuildContext context) {
    final first = line.label == '인적성 검사';
    return Container(
      padding: const EdgeInsets.all(AppSpace.s5),
      decoration: BoxDecoration(
        borderRadius: const BorderRadius.all(Radius.circular(24)),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.32)),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.accent.withValues(alpha: 0.20),
            AppColors.accentBlue.withValues(alpha: 0.10),
            AppColors.accentViolet.withValues(alpha: 0.14),
          ],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 6,
                height: 6,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  color: AppColors.accent,
                ),
              ),
              const SizedBox(width: AppSpace.s2),
              Text(
                first ? '먼저 하실 일' : '지금 하실 일',
                style: const TextStyle(
                  fontFamily: AppType.fontFamily,
                  fontSize: 11,
                  fontWeight: AppType.wSemiBold,
                  letterSpacing: 1.1,
                  color: AppColors.accentText,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpace.s3),
          Text(
            line.label,
            style: const TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: 26,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.6,
              height: 1.2,
              color: AppColors.text,
            ),
          ),
          const SizedBox(height: AppSpace.s1),
          Text(
            app.postingTitle,
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: AppType.caption,
              color: AppColors.text.withValues(alpha: 0.72),
            ),
          ),
          const SizedBox(height: AppSpace.s5),
          Row(
            children: [
              Expanded(
                child: _FilledButton(
                  label: line.action,
                  onTap: () => onOpen(line.tab),
                ),
              ),
              if (line.due != null) ...[
                const SizedBox(width: AppSpace.s3),
                Text(
                  line.due!.text,
                  style: TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.caption,
                    fontWeight: AppType.wSemiBold,
                    color: line.due!.near
                        ? AppColors.warnText
                        : AppColors.textSub,
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

/// 할 일이 없는 날. **대부분의 날이 그렇다** — 빈 자리로 두면 매일 앱을 켠다
class _CalmCard extends StatelessWidget {
  const _CalmCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpace.s5),
      decoration: BoxDecoration(
        borderRadius: const BorderRadius.all(Radius.circular(24)),
        border: Border.all(color: AppColors.border),
        color: AppColors.bgElev,
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '지금은',
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: 11,
              fontWeight: AppType.wSemiBold,
              letterSpacing: 1.1,
              color: AppColors.textSub,
            ),
          ),
          SizedBox(height: AppSpace.s3),
          Text(
            '기다리시면 돼요',
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: 22,
              fontWeight: FontWeight.w800,
              letterSpacing: -0.4,
              color: AppColors.text,
            ),
          ),
          SizedBox(height: AppSpace.s1),
          // **다음이 어떻게 오는지**까지 적는다 — 안 적으면 매일 켜게 된다
          Text(
            '내신 건 모두 접수됐어요. 다음 안내는 메일로 드려요.',
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: AppType.caption,
              color: AppColors.textSub,
            ),
          ),
        ],
      ),
    );
  }
}

/// 흰 판 버튼. 05-design §1 — 주 동작은 흰 면이고 네온이 아니다
class _FilledButton extends StatelessWidget {
  const _FilledButton({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.accentFill,
      borderRadius: const BorderRadius.all(Radius.circular(16)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          height: 50,
          child: Center(
            child: Text(
              label,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.sm,
                fontWeight: AppType.wSemiBold,
                color: AppColors.onAccent,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 지원 한 건 — 공고·단계 머리, 진행 막대, 할 일 줄들
class _ApplicationBlock extends StatelessWidget {
  const _ApplicationBlock({required this.app, required this.onOpen});

  final MyApplication app;
  final ValueChanged<ApplicantTab> onOpen;

  @override
  Widget build(BuildContext context) {
    final ending = _endingOf(app.stageLabel);
    final over = ending != null;
    final lines = _linesOf(app);

    return Opacity(
      // 끝난 지원은 흐리다 — **지우지는 않는다**: 없애면 "완료"와 "아직 안
      // 잡힘"이 같아진다
      opacity: over ? 0.58 : 1,
      child: Container(
        padding: const EdgeInsets.all(AppSpace.s4),
        decoration: BoxDecoration(
          borderRadius: const BorderRadius.all(Radius.circular(20)),
          border: Border.all(color: AppColors.border),
          color: AppColors.bgElev,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // **단계 칩을 제목 위로 올렸다.** 제목 옆에 두니 칩이 가져간
            // 폭만큼 공고명이 잘렸다(실기기에서 「백엔드 개발…」로 끊겼다).
            // 위로 올리면 제목이 한 줄을 통째로 쓴다
            Row(
              children: [
                _StageChip(label: app.stageLabel, ending: ending),
                const SizedBox(width: AppSpace.s2),
                Expanded(
                  child: Text(
                    '${formatDate(app.appliedAt)} 지원',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: AppType.fontFamily,
                      fontSize: 11,
                      color: AppColors.textSub,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpace.s3),
            // **카드에서 제일 큰 것 하나.** 전에는 열두 요소가 전부 10~15px
            // 라 눈이 붙을 데가 없었다 — 그것이 이 카드가 밋밋했던 까닭이다
            Text(
              app.postingTitle,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: 19,
                fontWeight: FontWeight.w700,
                letterSpacing: -0.3,
                height: 1.25,
                color: AppColors.text,
              ),
            ),
            const SizedBox(height: AppSpace.s5),
            _StageRail(label: app.stageLabel),

            // 끝난 지원은 할 일을 접는다 — 할 것이 없다
            if (!over) ...[
              const SizedBox(height: AppSpace.s4),
              // **한 겹 내려앉힌다.** 카드가 평면 한 장이라 「공고·여정」과
              // 「할 일」이 같은 높이에 섞여 있었다. 층을 하나 파면 둘이
              // 눈에 두 덩어리로 갈린다 — 줄을 지우지 않고도 가벼워진다
              Container(
                decoration: const BoxDecoration(
                  borderRadius: BorderRadius.all(Radius.circular(14)),
                  color: AppColors.bgSunken,
                ),
                child: Column(
                  children: [
                    for (var i = 0; i < lines.length; i++) ...[
                      if (i > 0)
                        const Divider(
                          height: 1,
                          indent: AppSpace.s4,
                          endIndent: AppSpace.s4,
                          color: AppColors.borderSoft,
                        ),
                      _TodoRow(line: lines[i], onOpen: onOpen),
                    ],
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 단계 알약. **전형 종료에 빨간색을 쓰지 않는다** — 서버가 "불합격"이라고
/// 말하지 않기로 한 것과 같은 이유다
class _StageChip extends StatelessWidget {
  const _StageChip({required this.label, required this.ending});

  final String label;
  final String? ending;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (ending) {
      'win' => (AppColors.okSoft, AppColors.okText),
      'stop' => (AppColors.bgSunken, AppColors.textSub),
      _ => (AppColors.accentSoft, AppColors.accentText),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpace.s3, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: const BorderRadius.all(AppShape.rPill),
        color: bg,
      ),
      child: Text(
        label,
        style: TextStyle(
          fontFamily: AppType.fontFamily,
          fontSize: 11,
          fontWeight: AppType.wSemiBold,
          color: fg,
        ),
      ),
    );
  }
}

/// 네 역짜리 노선. **굵은 막대 넷이던 것을 점과 선으로 바꿨다.**
///
/// 막대는 카드에서 제일 무거운 요소였는데 정작 말하는 것은 「지금 세 번째」
/// 하나뿐이었다. 점·선은 같은 것을 말하면서 자리를 덜 차지해, 커진 공고명이
/// 카드의 주인이 된다.
///
/// **지나온 역과 안 온 역은 모양이 다르다** — 채운 점 대 빈 점. 색만으로
/// 가르지 않는다(05-design §1).
class _StageRail extends StatelessWidget {
  const _StageRail({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final idx = _stageByLabel[label];
    // 못 맞추면 아예 안 그린다 — 틀린 노선은 없는 것보다 나쁘다
    if (idx == null) return const SizedBox.shrink();
    final ending = _endingOf(label);
    final last = _legNames.length - 1;
    final now = switch (ending) {
      'win' => AppColors.ok,
      // 램프 밖이다 — 진행이 아니라 멈춤이라 무채색을 쓴다
      'stop' => const Color(0xFF4A5568),
      _ => AppColors.accent,
    };

    return Row(
      children: [
        for (var i = 0; i < _legNames.length; i++)
          Expanded(
            child: Column(
              children: [
                SizedBox(
                  height: 16,
                  child: Row(
                    children: [
                      // 양 끝 바깥쪽은 선을 안 그린다. 그래도 자리는 남겨야
                      // 네 점이 같은 간격으로 선다
                      Expanded(child: _wire(on: i <= idx, hide: i == 0)),
                      _dot(i: i, idx: idx, now: now),
                      Expanded(child: _wire(on: i < idx, hide: i == last)),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpace.s2),
                Text(
                  i == idx && ending == 'stop' ? '종료' : _legNames[i],
                  style: TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: 10,
                    fontWeight: i == idx
                        ? AppType.wSemiBold
                        : AppType.wRegular,
                    color: i == idx
                        ? (ending == 'win'
                              ? AppColors.okText
                              : ending == 'stop'
                              ? AppColors.textSub
                              : AppColors.accentText)
                        : i < idx
                        ? AppColors.textSub
                        : AppColors.textSub.withValues(alpha: 0.5),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _wire({required bool on, required bool hide}) => Container(
    height: 2,
    color: hide
        ? Colors.transparent
        : on
        ? AppColors.stage2
        : Colors.white.withValues(alpha: 0.08),
  );

  Widget _dot({required int i, required int idx, required Color now}) {
    // 지금 역만 링을 한 겹 두른다 — 「여기」가 한눈에 잡힌다
    if (i == idx) {
      return Container(
        width: 16,
        height: 16,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: now.withValues(alpha: 0.24),
        ),
        child: Center(
          child: Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(shape: BoxShape.circle, color: now),
          ),
        ),
      );
    }
    // 지나온 역 — 채운 점
    if (i < idx) {
      return Container(
        width: 8,
        height: 8,
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.stage3,
        ),
      );
    }
    // 아직 안 온 역 — 빈 점
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
      ),
    );
  }
}

/// 할 일 한 줄.
///
/// **번호 동그라미와 버튼 상자를 뺐다.** 순서는 위에서 아래로 이미 읽히고,
/// 바로 위 히어로가 같은 일을 큰 버튼으로 이미 말하는데 여기서 작은 흰 판을
/// 한 번 더 그리니 줄마다 무게가 붙었다. 게다가 흰 판이 한 화면에 둘이라
/// 05-design 의 「채운 흰 버튼은 화면에 하나」도 어기고 있었다.
///
/// **동사(「하기」)는 남긴다** — 무엇이 일어나는지는 정보고, 무거웠던 것은
/// 상자다. 대신 줄 전체가 눌린다.
class _TodoRow extends StatelessWidget {
  const _TodoRow({required this.line, required this.onOpen});

  final _Line line;
  final ValueChanged<ApplicantTab> onOpen;

  @override
  Widget build(BuildContext context) {
    final dot = switch (line.tone) {
      _Tone.done => AppColors.ok,
      _Tone.todo => AppColors.accent,
      _Tone.quiet => AppColors.neutral,
    };

    final row = Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpace.s4,
        vertical: AppSpace.s3,
      ),
      child: Row(
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(shape: BoxShape.circle, color: dot),
          ),
          const SizedBox(width: AppSpace.s3),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  line.label,
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: 13,
                    fontWeight: AppType.wSemiBold,
                    color: AppColors.text,
                  ),
                ),
                const SizedBox(height: 1),
                Text(
                  line.due != null
                      ? '${line.state} · ${line.due!.text}'
                      : line.state,
                  style: TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: 11,
                    // 사흘 아래면 마감이 먼저다 — 히어로가 쓰는 경계와 같다
                    color: line.due?.near == true
                        ? AppColors.warnText
                        : switch (line.tone) {
                            _Tone.todo => AppColors.accentText,
                            _Tone.done => AppColors.okText,
                            _Tone.quiet => AppColors.textSub,
                          },
                  ),
                ),
              ],
            ),
          ),
          // 갈 곳이 없으면 문을 안 그린다 — 눌러도 막히는 줄이 된다
          if (line.action.isNotEmpty) ...[
            const SizedBox(width: AppSpace.s2),
            Text(
              line.action,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.caption,
                fontWeight: AppType.wSemiBold,
                color: AppColors.accentText,
              ),
            ),
            const Icon(
              Icons.chevron_right,
              size: 16,
              color: AppColors.accentText,
            ),
          ],
        ],
      ),
    );

    if (line.action.isEmpty) return row;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () => onOpen(line.tab),
        borderRadius: const BorderRadius.all(Radius.circular(14)),
        child: row,
      ),
    );
  }
}

/* ── 줄을 정하는 규칙 ─────────────────────────────────

   개편 전과 같다. 바뀐 것은 `due` 가 붙은 것뿐이다. */

List<_Line> _linesOf(MyApplication app) => [
  _aptitudeLine(app),
  _scheduleLine(app),
  _interviewLine(app),
];

_Line _aptitudeLine(MyApplication app) {
  if (app.aptitudes.isEmpty) {
    return const _Line(
      tab: ApplicantTab.aptitude,
      label: '인적성 검사',
      state: '아직 없어요',
      action: '',
    );
  }
  // 낸 것(`done`)도 내려온다 — **끝난 것을 안 보여 주면 "완료"와 "아직 안
  // 잡힘"이 같은 화면이 된다**
  // 탭이 여는 것과 **같은 세션**을 본다 (pickLink) — 다르면 홈이
  // 「3일 남음」이라 하고 탭은 「기한이 지났습니다」를 띄운다
  final first = pickLink(app.aptitudes)!;
  if (first.status == 'done') {
    return const _Line(
      tab: ApplicantTab.aptitude,
      label: '인적성 검사',
      state: '제출했어요',
      action: '',
      tone: _Tone.done,
    );
  }
  return _Line(
    tab: ApplicantTab.aptitude,
    label: '인적성 검사',
    state: '아직 안 하셨어요',
    action: '하기',
    tone: _Tone.todo,
    due: _dueOf(first.expiresAt),
  );
}

_Line _scheduleLine(MyApplication app) {
  if (app.schedules.isEmpty) {
    return const _Line(
      tab: ApplicantTab.schedule,
      label: '면접 시간',
      state: '아직 없어요',
      action: '',
    );
  }
  // 일정만 `confirmed` 도 온다 — 확정 뒤에도 "언제로 잡혔는지" 볼 일이 있다
  final first = pickLink(app.schedules)!;
  final fixed = first.status == 'confirmed';
  return _Line(
    tab: ApplicantTab.schedule,
    label: '면접 시간',
    state: fixed ? '확정됐어요' : '후보 중에서 골라 주세요',
    action: fixed ? '보기' : '고르기',
    tone: fixed ? _Tone.done : _Tone.todo,
    due: fixed ? null : _dueOf(first.expiresAt),
  );
}

_Line _interviewLine(MyApplication app) {
  if (app.interviews.isEmpty) {
    /* **AI 면접은 자동으로 안 생긴다** — `InterviewSession` 은 담당자가 발급할
       때만 만들어져(screening._after_pass 에 없다) 이 상태가 길다. 빈 줄로
       두지 않고 언제 생기는지를 적는다. */
    return const _Line(
      tab: ApplicantTab.interview,
      label: 'AI 면접',
      state: '면접 시간이 잡히면 알려드려요',
      action: '',
    );
  }
  // 탭이 여는 것과 같은 세션을 본다 (pickLink)
  final next = pickLink(app.interviews)!;
  if (next.status == 'done') {
    return const _Line(
      tab: ApplicantTab.interview,
      label: 'AI 면접',
      state: '완료했어요',
      // 끝난 면접은 다시 들어갈 수 없다 — 문을 그리지 않는다
      action: '',
      tone: _Tone.done,
    );
  }
  final going = next.status == 'in_progress';
  return _Line(
    tab: ApplicantTab.interview,
    label: 'AI 면접',
    state: going ? '진행 중이에요' : '아직 시작하지 않았어요',
    action: going ? '이어서' : '보기',
    tone: _Tone.todo,
    due: _dueOf(next.expiresAt),
  );
}
