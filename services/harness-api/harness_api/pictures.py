# SPDX-License-Identifier: AGPL-3.0-only
import base64
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote_to_bytes
from uuid import UUID, uuid4

import anyio

from .diagnostics import failure
from .upstream import Rights

SIGNATURES = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def may_attach(user_id: str, rights: Rights) -> bool:
    return True


def safe_name(header: str | None, mime: str) -> str:
    extension = ".png" if mime == "image/png" else ".jpg"
    try:
        name = unquote_to_bytes((header or "").encode("latin-1")).decode("utf-8")
    except UnicodeError, ValueError:
        name = ""
    name = re.split(r"[/\\]", name)[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).lstrip(". ")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return (stem[: 100 - len(extension)] or "picture") + extension


def key_parts(key: str) -> tuple[str, str]:
    parts = key.split("/")
    if (
        len(parts) != 3
        or parts[0] != "uploads"
        or not parts[2]
        or parts[2] in {".", ".."}
        or "\\" in key
        or "\x00" in key
    ):
        raise ValueError("Invalid upload key")
    if str(UUID(parts[1])) != parts[1]:
        raise ValueError("Invalid upload id")
    return parts[1], parts[2]


@contextmanager
def upload_directory(
    root: str, key: str, create: bool = False
) -> Iterator[tuple[int, str]]:
    identifier, name = key_parts(key)
    with_fd: list[int] = []
    try:
        parent = os.open(root, DIRECTORY)
        with_fd.append(parent)
        for part in ("uploads", identifier):
            if create:
                try:
                    os.mkdir(part, mode=0o750, dir_fd=parent)
                except FileExistsError:
                    pass
            parent = os.open(part, DIRECTORY, dir_fd=parent)
            with_fd.append(parent)
        yield parent, name
    finally:
        for descriptor in reversed(with_fd):
            os.close(descriptor)


def write_picture(root: str, key: str, content: bytes) -> None:
    with upload_directory(root, key, create=True) as (directory, name):
        temporary = f".pending-{uuid4()}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o640,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # The destination is a new UUID directory; refuse unexpected existing names.
        try:
            os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            raise FileExistsError("Upload already exists")


def read_picture(root: str, key: str) -> bytes:
    with upload_directory(root, key) as (directory, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            return source.read()


async def attach_pictures(
    history: list[dict[str, Any]], root: str, database: Any, user: str
) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in history
        if item.get("upload_id") and item.get("picture_completed", False)
    ][-3:]
    selected = {id(item) for item in candidates}
    result = []
    for item in history:
        message = {
            key: value
            for key, value in item.items()
            if key not in {"upload_id", "picture_completed"}
        }
        if id(item) in selected:
            identifier = item["upload_id"]
            try:
                upload = await database.upload(identifier, user)
                content = await anyio.to_thread.run_sync(
                    read_picture, root, upload["file_key"]
                )
                message["images"] = [
                    {
                        "media_type": upload["mime"],
                        "data": base64.b64encode(content).decode("ascii"),
                    }
                ]
            except OSError, ValueError:
                failure(
                    "request_error",
                    "storage_unavailable",
                    correlation_id=str(identifier),
                )
        result.append(message)
    return result
