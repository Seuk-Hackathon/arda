/// 지원자 내 정보 — 이름·이메일 · 지원 현황 · 로그아웃 (2026-09-08).
///
/// 탭 이름은 2026-09-15 에 '더보기' 에서 바꿨다. 파일·클래스 이름은 그대로
/// 두었다 — 셸이 참조하는 이름이라 바꾸면 한 화면 고치는 일이 아니게 된다.
///
/// 담당자 더보기([MoreScreen])와 다른 화면이다: 설정할 것이 거의 없다.
/// 비밀번호도(생년월일이다), 알림 설정도, 권한도 없다.
///
/// **여기 있는 것이 지원자가 아는 자기 정보의 전부다.** 서버가 지원자에게
/// 주는 것은 이름·이메일·공고·단계·지원일뿐이고(ADR-0031), 평가도 담당자
/// 이름도 불합격 사유도 내려오지 않는다.
///
/// 셸이 이미 받아 둔 것을 그린다 — 여기서 서버를 다시 부르지 않는다.
///
/// ## 2026-09-15 개편
///
/// - **프로필이 주인공.** 84px 아바타와 24px 이름 — 그 전에는 이름이 목록의
///   한 줄이었다
/// - 지원 목록을 통째로 싣던 것을 **숫자 셋**(낸 지원·할 일·합격)으로 줄였다.
///   자세한 것은 홈이 그린다
/// - 흩어져 있던 줄들을 **계정 · 이 앱** 두 묶음으로 나눴다
/// - **비밀번호 변경 자리를 만들어 두고 잠갔다.** 지원자에게는 비밀번호가
///   없다(로그인이 생년월일이고 `password_hash` 는 담당자 테이블에만 있다).
///   흐린 줄만 두면 고장인지 아직인지 구별이 안 돼서 **이유를 글자로** 적는다
/// - 로그아웃을 **맨 아래로.** 가운데 외곽선 버튼이라 실수로 누르기 쉬웠다
library;

import 'package:flutter/material.dart';

import '../models/applicant_me.dart';
import '../theme/tokens.dart';

class ApplicantMoreScreen extends StatelessWidget {
  const ApplicantMoreScreen({
    super.key,
    required this.me,
    required this.onLeave,
  });

  final ApplicantMe me;

  /// 로그아웃. 셸이 토큰을 지우고 로그인 화면으로 보낸다
  final Future<void> Function() onLeave;

  @override
  Widget build(BuildContext context) {
    final apps = me.applications;
    final todo = apps.where(_hasTodo).length;
    final won = apps.where((a) => a.stageLabel == '최종 합격').length;

    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpace.s4,
        AppSpace.s3,
        AppSpace.s4,
        AppSpace.s5,
      ),
      children: [
        _Profile(me: me),
        const SizedBox(height: AppSpace.s5),

        Row(
          children: [
            _Stat(n: apps.length, label: '낸 지원'),
            const SizedBox(width: AppSpace.s2),
            _Stat(n: todo, label: '할 일', tone: AppColors.accentText),
            const SizedBox(width: AppSpace.s2),
            _Stat(n: won, label: '합격', tone: AppColors.okText),
          ],
        ),
        const SizedBox(height: AppSpace.s5),

        const _GroupName('계정'),
        const SizedBox(height: AppSpace.s2),
        _Group(
          children: [
            // **아직 안 되는 것.** 이유를 글자로 적는다 — 흐린 줄만 두면
            // 고장인지 아직인지 구별이 안 된다
            const _Row(
              icon: Icons.lock_outline,
              title: '비밀번호 변경',
              sub: '지금은 생년월일로 로그인해요',
              trailing: '준비 중',
            ),
          ],
        ),
        const SizedBox(height: AppSpace.s5),

        const _GroupName('이 앱'),
        const SizedBox(height: AppSpace.s2),
        _Group(
          children: [
            _Row(
              icon: Icons.logout,
              title: '로그아웃',
              danger: true,
              onTap: onLeave,
            ),
          ],
        ),
        const SizedBox(height: AppSpace.s4),

        const Center(
          child: Text(
            'Arda 0.1.0',
            style: TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: 11,
              color: AppColors.textSub,
            ),
          ),
        ),
      ],
    );
  }

  /// 아직 할 일이 남았는가. 홈의 규칙과 같다 — 낼 것이 있거나 고를 것이 있다
  static bool _hasTodo(MyApplication a) {
    final aptitude = a.aptitudes.isNotEmpty && a.aptitudes.first.status != 'done';
    final schedule =
        a.schedules.isNotEmpty && a.schedules.first.status != 'confirmed';
    final interview = a.interviews.any((i) => i.status != 'done');
    return aptitude || schedule || interview;
  }
}

/// 이름이 목록의 한 줄이 아니라 화면의 머리다
class _Profile extends StatelessWidget {
  const _Profile({required this.me});

