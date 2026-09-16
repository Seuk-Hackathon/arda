"""메일 발송 어댑터 (ADR-0035 Phase 3f · 2026-09-16 SMTP 추가).

SQS 워커 경로, n8n 웹훅 경로, 그리고 **n8n 이 멈췄을 때 물러설 SMTP 경로**.
"""

from app.adapter.outbound.mail.n8n_dispatcher import N8nMailDispatcher
from app.adapter.outbound.mail.smtp_dispatcher import SmtpMailDispatcher
from app.adapter.outbound.mail.sqs_dispatcher import SqsMailDispatcher

__all__ = ["N8nMailDispatcher", "SmtpMailDispatcher", "SqsMailDispatcher"]
