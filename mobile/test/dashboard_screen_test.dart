// 대시보드 — 조각 3~9. 05-design 이 값을 못 박은 곳은 전부 그 값으로 검사한다.

import 'package:arda/data/mock_data.dart';
import 'package:arda/models/stage.dart';
import 'package:arda/auth/current_user.dart';
import 'package:arda/screens/dashboard_screen.dart';
import 'package:arda/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fake_repos.dart';

/// 2026-09-01 은 화요일 — 목데이터가 면접 2건을 두는 날
final aDay = DateTime(2026, 9, 1);

/// 큐 8 4단계로 서버에서 받아 온다 — 가짜가 목데이터를 그대로 준다.
/// 내 id 를 알아야 "내 리뷰 대기" 를 묻기 시작하므로 로그인한 사람도 넣는다.
Widget host({DateTime? today}) => CurrentUserScope(
  notifier: CurrentUser(mockUser),
  child: MaterialApp(
    home: Scaffold(
      body: DashboardScreen(
        today: today ?? aDay,
        repository: FakeDashboardRepository(),
      ),
    ),
  ),
);

/// 첫 카드. **'화면 안의 첫 Container' 로 집던 것을 키로 바꿨다** (2026-09-15) —
/// 그 자리를 히어로가 차지하면서 카드가 아닌 것을 보고 있었다
Finder get card => find.byKey(dashboardCardKey).first;

BoxDecoration decorationOf(WidgetTester tester) =>
    tester.widget<Container>(card).decoration! as BoxDecoration;

