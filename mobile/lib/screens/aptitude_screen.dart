/// 인적성 검사 — 지원자용 (2026-09-08, 2026-09-15 개편).
///
/// 문항도 척도 라벨도 **서버가 준 것을 그대로** 쓴다. 앱이 문장을 지어내면
/// 지원자가 실제로 본 문장과 서버가 스냅샷해 둔 문장이 갈린다.
///
/// **전 문항 필수, 재제출 없다**(서버가 막는다). 그래서 화면이 먼저 막는다.
///
/// ## 2026-09-15 — 한 번에 한 문항씩
///
/// 그 전에는 열 문항이 한 화면에 쭉 쌓여 있었다. 폰에서 계속 스크롤하며
/// 풀어야 했고, 몇 개 남았는지는 맨 아래 버튼에 가서야 보였다.
///
/// 지금은 **한 화면에 문항 하나**다. 21px 문장 하나와 선택지 다섯이면 스크롤이
/// 없다. 위 막대가 어디쯤인지 늘 말한다.
///
/// **시작 판을 먼저 둔다.** 「한 번만 낼 수 있어요」를 다 풀고 나서 알면 늦다.
/// 「3분」은 기대치를 먼저 주는 값이다 — 없으면 시작을 미룬다.
///
/// 답은 **기기 안에만** 있다. 서버는 제출 한 번에 전부 받는 구조라
/// (`POST /public/aptitude/{token}/submit`) 중간 저장 경로가 없다. 그래서
/// 화면도 "이 기기에 저장됨"이라고만 말한다 — 앱을 지웠다 깔면 사라진다.
library;

import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../data/applicant_portal_repository.dart';
import '../models/applicant_extra.dart';
import '../theme/tokens.dart';
import 'applicant_shell.dart';

class AptitudeScreen extends StatefulWidget {
  const AptitudeScreen({super.key, required this.token, this.portal});

  /// 없으면 담당자가 아직 안 보낸 것이다
  final String? token;

  final ApplicantPortalRepository? portal;

  @override
  State<AptitudeScreen> createState() => _AptitudeScreenState();
}

class _AptitudeScreenState extends State<AptitudeScreen> {
  late final ApplicantPortalRepository _portal =
      widget.portal ?? ApplicantPortalRepository();

  AptitudePublic? _data;
  String? _error;
  bool _sending = false;

  /// 시작 판을 지났는가. 처음에는 false 라 안내가 먼저 뜬다
  bool _started = false;

  /// 지금 보고 있는 문항 번호 (0부터)
  int _at = 0;

  /// 문항 키 → 고른 점수
  final _answers = <String, int>{};

  @override
  void initState() {
    super.initState();
    if (widget.token != null) _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final data = await _portal.aptitude(widget.token!);
      if (!mounted) return;
      setState(() => _data = data);
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    }
  }

  int get _left => (_data?.questions.length ?? 0) - _answers.length;

  Future<void> _submit() async {
    if (_sending || _left != 0) return;
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final next = await _portal.submitAptitude(widget.token!, _answers);
      if (!mounted) return;
      setState(() {
        _data = next;
        _sending = false;
      });
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _sending = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.token == null) {
      return const ApplicantMissing(what: '인적성 검사');
    }
    final data = _data;
    if (data == null) {
      return _error == null
          ? const Center(child: CircularProgressIndicator())
          : _Failed(message: _error!, onRetry: _load);
    }

    if (data.status != AptitudeStatus.pending) {
      return _Closed(status: data.status);
    }

    if (!_started) {
      return _Intro(
        count: data.questions.length,
        expiresAt: data.expiresAt,
        onStart: () => setState(() => _started = true),
      );
    }

    return _Asking(
      data: data,
      at: _at,
      answers: _answers,
      sending: _sending,
      error: _error,
      onPick: (key, v) => setState(() => _answers[key] = v),
      onBack: _at == 0 ? null : () => setState(() => _at -= 1),
      onNext: () {
        if (_at + 1 < data.questions.length) {
          setState(() => _at += 1);
        } else {
          _submit();
        }
      },
    );
  }
}

