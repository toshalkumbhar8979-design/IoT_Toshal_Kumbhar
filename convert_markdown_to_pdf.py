from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

src = Path('part_a_sensor_selection.md')
out = Path('part_a_sensor_selection.pdf')
text = src.read_text(encoding='utf-8')

lines = text.splitlines()
story = []
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='Body', parent=styles['BodyText'], fontSize=10, leading=14, spaceAfter=6))

# Very simple markdown-to-PDF conversion for this document.
for line in lines:
    if not line.strip():
        story.append(Spacer(1, 6))
    elif line.startswith('# '):
        story.append(Paragraph(line[2:], styles['Title']))
    elif line.startswith('## '):
        story.append(Paragraph(line[3:], styles['Heading2']))
    elif line.startswith('### '):
        story.append(Paragraph(line[4:], styles['Heading3']))
    else:
        story.append(Paragraph(line, styles['Body']))

pdf = SimpleDocTemplate(str(out), pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
pdf.build(story)
print(f'Created {out} ({out.stat().st_size} bytes)')
