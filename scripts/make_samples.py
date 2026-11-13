"""Create original Vietnamese PDF/DOCX fixtures; no third-party corpus required."""
from pathlib import Path
import os
import zipfile
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'data' / 'samples'
    target.mkdir(parents=True, exist_ok=True)
    candidates = [os.getenv('DEMO_FONT', ''), 'C:/Windows/Fonts/arial.ttf',
                  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                  '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']
    font = next((p for p in candidates if p and Path(p).is_file()), None)
    if not font:
        raise SystemExit('Set DEMO_FONT to a Unicode TrueType font.')
    pdfmetrics.registerFont(TTFont('Vietnamese', font))
    pages = [
        ['TÀI LIỆU MINH HỌA — QUY TRÌNH ĐĂNG KÝ',
         'Hồ sơ đăng ký được xử lý trong 5 ngày làm việc.',
         'Người đăng ký nộp hồ sơ tại phòng đào tạo.',
         'Hồ sơ gồm đơn đăng ký và bản sao thẻ sinh viên.'],
        ['NGUYÊN TẮC TRẢ LỜI TÀI LIỆU',
         'Câu trả lời phải dựa trên bằng chứng trong tài liệu đã chọn.',
         'Mỗi câu trả lời cần kèm nguồn tài liệu và số trang.',
         'Khi không có đủ bằng chứng, hệ thống phải từ chối trả lời.'],
    ]
    pdf = canvas.Canvas(str(target / 'quy-trinh-demo.pdf'))
    for lines in pages:
        pdf.setFont('Vietnamese', 12)
        for number, line in enumerate(lines):
            pdf.drawString(40, 790 - number * 32, line)
        pdf.showPage()
    pdf.save()
    lines = ['Hướng dẫn hỗ trợ — dữ liệu minh họa', 'Bộ phận hỗ trợ làm việc từ thứ Hai đến thứ Sáu.',
             'Yêu cầu hỗ trợ được tiếp nhận qua cổng thông tin sinh viên.']
    with zipfile.ZipFile(target / 'huong-dan-demo.docx', 'w', zipfile.ZIP_DEFLATED) as doc:
        doc.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        doc.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        paragraphs = ''.join(f'<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>' for line in lines)
        doc.writestr('word/document.xml', f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}<w:sectPr/></w:body></w:document>')
    print(target)


if __name__ == '__main__':
    main()
