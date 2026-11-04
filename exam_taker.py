import os
import json
import re
import time
import urllib.request
import urllib.error

# ReportLab imports for generating space-efficient PDFs
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, HRFlowable

# File paths
EXAM_DIR = "signals-and-systems"
EXAM_ID = "hs17"

EXAM_FILE = f"data/{EXAM_DIR}/exam_{EXAM_ID}.json"
OUTPUT_JSON = f"llm_output/{EXAM_DIR}/solutions_{EXAM_ID}.json"
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

def extract_json_safely(raw_text):
    """Robustly extracts and parses JSON from raw LLM output, handling markdown and preamble/postamble text."""
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

    # Use regex to find the outermost JSON braces
    match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not extract valid JSON from model response.")

def chunk_list(lst, n):
    """Yields successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# Extract questions from the exam structure
questions = exam_data.get('questions', [])
if not questions and isinstance(exam_data, list):
    questions = exam_data

chunk_size = 4  # Process 4 questions per request to avoid 504 timeouts
all_answers = []

url = "https://api.swissai.svc.cscs.ch/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

print(f"Starting batch processing of {len(questions)} questions in chunks of {chunk_size}...")

for idx, chunk in enumerate(chunk_list(questions, chunk_size)):
    print(f"Processing question chunk {idx + 1}...")
    
    chunk_payload_data = exam_data.copy()
    if isinstance(chunk_payload_data, dict):
        chunk_payload_data['questions'] = chunk

    prompt_content = f"""You are an expert exam solver in Signals and Systems. Solve the provided exam questions chunk and return strictly valid JSON matching the exact requested format. Do not include markdown code blocks or explanatory prose outside the JSON.

Exam Data Chunk:
{json.dumps(chunk_payload_data, indent=2)}

Return strictly this JSON format:
{{
  "examId": "{exam_data.get('examId', EXAM_ID)}",
  "examTitle": "Signals & Systems Solutions",
  "answers": [
    {{
      "id": "q1",
      "question": "<short description/summary of question>",
      "answer": "<exact option text selected>",
      "explanation": "<concise step-by-step solution logic>"
    }}
  ]
}}
"""

    payload = {
        "model": "CSCS-Inference/swiss-ai/Apertus-v1.5-70B",
        "messages": [
            {
                "role": "system",
                "content": "You are a precise automated exam solver. Output ONLY valid raw JSON without markdown or explanations outside the JSON object."
            },
            {
                "role": "user",
                "content": prompt_content
            }
        ],
        "temperature": 0.1,
        "stream": False
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    success = False
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                raw_content = result["choices"][0]["message"]["content"]
                parsed_chunk = extract_json_safely(raw_content)
                
                if "answers" in parsed_chunk:
                    all_answers.extend(parsed_chunk["answers"])
                success = True
                break
        except urllib.error.HTTPError as e:
            if e.code == 504 and attempt < 2:
                wait_time = 2 ** attempt
                print(f"Gateway Timeout (504) on chunk {idx + 1}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"HTTP Error {e.code}: {e.reason}")
            if hasattr(e, 'read'):
                print(e.read().decode("utf-8"))
            break
        except Exception as ex:
            print(f"Attempt {attempt + 1} failed for chunk {idx + 1}: {ex}")
            if attempt == 2:
                raise
            time.sleep(1)

    if not success:
        print(f"Warning: Chunk {idx + 1} failed after retries.")
    
    # Polite pause between chunks
    time.sleep(1)

# Compile consolidated solution dictionary
solution_data = {
    "examId": exam_data.get('examId', EXAM_ID),
    "examTitle": "Signals & Systems Solutions",
    "answers": all_answers
}

# Save intermediate JSON response to disk so you can iterate on PDF formatting without re-calling the API
os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(solution_data, f, indent=2)
print(f"Intermediate JSON saved to '{OUTPUT_JSON}'.")


def generate_compact_pdf(sol_data, output_filepath):
    """
    Generates a space-efficient, compact PDF containing exam solutions.
    """
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

    doc = SimpleDocTemplate(
        output_filepath,
        pagesize=letter,
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=colors.HexColor('#1A2B4C'),
        spaceAfter=2
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

    exam_id_text = sol_data.get('examId', EXAM_ID).upper()
    exam_title = sol_data.get('examTitle', 'Exam Solutions')
    
    story.append(Paragraph(f"<b>{exam_title}</b> — Solutions ({exam_id_text})", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1A2B4C'), spaceBefore=2, spaceAfter=4))

    col_widths = [45, 180, 130, 221]  # ID | Question | Answer | Explanation

    table_data = [
        [
            Paragraph("<b>Q#</b>", qid_style),
            Paragraph("<b>Question / Context</b>", qid_style),
            Paragraph("<b>Selected Answer</b>", qid_style),
            Paragraph("<b>Solution Logic</b>", qid_style)
        ]
    ]

    for idx, item in enumerate(sol_data.get('answers', [])):
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


# Build the PDF using the compiled solution data
generate_compact_pdf(solution_data, OUTPUT_PDF)
print(f"Success! Exam solution PDF saved to '{OUTPUT_PDF}'.")

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

