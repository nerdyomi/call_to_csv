"""Finding recordings and reading what the file name / file itself tells us."""
from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mutagen import File as MutagenFile

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/aac", ".aac")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/mpeg", ".mpeg")  # some recorders save MP3 as name.mp3.mpeg
mimetypes.add_type("audio/mpeg", ".mpga")

_AUDIO_SUFFIXES = {".mp3", ".mpeg", ".mpga", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def recording_stem(name: str) -> str:
    """'01762709049.mp3.mpeg' -> '01762709049'; strips any run of audio extensions."""
    p = Path(name)
    stem = p.stem
    while Path(stem).suffix.lower() in _AUDIO_SUFFIXES:
        stem = Path(stem).stem
    return stem


@dataclass(frozen=True)
class Recording:
    path: Path

    @property
    def stem(self) -> str:
        return recording_stem(self.path.name)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def mime_type(self) -> str:
        return mimetypes.guess_type(self.path.name)[0] or "audio/mpeg"

    @property
    def size(self) -> int:
        return self.path.stat().st_size


def discover(input_dir: Path, extensions: tuple[str, ...]) -> list[Recording]:
    if not input_dir.is_dir():
        raise SystemExit(f"Input folder not found: {input_dir}")
    files = sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in extensions)
    return [Recording(p) for p in files]


def duration_seconds(path: Path) -> float | None:
    try:
        audio = MutagenFile(path)
        return float(audio.info.length) if audio is not None and audio.info else None
    except Exception:
        return None


def metadata_from_filename(name: str, regex: str, tz_offset: str, phone_prefix: str,
                           duration: float | None) -> dict[str, str]:
    """Best-effort Started at / Ended at / Duration / Phone from the recording's file name.

    Returns only the keys it could work out; a manifest value always overrides these.
    """
    out: dict[str, str] = {}
    if duration:
        out["Duration (seconds)"] = str(round(duration))
    m = re.match(regex, recording_stem(name))
    if not m:
        return out
    groups = m.groupdict()
    if groups.get("date") and groups.get("time"):
        sign = -1 if tz_offset.startswith("-") else 1
        hh, mm = int(tz_offset[1:3]), int(tz_offset[3:5])
        tz = timezone(sign * timedelta(hours=hh, minutes=mm))
        start = datetime.strptime(groups["date"] + groups["time"], "%Y%m%d%H%M%S").replace(tzinfo=tz)
        out["Started at"] = start.strftime("%Y-%m-%d %H:%M:%S %z")
        if duration:
            out["Ended at"] = (start + timedelta(seconds=round(duration))).strftime("%Y-%m-%d %H:%M:%S %z")
    phone = groups.get("phone")
    if phone:
        # reference CEX keeps the leading 0 after the country code: 8801745196254
        out["Phone"] = phone_prefix + (phone if phone.startswith("0") else "0" + phone)
    return out