/// 시작 판. **「한 번만 낼 수 있어요」를 시작 전에** 말한다
class _Intro extends StatelessWidget {
  const _Intro({
    required this.count,
    required this.expiresAt,
    required this.onStart,
  });

  final int count;
  final DateTime? expiresAt;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final days = expiresAt == null
        ? null
        : (expiresAt!.difference(DateTime.now()).inHours / 24).ceil();

    return ListView(
      padding: const EdgeInsets.all(AppSpace.s4),
      children: [
        Container(
          padding: const EdgeInsets.all(AppSpace.s5),
          decoration: BoxDecoration(
            borderRadius: const BorderRadius.all(Radius.circular(24)),
            border: Border.all(color: AppColors.accent.withValues(alpha: 0.30)),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                AppColors.accent.withValues(alpha: 0.18),
                AppColors.accentBlue.withValues(alpha: 0.08),
                AppColors.accentViolet.withValues(alpha: 0.12),
              ],
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '먼저 하실 일',
                style: TextStyle(
                  fontFamily: AppType.fontFamily,
                  fontSize: 11,
                  fontWeight: AppType.wSemiBold,
                  letterSpacing: 1.1,
                  color: AppColors.accentText,
                ),
              ),
              const SizedBox(height: AppSpace.s3),
              Text(
                '$count문항,\n3분이면 끝나요',
                style: const TextStyle(
                  fontFamily: AppType.fontFamily,
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.6,
                  height: 1.25,
                  color: AppColors.text,
                ),
              ),
              const SizedBox(height: AppSpace.s2),
              Text(
                '정답이 없는 검사예요. 편하게 고르시면 돼요.',
                style: TextStyle(
                  fontFamily: AppType.fontFamily,
                  fontSize: AppType.caption,
                  color: AppColors.text.withValues(alpha: 0.74),
                ),
              ),
              const SizedBox(height: AppSpace.s4),
              Row(
                children: [
                  _MetaBox(label: '문항', value: '$count개'),
                  const SizedBox(width: AppSpace.s2),
                  const _MetaBox(label: '예상', value: '3분'),
                  if (days != null) ...[
                    const SizedBox(width: AppSpace.s2),
                    _MetaBox(label: '마감', value: '$days일'),
                  ],
                ],
              ),
              const SizedBox(height: AppSpace.s4),
              _Filled(label: '시작하기', onTap: onStart),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.s4),

        // **다 풀고 나서 알면 늦는 것들**을 여기서 먼저 말한다
        const _Rule(no: 1, bold: '한 번만 낼 수 있어요.', rest: ' 낸 뒤에는 고칠 수 없으니 천천히 골라 주세요.'),
        SizedBox(height: AppSpace.s3),
        const _Rule(no: 2, bold: '전부 답해야 제출돼요.', rest: ' 안 고른 게 있으면 알려드릴게요.'),
        SizedBox(height: AppSpace.s3),
        const _Rule(no: 3, bold: '점수로 매기지 않아요.', rest: ' 서류를 볼 때 참고하는 자료예요.'),
      ],
    );
  }
}

class _MetaBox extends StatelessWidget {
  const _MetaBox({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpace.s3,
          vertical: AppSpace.s2,
        ),
        decoration: BoxDecoration(
          borderRadius: const BorderRadius.all(Radius.circular(14)),
          color: Colors.black.withValues(alpha: 0.22),
          border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: 10,
                color: AppColors.textSub,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              value,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: 15,
                fontWeight: AppType.wSemiBold,
                color: AppColors.text,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Rule extends StatelessWidget {
  const _Rule({required this.no, required this.bold, required this.rest});

  final int no;
  final String bold;
  final String rest;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 20,
          height: 20,
          margin: const EdgeInsets.only(top: 1),
          alignment: Alignment.center,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            color: AppColors.bgSunken,
          ),
          child: Text(
            '$no',
            style: const TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: 10,
              color: AppColors.accentText,
            ),
          ),
        ),
        const SizedBox(width: AppSpace.s3),
        Expanded(
          child: Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: bold,
                  style: const TextStyle(
                    fontWeight: AppType.wSemiBold,
                    color: AppColors.text,
                  ),
                ),
                TextSpan(text: rest),
              ],
            ),
            style: const TextStyle(
              fontFamily: AppType.fontFamily,
              fontSize: AppType.caption,
              height: 1.6,
              color: AppColors.textSub,
            ),
          ),
        ),
      ],
    );
  }
}

