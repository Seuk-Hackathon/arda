"""기존 지원자 중 학력·경력·기술스택이 비어 있는 경우 이력서 파일에서 추출해 채운다.

실행: uv run python scripts/backfill_profile_fields.py [--dry-run] [--limit N]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB에 저장하지 않고 출력만")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 지원자 수 (0=전체)")
    args = parser.parse_args()

    from app.database import get_db
    from app.models import Application
    from app.agent.extractor import extract_text
    from app.agent.summarizer import _fill_structured_fields, _parse_json
    from app.agent.backends import get_summary_backend
    from sqlalchemy.orm import Session

    db: Session = next(get_db())

    backend = get_summary_backend()
    reason = backend.unavailable_reason()
    if reason:
        logger.error("백엔드 사용 불가: %s", reason)
        return

    query = db.query(Application).filter(
        (Application.education == None)  # noqa: E711
        | (Application.career_years == None)  # noqa: E711
        | (Application.skills == None)  # noqa: E711
    )
    if args.limit:
        query = query.limit(args.limit)

    apps = query.all()
    logger.info("대상 지원자 %d명", len(apps))

    filled = 0
    for app in apps:
        resume_text = None
        for f in app.files:
            if f.kind == "resume":
                resume_text = extract_text(f)
                break

        if not resume_text:
            logger.debug("이력서 파일 없음: application_id=%d", app.id)
            continue

        before = (app.education, app.career_years, app.skills)
        if args.dry_run:
            logger.info("[dry-run] application_id=%d 처리 건너뜀", app.id)
            continue

        _fill_structured_fields(db, app, backend, resume_text)
        after = (app.education, app.career_years, app.skills)
        if before != after:
            filled += 1
            logger.info(
                "application_id=%d 학력=%s 경력=%s 기술=%s",
                app.id,
                app.education,
                app.career_years,
                app.skills,
            )

    logger.info("완료: %d/%d 건 갱신", filled, len(apps))


if __name__ == "__main__":
    main()
