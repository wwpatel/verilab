"""
Generates the real Open Graph social share image for the marketing page.

A real generated asset (1200x630 PNG, the standard OG size), not a
placeholder or a screenshot: drawn directly from the same brand tokens as
the rest of the site (site/shared.css's navy/teal/violet), using Georgia
for the wordmark to match the wordmark everywhere else on the site.

This is a one-time local asset build (it shells out to system font files
at fixed macOS paths), not something re-run on every deploy. Re-run only
if the hero copy or brand colors change:

    python3 build_og_image.py
"""

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 630
NAVY = (27, 42, 74)
NAVY_LIGHT = (44, 66, 112)
TEAL = (42, 127, 126)
VIOLET = (91, 75, 138)
WHITE = (255, 255, 255)
LIGHT = (199, 208, 227)

GEORGIA_BOLD = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"


def main():
    img = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(img)

    # Soft diagonal accent band, top right, teal fading into violet, kept
    # subtle so it reads as texture, not competing with the text.
    for i in range(0, 420, 4):
        t = i / 420
        r = int(TEAL[0] + (VIOLET[0] - TEAL[0]) * t)
        g = int(TEAL[1] + (VIOLET[1] - TEAL[1]) * t)
        b = int(TEAL[2] + (VIOLET[2] - TEAL[2]) * t)
        draw.line([(WIDTH - 420 + i, 0), (WIDTH, i)], fill=(r, g, b), width=4)

    draw.rectangle([0, 0, WIDTH, HEIGHT], outline=NAVY_LIGHT, width=2)

    wordmark_font = ImageFont.truetype(GEORGIA_BOLD, 88)
    tagline_font = ImageFont.truetype(ARIAL, 34)
    footer_font = ImageFont.truetype(ARIAL, 24)

    draw.text((80, 200), "VERILAB", font=wordmark_font, fill=WHITE)

    # Small teal accent rule under the wordmark.
    draw.rectangle([84, 305, 224, 310], fill=TEAL)

    tagline_lines = [
        "The check that catches what the",
        "Opentrons simulator misses.",
    ]
    y = 340
    for line in tagline_lines:
        draw.text((80, y), line, font=tagline_font, fill=LIGHT)
        y += 46

    draw.text((80, HEIGHT - 70), "github.com/wwpatel/verilab", font=footer_font, fill=LIGHT)

    out_path = "site/og-image.png"
    img.save(out_path)
    print(f"Wrote {out_path} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()
