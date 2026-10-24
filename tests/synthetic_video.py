"""Tiny synthetic movies for the video tests: every frame is a solid colour derived from its number."""

from pathlib import Path

FPS = 24
WIDTH, HEIGHT = 160, 90


def frame_colour(index: int) -> tuple[int, int, int]:
    """Colour of the 0-based frame `index`, unique for the first 4 seconds.

    Red ramps within each second, green flips every second, blue steps up every second.
    """
    second, within = divmod(index, FPS)
    return (within * 10, 200 if second % 2 else 40, 30 + second * 60)


def make_movie(path: Path, frames: int = 72, fps: int = FPS, size: tuple[int, int] = (WIDTH, HEIGHT)) -> Path:
    import av
    from PIL import Image

    width, height = size
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        stream.options = {"g": str(fps), "crf": "18", "preset": "medium", "bf": "3"}  # a keyframe every second
        for index in range(frames):
            frame = av.VideoFrame.from_image(Image.new("RGB", (width, height), frame_colour(index)))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path
