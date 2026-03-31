from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import CommunityPost, CommunityPostLike


DEMO_ACTOR_KEY = "demo-user"


def serialize_post(post: CommunityPost, liked_post_ids: set[int]) -> dict:
    created_at = post.created_at.replace(tzinfo=timezone.utc).isoformat() if post.created_at.tzinfo is None else post.created_at.isoformat()
    return {
        "id": post.id,
        "category": post.category,
        "title": post.title,
        "content": post.content,
        "author_name": post.author_name,
        "author_masked": post.author_masked,
        "region_text": post.region_text,
        "created_at": created_at,
        "like_count": post.like_count,
        "is_liked_by_me": post.id in liked_post_ids,
    }


def seed_posts_if_empty(db: Session) -> None:
    exists = db.execute(select(func.count()).select_from(CommunityPost)).scalar_one()
    if exists:
        return
    samples = [
        CommunityPost(category="review", title="청년 월세 지원금 받았어요", content="서류만 제대로 준비하니 생각보다 빨리 승인됐습니다.", author_name="서울청년", region_text="서울 강남구", like_count=87),
        CommunityPost(category="qna", title="국민내일배움카드 조건이 궁금합니다", content="재직 중인데도 신청 가능한지 궁금합니다.", author_name="김청년", region_text="서울 마포구", like_count=12),
        CommunityPost(category="regional", title="마포구 주민센터 처리 속도 어떤가요?", content="최근 신청해보신 분 있으면 후기 알려주세요.", author_name="복지러버", region_text="서울 마포구", like_count=6),
        CommunityPost(category="anonymous", title="탈락 사유가 소득 때문이라는데 억울해요", content="건보료 기준이 생각보다 높게 잡히네요. 비슷한 경험 있으신가요?", author_name="익명", author_masked=True, like_count=4),
    ]
    db.add_all(samples)
    db.commit()


def list_posts(db: Session, category: str, sort: str, page: int, size: int) -> tuple[list[dict], int]:
    seed_posts_if_empty(db)

    query = select(CommunityPost)
    if category != "all":
        query = query.where(CommunityPost.category == category)
    if sort == "popular":
        query = query.order_by(desc(CommunityPost.like_count), desc(CommunityPost.created_at))
    else:
        query = query.order_by(desc(CommunityPost.created_at))

    total_count = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.offset((page - 1) * size).limit(size)).scalars().all()
    liked_post_ids = set(
        db.execute(
            select(CommunityPostLike.post_id).where(CommunityPostLike.actor_key == DEMO_ACTOR_KEY)
        ).scalars().all()
    )
    return [serialize_post(post, liked_post_ids) for post in rows], total_count


def get_post(db: Session, post_id: int) -> dict | None:
    seed_posts_if_empty(db)
    post = db.execute(select(CommunityPost).where(CommunityPost.id == post_id)).scalar_one_or_none()
    if not post:
        return None
    liked_post_ids = set(
        db.execute(
            select(CommunityPostLike.post_id).where(CommunityPostLike.actor_key == DEMO_ACTOR_KEY)
        ).scalars().all()
    )
    return serialize_post(post, liked_post_ids)


def create_post(db: Session, category: str, title: str, content: str, region_text: str | None) -> dict:
    seed_posts_if_empty(db)
    post = CommunityPost(
        category=category,
        title=title,
        content=content,
        region_text=region_text,
        author_name="남정현",
        author_masked=(category == "anonymous"),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return serialize_post(post, set())


def like_post(db: Session, post_id: int) -> dict | None:
    post = db.execute(select(CommunityPost).where(CommunityPost.id == post_id)).scalar_one_or_none()
    if not post:
        return None
    like = db.execute(
        select(CommunityPostLike).where(
            CommunityPostLike.post_id == post_id,
            CommunityPostLike.actor_key == DEMO_ACTOR_KEY,
        )
    ).scalar_one_or_none()
    if like is None:
        db.add(CommunityPostLike(post_id=post_id, actor_key=DEMO_ACTOR_KEY))
        post.like_count += 1
        db.commit()
    return {"id": post.id, "like_count": post.like_count, "is_liked_by_me": True}


def unlike_post(db: Session, post_id: int) -> dict | None:
    post = db.execute(select(CommunityPost).where(CommunityPost.id == post_id)).scalar_one_or_none()
    if not post:
        return None
    like = db.execute(
        select(CommunityPostLike).where(
            CommunityPostLike.post_id == post_id,
            CommunityPostLike.actor_key == DEMO_ACTOR_KEY,
        )
    ).scalar_one_or_none()
    if like is not None:
        db.delete(like)
        post.like_count = max(0, post.like_count - 1)
        db.commit()
    return {"id": post.id, "like_count": post.like_count, "is_liked_by_me": False}


def get_hot_posts(db: Session) -> list[dict]:
    seed_posts_if_empty(db)
    rows = db.execute(select(CommunityPost).order_by(desc(CommunityPost.like_count), desc(CommunityPost.created_at)).limit(5)).scalars().all()
    liked_post_ids = set(
        db.execute(
            select(CommunityPostLike.post_id).where(CommunityPostLike.actor_key == DEMO_ACTOR_KEY)
        ).scalars().all()
    )
    return [serialize_post(post, liked_post_ids) for post in rows]


def get_stats(db: Session) -> dict:
    seed_posts_if_empty(db)
    total_posts = db.execute(select(func.count()).select_from(CommunityPost)).scalar_one()
    total_likes = db.execute(select(func.coalesce(func.sum(CommunityPost.like_count), 0))).scalar_one()
    today = datetime.utcnow().date()
    today_posts = db.execute(
        select(func.count()).select_from(CommunityPost).where(func.date(CommunityPost.created_at) == today)
    ).scalar_one()
    return {
        "total_posts": total_posts,
        "today_posts": today_posts,
        "total_likes": total_likes,
    }
