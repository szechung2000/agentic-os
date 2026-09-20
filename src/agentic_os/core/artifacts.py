"""Content-addressed artifact storage with integrity verification."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from agentic_os.core.contracts import ArtifactRef
from agentic_os.core.redaction import redact_bytes

_SHA256_DIGEST = re.compile(r"^[a-f0-9]{64}$")


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve(strict=True)

    def put(self, content: bytes, media_type: str) -> ArtifactRef:
        content = redact_bytes(content)
        ref = ArtifactRef.from_bytes(content, media_type)
        path = self.path_for(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".artifact-")
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as temporary:
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return ref

    def path_for(self, ref: ArtifactRef) -> Path:
        digest = ref.content_hash.removeprefix("sha256:")
        if not _SHA256_DIGEST.fullmatch(digest):
            raise ValueError("invalid artifact content hash")
        path = self.root / digest[:2] / f"{digest}.blob"
        if not path.is_relative_to(self.root):
            raise ValueError("artifact path escapes store root")
        return path

    def get(self, ref: ArtifactRef) -> bytes:
        content = self.path_for(ref).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if f"sha256:{digest}" != ref.content_hash:
            raise ValueError(f"artifact hash mismatch: {ref.artifact_id}")
        return content
