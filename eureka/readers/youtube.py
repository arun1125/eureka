"""YouTubeReader — download auto-captions, fall back to Whisper if unavailable."""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url}")


def _download_captions(video_id: str, output_dir: str) -> tuple[list[dict] | None, dict]:
    """Try to download YouTube auto-captions. Returns (segments, metadata) or (None, metadata).

    Segments match Whisper format: [{"start": float, "end": float, "text": str}, ...]
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # First get metadata
    meta_cmd = ["yt-dlp", "--dump-json", "--no-download", url]
    print(f"Fetching metadata for {video_id}...", file=sys.stderr, flush=True)
    meta_result = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=60)
    if meta_result.returncode != 0:
        return None, {}

    metadata = json.loads(meta_result.stdout.strip().split("\n")[-1])

    # Try to download auto-subs as JSON3 (has timestamps)
    sub_cmd = [
        "yt-dlp",
        "--write-auto-sub",
        "--sub-lang", "en",
        "--sub-format", "json3",
        "--skip-download",
        "-o", os.path.join(output_dir, "%(id)s"),
        url,
    ]
    print("Trying auto-captions...", file=sys.stderr, flush=True)
    subprocess.run(sub_cmd, capture_output=True, text=True, timeout=60)

    # Look for the downloaded subtitle file
    sub_path = None
    for f in os.listdir(output_dir):
        if f.endswith(".json3") or (f.endswith(".json") and video_id in f):
            sub_path = os.path.join(output_dir, f)
            break

    if not sub_path:
        for f in os.listdir(output_dir):
            if f.endswith(".vtt") and video_id in f:
                sub_path = os.path.join(output_dir, f)
                break

    if not sub_path:
        print("No auto-captions found.", file=sys.stderr, flush=True)
        return None, metadata

    print(f"Found captions: {Path(sub_path).name}", file=sys.stderr, flush=True)

    if sub_path.endswith(".json3") or sub_path.endswith(".json"):
        segments = _parse_json3_subs(sub_path)
    elif sub_path.endswith(".vtt"):
        segments = _parse_vtt_subs(sub_path)
    else:
        return None, metadata

    if segments:
        print(f"Parsed {len(segments)} caption segments.", file=sys.stderr, flush=True)
    return segments, metadata


def _parse_json3_subs(path: str) -> list[dict]:
    """Parse YouTube json3 subtitle format into Whisper-style segments."""
    with open(path) as f:
        data = json.load(f)

    segments = []
    for event in data.get("events", []):
        start_ms = event.get("tStartMs", 0)
        duration_ms = event.get("dDurationMs", 0)
        segs = event.get("segs", [])
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if text and text != "\n":
            segments.append({
                "start": start_ms / 1000.0,
                "end": (start_ms + duration_ms) / 1000.0,
                "text": text,
            })
    return segments


def _parse_vtt_subs(path: str) -> list[dict]:
    """Parse VTT subtitle format into Whisper-style segments."""
    with open(path) as f:
        content = f.read()

    segments = []
    pattern = r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
    blocks = re.split(pattern, content)

    for i in range(1, len(blocks) - 2, 3):
        start_str, end_str, text_block = blocks[i], blocks[i + 1], blocks[i + 2]
        text = re.sub(r"<[^>]+>", "", text_block).strip()
        if not text:
            continue

        def _vtt_to_seconds(t: str) -> float:
            parts = t.split(":")
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s

        segments.append({
            "start": _vtt_to_seconds(start_str),
            "end": _vtt_to_seconds(end_str),
            "text": text,
        })

    # Deduplicate — VTT auto-captions repeat lines
    deduped = []
    for seg in segments:
        if not deduped or seg["text"] != deduped[-1]["text"]:
            deduped.append(seg)
    return deduped


def _download_video(video_id: str, output_dir: str) -> tuple[str, dict]:
    """Download video with yt-dlp, return (video_path, metadata)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--print-json",
        "--no-simulate",
        url,
    ]

    print(f"Downloading video {video_id}...", file=sys.stderr, flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[:500]}")

    metadata = json.loads(result.stdout.strip().split("\n")[-1])

    video_path = os.path.join(output_dir, f"{video_id}.mp4")
    if not os.path.exists(video_path):
        for f in os.listdir(output_dir):
            if f.startswith(video_id) and not f.endswith(".part"):
                video_path = os.path.join(output_dir, f)
                break

    if not os.path.exists(video_path):
        raise RuntimeError(f"Video file not found after download in {output_dir}")

    return video_path, metadata


def _transcribe_with_segments(video_path: str, model_name: str = "base") -> list[dict]:
    """Transcribe video audio with Whisper, return timestamped segments."""
    import whisper

    print(f"Loading Whisper model '{model_name}'...", file=sys.stderr, flush=True)
    model = whisper.load_model(model_name)

    print("Transcribing...", file=sys.stderr, flush=True)
    result = model.transcribe(video_path)

    return result["segments"]


def _segments_to_chunks(segments: list[dict], chunk_chars: int = 2000) -> list[str]:
    """Convert segments into text chunks."""
    full_text = " ".join(seg["text"].strip() for seg in segments)

    chunks = []
    words = full_text.split()
    current_chunk = []
    current_len = 0

    for word in words:
        word_len = len(word) + 1
        if current_len + word_len > chunk_chars and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(word)
        current_len += word_len

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


class YouTubeReader:
    """Read a YouTube video: auto-captions first, Whisper fallback."""

    def __init__(self, whisper_model: str = "base"):
        self.whisper_model = whisper_model

    def read(self, source_url: str) -> dict:
        video_id = _extract_video_id(source_url)

        with tempfile.TemporaryDirectory(prefix="eureka_yt_") as tmpdir:
            # Try auto-captions first (fast, no video download)
            segments, metadata = _download_captions(video_id, tmpdir)

            title = metadata.get("title", f"YouTube {video_id}")
            duration = metadata.get("duration", 0)
            channel = metadata.get("channel", metadata.get("uploader", "Unknown"))

            # Fall back to Whisper if no captions
            if not segments:
                print("Falling back to video download + Whisper...", file=sys.stderr, flush=True)
                video_path, metadata = _download_video(video_id, tmpdir)
                title = metadata.get("title", f"YouTube {video_id}")
                duration = metadata.get("duration", 0)
                channel = metadata.get("channel", metadata.get("uploader", "Unknown"))
                segments = _transcribe_with_segments(video_path, self.whisper_model)

            if not segments:
                raise RuntimeError(f"No transcript available for {video_id}")

        chunks = _segments_to_chunks(segments)

        return {
            "title": title,
            "type": "youtube",
            "chunks": chunks,
            "metadata": {
                "video_id": video_id,
                "channel": channel,
                "duration": duration,
                "url": source_url,
            },
        }
