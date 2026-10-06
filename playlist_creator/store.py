"""On-disk cache. Every stage reads and writes here, so each step can be re-run alone."""

import json
import os
from pathlib import Path

import numpy as np


class Store:
    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)
        self.videos_dir = self.root / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    # One JSON file per video: {"id", "title", ..., "transcript", "summary", "jev"}
    def video_path(self, video_id: str) -> Path:
        return self.videos_dir / f"{video_id}.json"

    def load_video(self, video_id: str) -> dict:
        path = self.video_path(video_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"id": video_id}

    def save_video(self, video: dict) -> None:
        _write_json(self.video_path(video["id"]), video)

    def update_video(self, video_id: str, **fields) -> dict:
        video = self.load_video(video_id)
        video.update(fields)
        self.save_video(video)
        return video

    def videos(self) -> list[dict]:
        """All cached videos, newest upload first (unknown dates last)."""
        videos = [json.loads(p.read_text(encoding="utf-8")) for p in self.videos_dir.glob("*.json")]
        return sorted(videos, key=lambda v: v.get("upload_date") or "", reverse=True)

    def load_json(self, name: str, default=None):
        path = self.root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def save_json(self, name: str, data) -> Path:
        path = self.root / name
        _write_json(path, data)
        return path

    def load_embeddings(self, model: str) -> dict[str, np.ndarray]:
        path = self._embeddings_path(model)
        if not path.exists():
            return {}
        with np.load(path) as data:
            return {key: data[key] for key in data.files}

    def save_embeddings(self, model: str, embeddings: dict[str, np.ndarray]) -> None:
        path = self._embeddings_path(model)
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **embeddings)
        os.replace(tmp, path)

    def _embeddings_path(self, model: str) -> Path:
        return self.root / f"embeddings-{model.replace('/', '_')}.npz"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