  final ApplicantMe me;

  @override
  Widget build(BuildContext context) {
    final initial = me.name.isEmpty ? '?' : me.name.characters.first;

    return Column(
      children: [
        Container(
          width: 84,
          height: 84,
          alignment: Alignment.center,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [Color(0xFF7DD3FC), AppColors.accent, AppColors.accentBlue],
              stops: [0, 0.46, 1],
            ),
          ),
          child: Text(
            initial,
            style: const TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: 32,
              fontWeight: FontWeight.w800,
              color: AppColors.onAccent,
            ),
          ),
        ),
        const SizedBox(height: AppSpace.s3),
        Text(
          me.name,
          style: const TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: 24,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.5,
            color: AppColors.text,
            shadows: AppTextShadow.heading,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          me.email,
          style: const TextStyle(
            fontFamily: AppType.fontFamily,
            fontSize: AppType.caption,
            color: AppColors.textSub,
          ),
        ),
      ],
    );
  }
}

/// 숫자 하나. 홈에 안 가도 상태가 읽히게 하는 값이다
class _Stat extends StatelessWidget {
  const _Stat({required this.n, required this.label, this.tone});

  final int n;
  final String label;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpace.s2,
          vertical: AppSpace.s3,
        ),
        decoration: BoxDecoration(
          borderRadius: const BorderRadius.all(Radius.circular(16)),
          border: Border.all(color: AppColors.border, width: AppShape.borderW),
          color: AppColors.bgElev,
        ),
        child: Column(
          children: [
            Text(
              '$n',
              style: TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: 22,
                fontWeight: FontWeight.w800,
                letterSpacing: -0.4,
                fontFeatures: AppType.tabularNums,
                // 0 이면 색을 쓰지 않는다 — 없는 것을 강조할 이유가 없다
                color: n > 0 ? (tone ?? AppColors.text) : AppColors.text,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: 11,
                color: AppColors.textSub,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _GroupName extends StatelessWidget {
  const _GroupName(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: AppSpace.s1),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: AppType.fontFamily,
          fontSize: 11,
          fontWeight: AppType.wSemiBold,
          letterSpacing: 0.9,
          color: AppColors.textSub,
        ),
      ),
    );
  }
}

class _Group extends StatelessWidget {
  const _Group({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: const BorderRadius.all(Radius.circular(18)),
        border: Border.all(color: AppColors.border, width: AppShape.borderW),
        color: AppColors.bgElev,
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0)
              const Divider(height: 1, color: AppColors.borderSoft),
            children[i],
          ],
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({
    required this.icon,
    required this.title,
    this.sub,
    this.trailing,
    this.danger = false,
    this.onTap,
  });

  final IconData icon;
  final String title;
  final String? sub;

  /// 오른쪽에 붙는 표시. 있으면 화살표 대신 이것이 뜬다
  final String? trailing;

  final bool danger;
  final Future<void> Function()? onTap;

  @override
  Widget build(BuildContext context) {
    // 갈 곳이 없으면 눌리지 않는다 — 눌러도 아무 일 없는 줄은 고장 같다
    final off = onTap == null;
    final fg = danger ? AppColors.danger : AppColors.text;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: off ? null : () => onTap!(),
        child: Opacity(
          opacity: off ? 0.55 : 1,
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpace.s4,
              vertical: AppSpace.s3,
            ),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  alignment: Alignment.center,
                  decoration: const BoxDecoration(
                    borderRadius: BorderRadius.all(Radius.circular(11)),
                    color: AppColors.bgSunken,
                  ),
                  child: Icon(
                    icon,
                    size: 17,
                    color: danger ? AppColors.danger : AppColors.accentText,
                  ),
                ),
                const SizedBox(width: AppSpace.s3),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: TextStyle(
                          fontFamily: AppType.fontFamily,
                          fontSize: AppType.sm,
                          fontWeight: AppType.wSemiBold,
                          color: fg,
                        ),
                      ),
                      if (sub != null)
                        Text(
                          sub!,
                          style: const TextStyle(
                            fontFamily: AppType.fontFamily,
                            fontSize: 11,
                            color: AppColors.textSub,
                          ),
                        ),
                    ],
                  ),
                ),
                if (trailing != null)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 9,
                      vertical: 3,
                    ),
                    decoration: const BoxDecoration(
                      borderRadius: BorderRadius.all(AppShape.rPill),
                      color: AppColors.bgSunken,
                    ),
                    child: Text(
                      trailing!,
                      style: const TextStyle(
                        fontFamily: AppType.fontFamily,
                        fontSize: 10,
                        fontWeight: AppType.wSemiBold,
                        color: AppColors.textSub,
                      ),
                    ),
                  )
                else if (!off)
                  const Icon(
                    Icons.chevron_right,
                    size: 20,
                    color: AppColors.neutral,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
