"""Content-addressed artifact storage with integrity verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentic_os.core.contracts import ArtifactRef


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, media_type: str) -> ArtifactRef:
        ref = ArtifactRef.from_bytes(content, media_type)
        path = self.path_for(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return ref

    def path_for(self, ref: ArtifactRef) -> Path:
        digest = ref.content_hash.removeprefix("sha256:")
        return self.root / digest[:2] / f"{digest}.blob"

    def get(self, ref: ArtifactRef) -> bytes:
        content = self.path_for(ref).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if f"sha256:{digest}" != ref.content_hash:
            raise ValueError(f"artifact hash mismatch: {ref.artifact_id}")
        return content
