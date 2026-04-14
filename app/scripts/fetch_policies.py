from __future__ import annotations

import argparse
import time

from sqlalchemy import select

from app.collectors.base import CollectorError
from app.collectors.bokjiro import BokjiroCollector
from app.collectors.gov24 import Gov24Collector
from app.core.config import get_settings
from app.db.models import RawPolicyConditionItem, RawPolicyDetailItem, RawPolicyListItem
from app.db.session import SessionLocal


def existing_policy_ids(db, model, source: str) -> set[str]:
    rows = db.execute(select(model.source_policy_id).where(model.source == source).distinct()).scalars().all()
    return {row for row in rows if row}


def missing_detail_policy_ids(db, source: str, limit: int | None = None) -> list[str]:
    detail_subquery = select(RawPolicyDetailItem.source_policy_id).where(RawPolicyDetailItem.source == source).distinct()
    stmt = (
        select(RawPolicyListItem.source_policy_id)
        .where(RawPolicyListItem.source == source)
        .where(RawPolicyListItem.source_policy_id.not_in(detail_subquery))
        .distinct()
        .order_by(RawPolicyListItem.source_policy_id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return [row for row in db.execute(stmt).scalars().all() if row]


def iter_pages(start_page: int, max_pages: int) -> range | None:
    if max_pages > 0:
        return range(start_page, start_page + max_pages)
    return None


def fetch_gov24(
    start_page: int,
    max_pages: int,
    page_size: int,
    fetch_details: bool,
    fetch_conditions: bool,
    detail_mode: str,
    sleep_seconds: float,
    detail_limit: int | None,
) -> None:
    settings = get_settings()
    db = SessionLocal()
    collector = Gov24Collector(
        db=db,
        service_key=settings.gov24_service_key or "",
        base_url=settings.gov24_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )

    try:
        existing_details = existing_policy_ids(db, RawPolicyDetailItem, "gov24") if detail_mode == "missing" else set()
        fetched_detail_count = 0
        page_iter = iter_pages(start_page, max_pages)
        page = start_page

        while True:
            if page_iter is not None and page not in page_iter:
                break
            items = collector.fetch_list(page=page, per_page=page_size)
            print(f"[gov24] list page={page} fetched={len(items)}")
            if not items:
                break

            if fetch_details:
                for item in items:
                    policy_id = collector._extract_policy_id(item)
                    if not policy_id:
                        continue
                    if detail_mode == "missing" and policy_id in existing_details:
                        continue
                    if detail_limit is not None and fetched_detail_count >= detail_limit:
                        return
                    try:
                        collector.fetch_detail(policy_id)
                        existing_details.add(policy_id)
                        fetched_detail_count += 1
                        print(f"[gov24] detail policy_id={policy_id}")
                    except CollectorError as exc:
                        print(f"[gov24] detail failed policy_id={policy_id} error={exc}")
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)

            page += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        if fetch_conditions:
            existing_conditions = existing_policy_ids(db, RawPolicyConditionItem, "gov24")
            page_iter = iter_pages(start_page, max_pages)
            page = start_page
            while True:
                if page_iter is not None and page not in page_iter:
                    break
                before_count = len(existing_conditions)
                items = collector.fetch_conditions(page=page, per_page=page_size)
                for item in items:
                    policy_id = collector._extract_policy_id(item)
                    if policy_id:
                        existing_conditions.add(policy_id)
                print(f"[gov24] conditions page={page} fetched={len(items)} new_ids={len(existing_conditions) - before_count}")
                if not items:
                    break
                page += 1
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    finally:
        collector.close()
        db.close()


def fetch_bokjiro(
    start_page: int,
    max_pages: int,
    page_size: int,
    fetch_details: bool,
    detail_mode: str,
    sleep_seconds: float,
    detail_limit: int | None,
    detail_only_missing_from_db: bool,
) -> None:
    settings = get_settings()
    db = SessionLocal()
    collector = BokjiroCollector(
        db=db,
        service_key=settings.bokjiro_service_key or "",
        base_url=settings.bokjiro_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )

    try:
        if fetch_details and detail_only_missing_from_db:
            targets = missing_detail_policy_ids(db, "bokjiro", detail_limit)
            print(f"[bokjiro] db-missing detail targets={len(targets)}")
            consecutive_rate_limits = 0
            for policy_id in targets:
                try:
                    collector.fetch_detail(policy_id)
                    print(f"[bokjiro] detail policy_id={policy_id}")
                    consecutive_rate_limits = 0
                except CollectorError as exc:
                    print(f"[bokjiro] detail failed policy_id={policy_id} error={exc}")
                    error_text = str(exc).lower()
                    if "429" in error_text or "quota" in error_text:
                        consecutive_rate_limits += 1
                        if consecutive_rate_limits >= 3:
                            print("[bokjiro] stopping batch early due to repeated rate-limit responses")
                            return
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            return

        existing_details = existing_policy_ids(db, RawPolicyDetailItem, "bokjiro") if detail_mode == "missing" else set()
        fetched_detail_count = 0
        consecutive_rate_limits = 0
        page_iter = iter_pages(start_page, max_pages)
        page = start_page

        while True:
            if page_iter is not None and page not in page_iter:
                break
            items = collector.fetch_list(page=page, num_rows=page_size)
            print(f"[bokjiro] list page={page} fetched={len(items)}")
            if not items:
                break

            if fetch_details:
                for item in items:
                    policy_id = collector._extract_policy_id(item)
                    if not policy_id:
                        continue
                    if detail_mode == "missing" and policy_id in existing_details:
                        continue
                    if detail_limit is not None and fetched_detail_count >= detail_limit:
                        return
                    try:
                        collector.fetch_detail(policy_id)
                        existing_details.add(policy_id)
                        fetched_detail_count += 1
                        consecutive_rate_limits = 0
                        print(f"[bokjiro] detail policy_id={policy_id}")
                    except CollectorError as exc:
                        print(f"[bokjiro] detail failed policy_id={policy_id} error={exc}")
                        error_text = str(exc).lower()
                        if "429" in error_text or "quota" in error_text:
                            consecutive_rate_limits += 1
                            if consecutive_rate_limits >= 3:
                                print("[bokjiro] stopping page run early due to repeated rate-limit responses")
                                return
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)

            page += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    finally:
        collector.close()
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch raw policy data from gov24 and bokjiro.")
    parser.add_argument("--source", choices=("gov24", "bokjiro", "all"), default="all")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Use 0 to keep paging until an empty page is returned.",
    )
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--fetch-details", action="store_true")
    parser.add_argument("--fetch-conditions", action="store_true")
    parser.add_argument(
        "--detail-mode",
        choices=("missing", "all"),
        default="missing",
        help="When set to missing, only policies without a saved raw detail are requested again.",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=None,
        help="Optional cap for how many detail payloads to fetch in one run.",
    )
    parser.add_argument(
        "--detail-only-missing-from-db",
        action="store_true",
        help="Fetch only missing detail rows for policy IDs already stored in raw list data.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.source in ("gov24", "all"):
        fetch_gov24(
            start_page=args.start_page,
            max_pages=args.max_pages,
            page_size=args.page_size,
            fetch_details=args.fetch_details,
            fetch_conditions=args.fetch_conditions,
            detail_mode=args.detail_mode,
            sleep_seconds=args.sleep_seconds,
            detail_limit=args.detail_limit,
        )
    if args.source in ("bokjiro", "all"):
        fetch_bokjiro(
            start_page=args.start_page,
            max_pages=args.max_pages,
            page_size=args.page_size,
            fetch_details=args.fetch_details,
            detail_mode=args.detail_mode,
            sleep_seconds=args.sleep_seconds,
            detail_limit=args.detail_limit,
            detail_only_missing_from_db=args.detail_only_missing_from_db,
        )


if __name__ == "__main__":
    main()