/// 한 문항. 위에 진행 막대, 아래 다음 버튼
class _Asking extends StatelessWidget {
  const _Asking({
    required this.data,
    required this.at,
    required this.answers,
    required this.sending,
    required this.error,
    required this.onPick,
    required this.onBack,
    required this.onNext,
  });

  final AptitudePublic data;
  final int at;
  final Map<String, int> answers;
  final bool sending;
  final String? error;
  final void Function(String key, int value) onPick;
  final VoidCallback? onBack;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final q = data.questions[at];
    final picked = answers[q.key];
    final total = data.questions.length;
    final last = at + 1 == total;
    final allDone = answers.length == total;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // 진행 막대 — 어디쯤인지 늘 말한다
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpace.s4,
            AppSpace.s2,
            AppSpace.s4,
            0,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ClipRRect(
                borderRadius: const BorderRadius.all(Radius.circular(3)),
                child: LinearProgressIndicator(
                  value: (at + 1) / total,
                  minHeight: 4,
                  backgroundColor: Colors.white.withValues(alpha: 0.08),
                  valueColor: const AlwaysStoppedAnimation(AppColors.accent),
                ),
              ),
              const SizedBox(height: AppSpace.s2),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  // **기기 안에만 있다**는 것을 분명히 한다 — 서버에 중간
                  // 저장 경로가 없다
                  Text(
                    answers.isEmpty ? '' : '이 기기에 저장됨',
                    style: const TextStyle(
                      fontFamily: AppType.fontFamily,
                      fontSize: 11,
                      color: AppColors.textSub,
                    ),
                  ),
                  Text(
                    '${at + 1} / $total',
                    style: const TextStyle(
                      fontFamily: AppType.fontFamily,
                      fontSize: 11,
                      fontWeight: AppType.wSemiBold,
                      color: AppColors.accentText,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),

        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              AppSpace.s4,
              AppSpace.s5,
              AppSpace.s4,
              AppSpace.s4,
            ),
            children: [
              Text(
                q.text,
                style: const TextStyle(
                  fontFamily: AppType.fontFamily,
                  fontSize: 21,
                  fontWeight: AppType.wSemiBold,
                  letterSpacing: -0.3,
                  height: 1.45,
                  color: AppColors.text,
                ),
              ),
              const SizedBox(height: AppSpace.s5),

              // 세로 5줄. **가로 눈금은 폰에서 오누름이 잦다**
              for (final e in _sortedLabels(data.likertLabels)) ...[
                _Option(
                  value: e.key,
                  label: e.value,
                  on: picked == e.key,
                  onTap: () => onPick(q.key, e.key),
                ),
                const SizedBox(height: AppSpace.s2),
              ],

              if (error != null) ...[
                const SizedBox(height: AppSpace.s2),
                _Note(text: error!, tone: AppColors.danger),
              ],
            ],
          ),
        ),

        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpace.s4,
            0,
            AppSpace.s4,
            AppSpace.s4,
          ),
          child: Row(
            children: [
              if (onBack != null) ...[
                _Back(onTap: onBack!),
                const SizedBox(width: AppSpace.s2),
              ],
              Expanded(
                child: _Filled(
                  label: sending
                      ? '보내는 중…'
                      : last
                      ? (allDone ? '제출하기' : '${total - answers.length}문항 남았어요')
                      : '다음',
                  // 마지막에서는 전부 답해야 살아난다 — 서버가 422 를 주기 전에
                  // 화면이 먼저 막는다
                  onTap: (picked == null || sending || (last && !allDone))
                      ? null
                      : onNext,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  /// 1~5 차례로. Map 순서에 기대지 않는다
  List<MapEntry<int, String>> _sortedLabels(Map<int, String> labels) {
    final list = labels.entries.toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    return list;
  }
}

class _Option extends StatelessWidget {
  const _Option({
    required this.value,
    required this.label,
    required this.on,
    required this.onTap,
  });

  final int value;
  final String label;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: on
          ? AppColors.accent.withValues(alpha: 0.10)
          : Colors.white.withValues(alpha: 0.03),
      borderRadius: const BorderRadius.all(Radius.circular(14)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpace.s4,
            vertical: AppSpace.s3,
          ),
          decoration: BoxDecoration(
            borderRadius: const BorderRadius.all(Radius.circular(14)),
            border: Border.all(
              color: on
                  ? AppColors.accent.withValues(alpha: 0.55)
                  : AppColors.border,
              width: AppShape.borderW,
            ),
          ),
          child: Row(
            children: [
              Container(
                width: 18,
                height: 18,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: on
                        ? AppColors.accent
                        : AppColors.textSub.withValues(alpha: 0.45),
                    width: 2,
                  ),
                ),
                child: on
                    ? Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          shape: BoxShape.circle,
                          color: AppColors.accent,
                        ),
                      )
                    : null,
              ),
              const SizedBox(width: AppSpace.s3),
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    fontFamily: AppType.fontFamily,
                    fontSize: AppType.sm,
                    fontWeight: on ? AppType.wSemiBold : AppType.wRegular,
                    color: on ? AppColors.accentText : AppColors.text,
                  ),
                ),
              ),
              Text(
                '$value',
                style: TextStyle(
                  fontFamily: AppType.fontFamily,
                  fontSize: 11,
                  color: AppColors.textSub.withValues(alpha: 0.5),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Back extends StatelessWidget {
  const _Back({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.bgSunken,
      borderRadius: const BorderRadius.all(Radius.circular(16)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: const SizedBox(
          width: 52,
          height: 50,
          child: Icon(
            Icons.arrow_back,
            size: 18,
            color: AppColors.textSub,
          ),
        ),
      ),
    );
  }
}

/// 흰 판 버튼. 05-design §1 — 주 동작은 흰 면이고 네온이 아니다
class _Filled extends StatelessWidget {
  const _Filled({required this.label, required this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final off = onTap == null;
    return Material(
      color: off
          ? Colors.white.withValues(alpha: 0.14)
          : AppColors.accentFill,
      borderRadius: const BorderRadius.all(Radius.circular(16)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          height: 50,
          child: Center(
            child: Text(
              label,
              style: TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.sm,
                fontWeight: AppType.wSemiBold,
                color: off
                    ? AppColors.text.withValues(alpha: 0.45)
                    : AppColors.onAccent,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Closed extends StatelessWidget {
  const _Closed({required this.status});

  final AptitudeStatus status;

  @override
  Widget build(BuildContext context) {
    final done = status == AptitudeStatus.submitted;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpace.s6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              done ? Icons.check_circle_outline : Icons.schedule,
              size: 28,
              color: done ? AppColors.okText : AppColors.neutral,
            ),
            const SizedBox(height: AppSpace.s3),
            Text(
              done
                  ? '제출했어요.\n따로 하실 일은 없어요.'
                  : '인적성 검사 기한이 지났습니다.\n담당자에게 문의해 주세요.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.sm,
                height: 1.6,
                color: done ? AppColors.textSub : AppColors.danger,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({required this.text, required this.tone});

  final String text;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpace.s3),
      decoration: BoxDecoration(
        color: AppColors.bgSunken,
        borderRadius: AppShape.ctl,
        border: Border.all(
          color: AppColors.borderSoft,
          width: AppShape.borderW,
        ),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontFamily: AppType.fontFamily,
          fontSize: AppType.sm,
          height: 1.6,
          color: tone,
        ),
      ),
    );
  }
}

class _Failed extends StatelessWidget {
  const _Failed({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpace.s5),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: AppType.fontFamily,
                fontSize: AppType.sm,
                color: AppColors.danger,
              ),
            ),
            const SizedBox(height: AppSpace.s4),
            SizedBox(
              height: AppLayout.minTouchTarget,
              child: OutlinedButton(
                onPressed: onRetry,
                child: const Text('다시 시도'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
