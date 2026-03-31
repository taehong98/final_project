from pydantic import BaseModel, Field


class CommunityPostItem(BaseModel):
    id: int
    category: str
    title: str
    content: str
    author_name: str
    author_masked: bool
    region_text: str | None = None
    created_at: str
    like_count: int
    is_liked_by_me: bool


class CommunityListData(BaseModel):
    items: list[CommunityPostItem]
    page: int
    size: int
    total_count: int
    has_next: bool


class CommunityCreateRequest(BaseModel):
    category: str
    title: str = Field(max_length=80)
    content: str
    region_text: str | None = None


class CommunityLikeData(BaseModel):
    id: int
    like_count: int
    is_liked_by_me: bool


class CommunityStatsData(BaseModel):
    total_posts: int
    today_posts: int
    total_likes: int
