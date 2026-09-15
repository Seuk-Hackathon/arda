/// 더보기 (더보기 탭) — 앱 UI 초안(2026-09-01) 조각 11.
///
/// 웹 사이드바 중 탭 5칸에 못 들어간 것이 여기로 모인다.
/// 사이드바 하단의 프로필 자리도 이 화면이 받는다.
///
/// **'평가 현황' 은 뺐다 (2026-09-15).** 웹에서 같이 지웠다 — 평가는 지원자
/// 상세에서 남기고, 같은 일을 하는 자리가 둘이면 어느 쪽이 진짜인지 갈린다.
/// 그래서 지금 여기 남은 것은 설정 · 알림 · 로그아웃뿐이다.
///
/// 05-design 설정 절: "**사이드바 하단 프로필은 표시 전용** — 로그인한 사용자의
/// 이름·역할 라벨·이니셜 아바타를 실데이터로 그린다. **클릭 진입은 두지 않는다**:
/// 설정은 내비에 이미 항목이 있어 두 번째 진입점이 필요 없다."
/// → 프로필 카드는 누를 수 없다. 사진도 없다(users 에 사진 컬럼이 없다).
///
/// **'단계 이력' 은 뺐다 (2026-09-03).** 누를 곳이 없는 죽은 줄이었다 — 단계
/// 이력은 지원자 상세에서 *그 사람 것*으로 들어가고, 전체를 모아 보는 화면은
/// 웹에도 없다.
library;

import 'package:flutter/material.dart';

import '../data/mock_data.dart';
import '../auth/current_user.dart';
import '../auth/logout.dart';
import '../models/app_user.dart';
import '../routes.dart';
import '../theme/tokens.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key, this.user});

  final AppUser? user;

  @override
  Widget build(BuildContext context) {
    // 로그인한 사람이 우선. 아직 못 받았으면(테스트·개발 중 직접 띄운 경우)
    // 목데이터로 그린다 — 프로필 카드가 통째로 비면 화면이 깨져 보인다
    final me = user ?? CurrentUserScope.of(context) ?? mockUser;

    return ListView(
      padding: const EdgeInsets.all(AppSpace.s4),
      children: [
        _Profile(user: me),
        const SizedBox(height: AppSpace.s4),
        // 「평가 현황」이 여기 있었다 (배지 딸린 첫 묶음). 2026-09-15 에
        // 웹과 함께 지웠다 — 평가는 지원자 상세에서 남긴다.
        _Group(
          items: [
            _Item(
              icon: Icons.settings_outlined,
              label: '설정',
              onTap: () => Navigator.pushNamed(context, Routes.settings),
            ),
            const _Item(
              icon: Icons.notifications_none,
              label: '알림',
              trailing: '켬',
            ),
          ],
        ),
        const SizedBox(height: AppSpace.s4),
        _Group(
          items: [
            _Item(
              icon: Icons.logout,
              label: '로그아웃',
              exits: true,
              onTap: () => logout(context),
            ),
          ],
        ),
        const SizedBox(height: AppSpace.s4),
        const _Version(),
      ],
    );
  }
}

/// 프로필 — **표시 전용**. 누를 수 없다(05-design 설정 절).
class _Profile extends StatelessWidget {
  const _Profile({required this.user});

  final AppUser user;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpace.s4),
      decoration: BoxDecoration(
        color: AppColors.bgElev,
        borderRadius: AppShape.card,
        border: Border.all(color: AppColors.border, width: AppShape.borderW),
        boxShadow: AppShadow.card,
      ),
      child: Row(
        children: [
          // 사진 대신 이니셜 — users 테이블에 사진 컬럼이 없다
          Container(
            width: 48,
            height: 48,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: AppColors.sidebarBg,
              shape: BoxShape.circle,
              border: Border.all(
                color: AppColors.sidebarLine,
                width: AppShape.borderW,
              ),
            ),
            child: Text(
              user.initial,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.h2,
                fontWeight: FontWeight.w700,
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
                  user.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.h2,
                    fontWeight: FontWeight.w700,
                    color: AppColors.text,
                    shadows: AppTextShadow.heading,
                  ),
                ),
                const SizedBox(height: AppSpace.s1),
                Text(
                  '${user.role.label} · ${user.email}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.sm,
                    color: AppColors.textSub,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Group extends StatelessWidget {
  const _Group({required this.items});

  final List<_Item> items;

  @override
  Widget build(BuildContext context) {
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppColors.bgElev,
        borderRadius: AppShape.card,
        border: Border.all(color: AppColors.border, width: AppShape.borderW),
        boxShadow: AppShadow.card,
      ),
      child: Column(
        children: [
          for (var i = 0; i < items.length; i++)
            DecoratedBox(
              decoration: BoxDecoration(
                border: i == 0
                    ? null
                    : const Border(
                        top: BorderSide(
                          color: AppColors.borderSoft,
                          width: AppShape.borderW,
                        ),
                      ),
              ),
              child: items[i],
            ),
        ],
      ),
    );
  }
}

/// 목록 한 줄 — 아이콘 · 라벨 · 값 · 화살표.
class _Item extends StatelessWidget {
  const _Item({
    required this.icon,
    required this.label,
    this.trailing,
    this.exits = false,
    this.onTap,
  });

  final IconData icon;
  final String label;

  /// 오른쪽에 붙는 현재 값 (예: 알림 "켬")
  final String? trailing;

  /// 로그아웃처럼 **더 들어가지 않고 나가는** 항목 — 오른쪽 화살표를 두지 않는다.
  ///
  /// 예전에는 적갈로도 칠했는데 무채로 되돌렸다(2026-09-02): 웹은 로그아웃을
  /// 평범한 버튼으로 두고, §1 은 색을 판단(합격·불합격·실패)에만 쓴다.
  /// 나가는 것은 판단이 아니다.
  final bool exits;

  final VoidCallback? onTap;

  /// 누를 곳이 생긴 항목만 연결한다. 알림은 아직 화면이 없다

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        highlightColor: AppColors.bgSunken,
        splashColor: AppColors.bgSunken,
        child: Container(
          // §9 터치 타깃 — 목록 항목은 Material 내비 항목과 같은 높이로 둔다
          height: 56,
          padding: const EdgeInsets.symmetric(horizontal: AppSpace.s4),
          child: Row(
            children: [
              Icon(icon, size: 22, color: AppColors.textSub),
              const SizedBox(width: AppSpace.s3),
              Expanded(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.body,
                    color: AppColors.text,
                  ),
                ),
              ),
              if (trailing != null)
                Text(
                  trailing!,
                  style: const TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.sm,
                    color: AppColors.textSub,
                  ),
                ),
              if (!exits) ...[
                const SizedBox(width: AppSpace.s2),
                const Icon(
                  Icons.chevron_right,
                  size: 20,
                  color: AppColors.textSub,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _Version extends StatelessWidget {
  const _Version();

  @override
  Widget build(BuildContext context) {
    return const Text(
      // pubspec 의 version 과 맞춰 둔다. API 연동 때 package_info 로 읽는다
      'Arda 0.1.0',
      textAlign: TextAlign.center,
      style: TextStyle(
        fontFamily: AppType.fontFamily,
        fontSize: AppType.caption,
        fontFeatures: AppType.tabularNums,
        color: AppColors.textSub,
      ),
    );
  }
}
