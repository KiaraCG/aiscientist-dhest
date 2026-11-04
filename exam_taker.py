import os
import json
import urllib.request
import urllib.error
import re 

# ReportLab imports for generating space-efficient PDFs
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

# File paths
EXAM_DIR = "signals-and-systems"
EXAM_ID = "hs21"

EXAM_FILE = f"data/{EXAM_DIR}/exam_{EXAM_ID}.json"
OUTPUT_PDF = f"llm_output/{EXAM_DIR}/output_{EXAM_ID}.pdf"

# Read directly from the shell environment variable
api_key = os.environ.get("SWISSAI_RESEARCH_API_KEY")
if not api_key:
    print("Error: SWISSAI_RESEARCH_API_KEY is not set in your environment.")
    print("Please run: export SWISSAI_RESEARCH_API_KEY='your_key' before running this script.")
    exit(1)

if not os.path.exists(EXAM_FILE):
    print(f"Error: {EXAM_FILE} not found. Please ensure your exam JSON file exists.")
    exit(1)

with open(EXAM_FILE, "r", encoding="utf-8") as f:
    exam_data = json.load(f)

# Construct prompt asking for full solutions structured in JSON
prompt_content = f"""You are an expert exam solver in Signals and Systems. You must solve the exam questions provided and output strictly valid JSON matching the requested output format. Do not include markdown code block formatting (e.g., ```json), and do not include any explanatory prose outside of the JSON object.

Please solve the following exam. For each question, provide the question title/summary, selected answer, and a concise explanation/solution.

Exam Data:
{json.dumps(exam_data, indent=2)}

Return your final submission matching strictly this JSON format:
{{
  "examId": "{exam_data.get('examId', '')}",
  "examTitle": "Signals & Systems Solutions",
  "answers": [
    {{
      "id": "q1",
      "question": "<short description/summary of question 1>",
      "answer": "<exact option text selected>",
      "explanation": "<concise step-by-step solution logic>"
    }}
  ]
}}
"""

url = "https://api.swissai.svc.cscs.ch/v1/chat/completions"

payload = {
    "model": "CSCS-Inference/swiss-ai/Apertus-v1.5-70B",
    "messages": [
        {
            "role": "system",
            "content": "You are a precise automated exam solver. You output ONLY valid raw JSON without any markdown code blocks, conversational text, or explanations outside the JSON structure."
        },
        {
            "role": "user",
            "content": prompt_content
        }
    ],
    "temperature": 0.1,  # Lower temperature reduces rambling and formatting drift
    "stream": False
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers=headers,
    method="POST"
)


def extract_json_safely(raw_text):
    """Extracts and parses JSON object from raw LLM output, handling markdown and extra text."""
    # Try direct parse first
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code blocks if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Use regex to find the first '{' and last '}'
    match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not extract valid JSON from model response.")

def generate_compact_pdf(solution_data, output_filepath):
    """
    Generates a space-efficient, compact PDF containing exam solutions.
    """
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    # Ultra-compact margins (0.25 inch / 18 pt) to minimize page count
    doc = SimpleDocTemplate(
        output_filepath,
        pagesize=letter,
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18
    )

    styles = getSampleStyleSheet()

    # Custom dense typography styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=colors.HexColor('#1A2B4C'),
        spaceAfter=2
    )

    header_meta_style = ParagraphStyle(
        'HeaderMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#555555')
    )

    qid_style = ParagraphStyle(
        'QID',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1A2B4C')
    )

    text_style = ParagraphStyle(
        'QText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#222222')
    )

    ans_style = ParagraphStyle(
        'QAns',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#0D6EFD')
    )

    expl_style = ParagraphStyle(
        'QExpl',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#333333')
    )

    story = []

    # Title & Metadata Row
    exam_id_text = solution_data.get('examId', EXAM_ID).upper()
    exam_title = solution_data.get('examTitle', 'Exam Solutions')
    
    story.append(Paragraph(f"<b>{exam_title}</b> — Solutions ({exam_id_text})", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1A2B4C'), spaceBefore=2, spaceAfter=4))

    # Dense Table Setup
    # Total printable width = 612 (letter width) - 36 (margins) = 576 points
    col_widths = [45, 180, 130, 221]  # ID | Question | Answer | Explanation

    table_data = [
        [
            Paragraph("<b>Q#</b>", qid_style),
            Paragraph("<b>Question / Context</b>", qid_style),
            Paragraph("<b>Selected Answer</b>", qid_style),
            Paragraph("<b>Solution Logic</b>", qid_style)
        ]
    ]

    answers = solution_data.get('answers', [])
    for idx, item in enumerate(answers):
        q_id = str(item.get('id', f'Q{idx+1}'))
        q_text = item.get('question', '-')
        q_ans = item.get('answer', '-')
        q_expl = item.get('explanation', '-')

        table_data.append([
            Paragraph(q_id, qid_style),
            Paragraph(q_text, text_style),
            Paragraph(q_ans, ans_style),
            Paragraph(q_expl, expl_style)
        ])

    # Table styling for maximum density
    dense_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    dense_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F0F4F8')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1A2B4C')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D0D7DE')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')])
    ]))

    story.append(dense_table)
    doc.build(story)


try:
    print("Sending exam to SwissAI API...")
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        raw_content = result["choices"][0]["message"]["content"].strip()

        if raw_content.startswith("```"):
            lines = raw_content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_content = "\n".join(lines).strip()

        parsed_output = json.loads(raw_content)
        
        # Build ultra-compact PDF output
        generate_compact_pdf(parsed_output, OUTPUT_PDF)
        print(f"Success! Exam solution PDF saved to '{OUTPUT_PDF}'.")

except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.reason}")
    print(e.read().decode("utf-8"))
except json.JSONDecodeError:
    print("Error: The model output could not be parsed as valid JSON.")
    print("Raw output received:")
    print(raw_content)
except Exception as e:
    print(f"An unexpected error occurred: {e}")