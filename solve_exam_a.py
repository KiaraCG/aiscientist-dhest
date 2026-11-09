"""
BASELINE_A
"""
import os
import json
import re
import time
import urllib.request
import urllib.error
import sys
import argparse
import glob
import socket

# ReportLab imports for generating space-efficient PDFs
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, HRFlowable

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

def solve_exam(exam_dir, exam_id, model_name, api_key):
    """Processes a single exam file, queries the specified LLM model in smaller chunks, saves JSON, and generates a PDF."""
    exam_file = f"data/{exam_dir}/exam_{exam_id}.json"
    output_json = f"llm_output/{exam_dir}/solutions_{exam_id}.json"
    output_pdf = f"llm_output/{exam_dir}/output_{exam_id}.pdf"

    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False

    print(f"\n--- Processing Exam ID: {exam_id} (Directory: {exam_dir}) using model: {model_name} ---")

    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)

    questions = exam_data.get('questions', [])
    if not questions and isinstance(exam_data, list):
        questions = exam_data

    chunk_size = 4  
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
  "examId": "{exam_data.get('examId', exam_id)}",
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
            "model": model_name,
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
                # INCREASED TIMEOUT to 300s (5 minutes) for heavy 70B generation
                with urllib.request.urlopen(req, timeout=300) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    raw_content = result["choices"][0]["message"]["content"]
                    parsed_chunk = extract_json_safely(raw_content)
                    
                    if "answers" in parsed_chunk:
                        all_answers.extend(parsed_chunk["answers"])
                    success = True
                    break
            except urllib.error.HTTPError as e:
                if e.code == 504 and attempt < 2:
                    wait_time = 5 * (2 ** attempt)
                    print(f"Gateway Timeout (504) on chunk {idx + 1}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                print(f"HTTP Error {e.code}: {e.reason}")
                if hasattr(e, 'read'):
                    print(e.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, socket.timeout) as ex:
                wait_time = 5 * (2 ** attempt)  # Proper exponential backoff: 5s, 10s, 20s
                if attempt < 2:
                    print(f"Timeout/Network error on chunk {idx + 1} (Attempt {attempt + 1}/3). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                print(f"Attempt {attempt + 1} failed for chunk {idx + 1}: {ex}")
                break
            except Exception as ex:
                print(f"Attempt {attempt + 1} failed for chunk {idx + 1}: {ex}")
                if attempt == 2:
                    raise
                time.sleep(2)

        if not success:
            print(f"Warning: Chunk {idx + 1} failed after retries.")
        
        time.sleep(1)

    solution_data = {
        "examId": exam_data.get('examId', exam_id),
        "examTitle": "Signals & Systems Solutions",
        "answers": all_answers
    }

    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(solution_data, f, indent=2)
    print(f"Intermediate JSON saved to '{output_json}'.")

    generate_compact_pdf(solution_data, output_pdf, exam_id)
    print(f"Success! Exam solution PDF saved to '{output_pdf}'.")
    return True

def generate_compact_pdf(sol_data, output_filepath, exam_id):
    """Generates a space-efficient, compact PDF containing exam solutions."""
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
        'DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=12, leading=14, textColor=colors.HexColor('#1A2B4C'), spaceAfter=2
    )
    qid_style = ParagraphStyle(
        'QID', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#1A2B4C')
    )
    text_style = ParagraphStyle(
        'QText', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor('#222222')
    )
    ans_style = ParagraphStyle(
        'QAns', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#0D6EFD')
    )
    expl_style = ParagraphStyle(
        'QExpl', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#333333')
    )

    story = []
    exam_id_text = sol_data.get('examId', exam_id).upper()
    exam_title = sol_data.get('examTitle', 'Exam Solutions')
    
    story.append(Paragraph(f"<b>{exam_title}</b> — Solutions ({exam_id_text})", title_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1A2B4C'), spaceBefore=2, spaceAfter=4))

    col_widths = [45, 180, 130, 221]
    table_data = [[
        Paragraph("<b>Q#</b>", qid_style),
        Paragraph("<b>Question / Context</b>", qid_style),
        Paragraph("<b>Selected Answer</b>", qid_style),
        Paragraph("<b>Solution Logic</b>", qid_style)
    ]]

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

def main(argv=None) -> int:
    try:
        p = argparse.ArgumentParser(description="Process exam JSON files and generate solution PDFs.")
        p.add_argument("--examdir", default="signals-and-systems", help="Directory name under data/ containing exam JSON files.")
        p.add_argument("--examid", default=None, help="Specific exam ID (e.g., hs17). If omitted, processes all exams in the directory.")
        p.add_argument("--model", default="CSCS-Inference/swiss-ai/Apertus-v1.5-70B", help="LLM model identifier to use for processing.")
        args = p.parse_args(argv)

        exam_dir = args.examdir
        exam_id = args.examid
        model_name = args.model

        api_key = os.environ.get("SWISSAI_RESEARCH_API_KEY")
        if not api_key:
            print("Error: SWISSAI_RESEARCH_API_KEY is not set in your environment.")
            return 1

        target_dir = os.path.join("data", exam_dir)
        if not os.path.exists(target_dir):
            print(f"Error: Directory '{target_dir}' does not exist.")
            return 1

        if exam_id:
            success = solve_exam(exam_dir, exam_id, model_name, api_key)
            return 0 if success else 1
        else:
            pattern = os.path.join(target_dir, "exam_*.json")
            exam_files = glob.glob(pattern)
            
            if not exam_files:
                print(f"No exam files matching 'exam_*.json' found in '{target_dir}'.")
                return 1

            print(f"Found {len(exam_files)} exam(s) in '{target_dir}'. Starting batch generation...")
            success_count = 0
            for file_path in sorted(exam_files):
                filename = os.path.basename(file_path)
                match = re.match(r"exam_(.+)\.json", filename)
                if match:
                    current_exam_id = match.group(1)
                    if solve_exam(exam_dir, current_exam_id, model_name, api_key):
                        success_count += 1

            print(f"\nBatch complete! Successfully processed {success_count}/{len(exam_files)} exams.")
            return 0 if success_count > 0 else 1

    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())