/// 진행중 공고 카드까지 내려간다 — 지원자 현황 목록 때문에 화면 밖으로 밀렸다.
Future<void> scrollToPostings(WidgetTester tester) async {
  await tester.dragUntilVisible(
    find.text('공고별 현황'),
    find.byType(Scrollable).first,
    const Offset(0, -300),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('조각 3 — 카드 자리', () {
    testWidgets('흰 바탕 · radius 8 · 1px 테두리 · 카드 그림자 (§4)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();
      final deco = decorationOf(tester);

      expect(deco.color, AppColors.bgElev);
      expect(deco.borderRadius, AppShape.card);
      expect((deco.border! as Border).top.color, AppColors.border);
      expect((deco.border! as Border).top.width, AppShape.borderW);
      expect(deco.boxShadow, AppShadow.card);
    });

    testWidgets('화면 여백 --sp-4, 카드 안쪽 여백도 --sp-4 (§3 · §0.5)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final screen = tester.getRect(find.byType(DashboardScreen));
      final box = tester.getRect(card);
      expect(box.left - screen.left, AppSpace.s4);
      expect(screen.right - box.right, AppSpace.s4);
      // **위 여백은 첫 카드가 아니라 인사말이 받는다** (2026-09-15) —
      // 카드 위에 인사말과 오늘 히어로가 생겼다. 화면 여백 자체는 그대로 16 이다
      // 인사말 문구는 시간대마다 바뀌므로 이름 줄로 집는다
      final hello = tester.getRect(find.text('${mockUser.name} 님'));
      expect(hello.top - screen.top, lessThanOrEqualTo(AppSpace.s4 + 24));

      expect(
        tester.widget<Container>(card).padding,
        const EdgeInsets.all(AppSpace.s4),
      );
    });

    testWidgets('높이는 내용이 정한다 — 잠정 높이를 걷어냈다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      // 카드 높이 = 내용 높이 + 안쪽 여백 위아래 + 테두리 위아래.
      // 고정 높이가 남아 있으면 이 등식이 깨진다
      final content = tester.getSize(
        find.descendant(of: card, matching: find.byType(Column)).first,
      );
      expect(
        tester.getSize(card).height,
        moreOrLessEquals(
          content.height + (AppSpace.s4 + AppShape.borderW) * 2,
          epsilon: 0.5,
        ),
      );
    });
  });

  group('조각 4 — 카드 제목 줄', () {
    testWidgets('제목은 h2 · w700 · 제목 그림자 (§2 · §0.5)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final title = tester.widget<Text>(find.text('오늘 면접'));
      expect(title.style!.fontSize, AppType.h2);
      expect(title.style!.fontWeight, FontWeight.w700);
      expect(title.style!.color, AppColors.text);
      expect(title.style!.shadows, AppTextShadow.heading);
    });

    testWidgets('메타는 "날짜 · N건" — 날짜는 §2 표기, 일정은 명이 아니라 건', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();
      expect(find.text('2026.09.01 · 2건'), findsOneWidget);
    });

    testWidgets('메타는 --font-num + tabular-nums, 그림자 없음 (§2)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final meta = tester.widget<Text>(find.text('2026.09.01 · 2건'));
      expect(meta.style!.fontSize, AppType.num);
      expect(meta.style!.fontFeatures, AppType.tabularNums);
      expect(meta.style!.color, AppColors.textSub);
      expect(meta.style!.shadows, isNull);
    });
  });

  group('조각 5 — 면접 행', () {
    testWidgets('오늘 확정된 면접이 시각 순서대로 나온다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      expect(find.text('14:00'), findsOneWidget);
      expect(find.text('16:30'), findsOneWidget);
      expect(
        tester.getRect(find.text('14:00')).top,
        lessThan(tester.getRect(find.text('16:30')).top),
      );
    });

    testWidgets('행에 지원자 이름과 공고가 함께 있다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      for (final interview in mockInterviewsOn(aDay)) {
        expect(
          find.descendant(
            of: card,
            matching: find.text(interview.applicantName),
          ),
          findsOneWidget,
        );
      }
      // 두 사람 모두 같은 공고라 제목은 2번. 진행중 공고 블록에도 같은 제목이
      // 있으므로 '오늘 면접' 카드 안으로 범위를 좁혀서 센다
      expect(
        find.descendant(of: card, matching: find.text('백엔드 개발자 (신입)')),
        findsNWidgets(2),
      );
    });

    testWidgets('시각은 --font-num + tabular + 잎초록 (§1 · §2)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final time = tester.widget<Text>(find.text('14:00'));
      expect(time.style!.fontSize, AppType.num);
      expect(time.style!.fontFeatures, AppType.tabularNums);
      expect(time.style!.color, AppColors.leaf);
      // §2: 작은 글씨엔 그림자 금지
      expect(time.style!.shadows, isNull);
    });

    testWidgets('이름은 본문 크기 w600, 공고는 캡션 크기 보조색', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();
      final first = mockInterviewsOn(aDay).first;

      final name = tester.widget<Text>(
        find.descendant(of: card, matching: find.text(first.applicantName)),
      );
      expect(name.style!.fontSize, AppType.body);
      expect(name.style!.fontWeight, AppType.wSemiBold);

      final posting = tester.widget<Text>(
        find
            .descendant(of: card, matching: find.text(first.postingTitle))
            .first,
      );
      expect(posting.style!.fontSize, AppType.caption);
      expect(posting.style!.color, AppColors.textSub);
    });

    testWidgets('긴 이름은 한 줄 말줄임 — 시간표가 무너지지 않는다 (§7)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final long = mockInterviewsOn(aDay)
          .map((i) => i.applicantName)
          .reduce((a, b) => a.length >= b.length ? a : b);
      expect(long.length, greaterThan(20), reason: '긴 이름 케이스가 목데이터에 있어야 한다');

      final text = tester.widget<Text>(
        find.descendant(of: card, matching: find.text(long)).first,
      );
      expect(text.maxLines, 1);
      expect(text.overflow, TextOverflow.ellipsis);

      // 두 행 높이가 같아야 한다 — 긴 이름이 줄을 늘리면 어긋난다.
      // **위치 번호가 아니라 키로 집는다** — 히어로가 생기며 번호가 밀렸다
      final rows = find.byKey(interviewRowKey);
      expect(rows.evaluate().length, greaterThanOrEqualTo(2));
      final h1 = tester.getSize(rows.at(0)).height;
      final h2 = tester.getSize(rows.at(1)).height;
      expect(h1, h2);
    });

    testWidgets('행 사이 실선은 --border-soft 1px (§4)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final row = tester.widget<Container>(find.byKey(interviewRowKey).first);
      final border = (row.decoration! as BoxDecoration).border! as Border;
      expect(border.top.color, AppColors.borderSoft);
      expect(border.top.width, AppShape.borderW);
    });
  });

  group('조각 6 — 캘린더 링크', () {
    testWidgets('링크 글자는 --leaf · sm · w600, 그림자 없음 (§1 · §2)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final link = tester.widget<Text>(find.text('캘린더 →'));
      expect(link.style!.color, AppColors.leaf);
      expect(link.style!.fontSize, AppType.sm);
      expect(link.style!.fontWeight, AppType.wSemiBold);
      expect(link.style!.shadows, isNull);
    });

    testWidgets('누를 자리가 44×44 이상이다 (§9)', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final tapArea = tester.getSize(
        find
            .ancestor(of: find.text('캘린더 →'), matching: find.byType(InkWell))
            .first,
      );
      expect(tapArea.height, greaterThanOrEqualTo(AppLayout.minTouchTarget));
      expect(tapArea.width, greaterThanOrEqualTo(AppLayout.minTouchTarget));
    });

    testWidgets('오른쪽 끝이 카드 안쪽 선에 맞는다 — 위 날짜와 같은 세로선', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      final link = tester.getRect(find.text('캘린더 →'));
      final meta = tester.getRect(find.text('2026.09.01 · 2건'));
      expect(link.right, moreOrLessEquals(meta.right, epsilon: 0.5));
    });

    testWidgets('누르면 콜백이 온다', (tester) async {
      var opened = false;
      await tester.pumpWidget(
        CurrentUserScope(
          notifier: CurrentUser(mockUser),
          child: MaterialApp(
            home: Scaffold(
              body: DashboardScreen(
                today: aDay,
                repository: FakeDashboardRepository(),
                onOpenCalendar: () => opened = true,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('캘린더 →'));
      expect(opened, isTrue);
    });
  });

  // 「조각 7 — 내 리뷰 대기」 묶음이 여기 있었다. 2026-09-15 에 평가 현황을
  // 지우면서 그 카드가 화면에서 사라져 같이 뺐다.

  // 2026-09-07 — 지원자 이름 목록(옛 조각 8)과 면접 행 일정 칩 검사를 걷었다.
  // 웹 대시보드 개편을 따라 그 블록이 화면에서 사라졌다. 사람을 훑는 일은
  // '지원자' 탭이 하고, 대시보드는 "지금 어디에 몇 명"에만 답한다.
  group('전체 현황', () {
    testWidgets('심사 중 세 단계는 막대가 있고, 합격·불합격은 없다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      // 합격·불합격은 한번 되면 영원히 쌓이는 누적값이라 심사 중 세 칸과
      // 같은 자를 쓸 수 없다 — 막대 대신 '누적'이라 적는다
      expect(find.text('누적'), findsNWidgets(2));
    });

    testWidgets('다섯 단계가 모두 숫자로 나온다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      for (final stage in Stage.values) {
        expect(
          find.text(stage.label),
          findsWidgets,
          reason: '${stage.label} 칸이 없다 — 다섯이 다 보여야 합이 읽힌다',
        );
      }
    });

    testWidgets('단계별 지원자 이름을 늘어놓지 않는다 — 그건 지원자 탭이 한다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();

      // '오늘 면접'은 이름을 적는 게 맞다 — 그 블록의 목적이 누구를 언제
      // 만나는지이기 때문이다. 걷어낸 것은 단계별로 늘어놓던 이름 목록이다.
      final onToday = {for (final i in mockInterviewsOn(aDay)) i.applicantName};
      final others = mockApplicants.where((a) => !onToday.contains(a.name));
      expect(others, isNotEmpty, reason: '검사할 대상이 없으면 통과가 무의미하다');

      for (final a in others) {
        expect(
          find.text(a.name),
          findsNothing,
          reason: '대시보드에 ${a.name} 이름이 남아 있다',
        );
      }
    });
  });

  group('공고별 현황', () {
    testWidgets('진행중 공고만 나온다 — 마감은 없다', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();
      await scrollToPostings(tester);

      for (final p in mockOpenPostings) {
        expect(find.text(p.title), findsWidgets);
      }
      for (final p in mockPostings.where(
        (p) => !mockOpenPostings.contains(p),
      )) {
        expect(find.text(p.title), findsNothing, reason: '마감된 공고');
      }
    });

    testWidgets('행 오른쪽 끝은 비워 둔다 — 아르 버튼 자리', (tester) async {
      await tester.pumpWidget(host());
      await tester.pumpAndSettle();
      await scrollToPostings(tester);

      final screen = tester.getRect(find.byType(DashboardScreen));
      final meta = tester.getRect(find.textContaining('마감 D-').first);
      expect(screen.right - meta.right, greaterThan(60));
    });
  });
}
