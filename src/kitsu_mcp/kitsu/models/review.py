"""Review: preview files, recent uploads, downloads, playlists and video."""

from pydantic import BaseModel, Field


class PreviewFile(BaseModel):
    id: str
    revision: int | None
    position: int | None = Field(None, description="Order within the revision; 1 is the main file")
    extension: str | None
    is_movie: bool | None
    original_name: str | None
    status: str | None
    validation_status: str | None
    width: int | None
    height: int | None
    created_at: str | None
    is_video: bool = Field(
        default=False, description="A movie, detected from the extension (is_movie is unreliable); see the video tools"
    )
    duration: float | None = Field(default=None, description="Seconds, for movies")
    note: str | None = None
    url: str | None = Field(None, description="Kitsu web page; open it to watch movies and read comments")
    download_url: str | None = Field(None, description="Original upload; opens in a browser signed in to Kitsu")


class RecentPreview(BaseModel):
    """An upload from the project's activity feed."""

    date: str | None
    entity: str | None = Field(description="Full entity name, e.g. 'SQ010 / SH020'")
    entity_id: str | None
    task_id: str | None
    task_type: str | None
    status: str | None = Field(description="Task status set with the upload")
    author: str | None
    preview_file_id: str
    revision: int | None
    extension: str | None
    is_video: bool


class RecentPreviews(BaseModel):
    total: int = Field(description="Uploads matching the filters in Kitsu (may exceed what is returned)")
    previews: list[RecentPreview]


class SavedPreview(BaseModel):
    kind: str
    id: str
    name: str
    path: str


class FailedPreview(BaseModel):
    name: str
    error: str


class DownloadResult(BaseModel):
    saved: list[SavedPreview]
    skipped: int = Field(description="All entities not downloaded: the sum of the next three counts")
    no_preview: int = 0
    canceled: int = 0
    already_downloaded: int = Field(0, description="File already in dest_dir (pass overwrite=True to replace)")
    failed: list[FailedPreview]


class Playlist(BaseModel):
    id: str
    name: str
    for_entity: str | None
    for_client: bool | None
    task_type: str | None
    updated_at: str | None
    url: str | None = Field(None, description="Kitsu web page; open it to watch movies and read comments")


class PlaylistList(BaseModel):
    total: int = Field(description="Playlists before limit/offset")
    playlists: list[Playlist]


class PlaylistItem(BaseModel):
    entity_id: str
    entity: str | None
    preview_file_id: str | None


class PlaylistDetail(Playlist):
    items: list[PlaylistItem]


class VideoInfo(BaseModel):
    preview_file_id: str
    task_id: str | None
    revision: int | None
    original_name: str | None
    extension: str | None
    download_url: str | None = Field(None, description="Original upload; opens in a browser signed in to Kitsu")
    quality: str = Field(description="Which file was probed: low (Kitsu's web-playback encode) or original")
    file_bytes: int
    codec: str | None
    width: int
    height: int
    fps: float
    duration: float = Field(description="Seconds")
    frame_count: int = Field(description="Frames are numbered 1..frame_count, like Kitsu's player")
    kitsu_width: int | None = None
    kitsu_height: int | None = None
    kitsu_duration: float | None = None
    original_file_size: int | None = Field(None, description="Bytes of the uploaded file")
    annotated_frames: list[int] = Field(default_factory=list, description="Frames with drawings in Kitsu")


class SavedVideo(BaseModel):
    preview_file_id: str
    path: str
    quality: str
    bytes: int
    skipped: bool = Field(default=False, description="The file already existed and overwrite was False")
