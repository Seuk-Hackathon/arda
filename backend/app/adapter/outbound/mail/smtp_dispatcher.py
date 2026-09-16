"""SMTP 로 바로 보내는 어댑터 — n8n 없이 도는 경로 (2026-09-16).

[ADR-0031](../../../../../docs/03_decision/0031-aws-최소화.md) 의 "워커는 SMTP 20줄
비상 폴백만" 을 어댑터로 만든 것이다. `MAIL_DISPATCH=smtp` 로 두면 정상 경로가
되고, 그 외에는 `mail.publish` 가 **n8n 이 실패했을 때만** 이쪽으로 물러선다.

**큐가 아니라 그 자리에서 보낸다.** 다른 어댑터는 발행만 하고 끝나지만 여기는
SMTP 응답까지 기다린다 — 폴백은 "나중에 누가 처리해 주겠지" 가 성립하지 않는
자리라(그 누군가가 죽어서 폴백을 타는 것이다) 여기서 끝을 봐야 한다.
"""

from __future__ import annotations

import logging

from app.ports.output.mail_dispatcher_port import MailDispatcher

logger = logging.getLogger(__name__)


class SmtpMailDispatcher(MailDispatcher):
    def publish(self, email_log_id: int) -> None:
        from app.shared import mail_smtp

        if not mail_smtp.send_log_id(email_log_id):
            raise RuntimeError(f"SMTP 발송 실패 email_log_id={email_log_id}")
