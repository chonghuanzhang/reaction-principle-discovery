#!/usr/bin/env python3
"""Synchronize repository knowledge-graph view labels with the current catalog."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
FIGURE_DIR = ROOT / "knowledge_graph" / "figures"
FONT_OPTIONS = {
    "regular": (
        (Path("/System/Library/Fonts/Helvetica.ttc"), 0),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), 0),
        (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"), 0),
    ),
    "bold": (
        (Path("/System/Library/Fonts/Helvetica.ttc"), 1),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), 0),
        (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"), 0),
    ),
}

TITLES = (
    (531, "Tier 1 · 139 sources", "#406f91"),
    (1594, "Tier 2 · 101 sources", "#5d8c86"),
    (2657, "Tier 3 · 88 sources", "#a77b40"),
    (3720, "Tier 4 · 42 sources", "#92718e"),
)


def load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path, index in FONT_OPTIONS[weight]:
        if path.exists():
            return ImageFont.truetype(str(path), size=size, index=index)
    raise FileNotFoundError(f"No supported {weight} font was found")


def fade_towards_white(colour: str, opacity: float) -> str:
    channels = tuple(int(colour[index : index + 2], 16) for index in (1, 3, 5))
    blended = tuple(round(255 - (255 - channel) * opacity) for channel in channels)
    return "#" + "".join(f"{channel:02x}" for channel in blended)


def update_view(path: Path, figure_number: int) -> None:
    image = Image.open(path).convert("RGBA")
    if image.size != (4251, 4842):
        raise ValueError(f"Unexpected canvas for {path}: {image.size}")

    draw = ImageDraw.Draw(image)
    title_font = load_font("bold", 64)
    note_font = load_font("regular", 50)

    active_tier = figure_number - 5 if figure_number >= 6 else None
    for tier_index, (center_x, title, colour) in enumerate(TITLES, start=1):
        if active_tier is not None and tier_index != active_tier:
            colour = fade_towards_white(colour, 0.18)
        draw.rectangle((center_x - 430, 112, center_x + 430, 205), fill="white")
        draw.text((center_x, 160), title, font=title_font, fill=colour, anchor="mm")

    draw.rectangle((520, 4270, 3730, 4350), fill="white")
    draw.text(
        (2125, 4310),
        "Evidence tiers organize sources by chemical role.",
        font=note_font,
        fill="#74818b",
        anchor="mm",
    )

    image.convert("RGB").save(path, format="PNG", compress_level=9)


def main() -> None:
    for figure_number in range(2, 10):
        update_view(FIGURE_DIR / f"G{figure_number}.png", figure_number)


if __name__ == "__main__":
    main()
