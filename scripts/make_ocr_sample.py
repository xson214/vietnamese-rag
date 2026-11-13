"""Original high-contrast Vietnamese OCR fixture, no patient/medical data."""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    fonts = [
        os.getenv("DEMO_FONT", ""),
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    name = next((p for p in fonts if p and Path(p).is_file()), None)
    if not name:
        raise SystemExit("Set DEMO_FONT to a Vietnamese-compatible TrueType font.")
    image = Image.new("RGB", (1800, 650), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(name, 48)
    lines = [
        "TÀI LIỆU OCR MINH HỌA",
        "Hồ sơ đăng ký được xử lý trong 5 ngày làm việc.",
        "Đây là dữ liệu thử nghiệm, không phải đơn thuốc.",
        "Chụp đủ trang, rõ nét và đủ sáng.",
    ]
    for i, line in enumerate(lines):
        draw.text((65, 70 + i * 110), line, font=font, fill="black")
    output = ROOT / "data/samples/ocr-demo.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    image.close()
    print(output)


if __name__ == "__main__":
    main()
