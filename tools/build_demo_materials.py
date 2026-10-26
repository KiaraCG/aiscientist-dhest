#!/usr/bin/env python3
"""Regenerate the synthetic example PDF fixtures (requires reportlab).

No real student or instructor exam is read. Use --overwrite only to replace
these specific generated example files. Numeric scoring fixtures are authored,
not predictions from a model.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/minimal_exam"


def pdf(path, sections):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RubricHeading", parent=styles["Heading2"], fontSize=11,
                             leading=15, spaceBefore=15, spaceAfter=7, textColor=colors.HexColor("#173D4C")))
    styles["Normal"].fontSize = 10.5
    styles["Normal"].leading = 15
    story = []
    for kind, text in sections:
        if kind == "page":
            story.append(PageBreak())
        else:
            story.append(Paragraph(escape(text), styles[kind]))
            story.append(Spacer(1, 7))
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(42, 26, "SYNTHETIC EXAMPLE - NOT A REAL EXAM OR STUDENT")
        canvas.drawRightString(A4[0]-42, 26, str(doc.page))
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=42, rightMargin=42,
                      topMargin=42, bottomMargin=44, title="Synthetic exam-scoring example",
                      author="Exam scoring toolkit example").build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--overwrite", action="store_true")
    args=p.parse_args()
    paths=[EXAMPLE/"Rubrics/rubric.pdf", EXAMPLE/"RawExams/Exam001.pdf", EXAMPLE/"RawExams/Exam002.pdf",
           EXAMPLE/"exam_config.json",EXAMPLE/"rubric_manifest.json",
           EXAMPLE/"synthetic_evals/Exam001.json",EXAMPLE/"synthetic_evals/Exam002.json"]
    if not args.overwrite and any(x.exists() for x in paths):
        p.error("Example files exist; use --overwrite to regenerate the synthetic fixtures")
    config={"schema_version":1,"exam_id":"SYNTHETIC_CONSTANT_SPEED_V1","exam_title":"Synthetic constant-speed example",
            "approved_for_scoring":False,
            "paths":{"manifest":"rubric_manifest.json","rubric":"Rubrics/rubric.pdf",
                     "prompt_template":"Prompts/prompt.template.txt","prompt":"Prompts/prompt.txt",
                     "exams":"RawExams","evals":"evals"},
            "filename_pattern":r"^(?:(?:exam|student)_?)?(?P<id>[0-9]+)$", "identity_mode":"numeric",
            "max_combined_pdf_bytes":50000000,
            "rubric_validation":{"mode":"headings","approved_sha256":""},
            "notes":"SYNTHETIC demonstration only. All speeds are constant. The MC key is option 2 (m/s). "
                    "For 2(b), accept correct follow-through from the student's distance in 2(a); do not penalize its arithmetic mistake twice. "
                    "No misconduct penalty or negative marking. No final grade conversion."}
    def item(label,name,maxi,part,problem,mode,**extra):
        return dict(rubric_item=label,rubric_name=name,max_points=maxi,part_id=part,problem_id=problem,
                    score_mode=mode,notes="",dependencies=[],**extra)
    items=[item("1.a.a","Speed unit",1,"1.a","1","allowed",allowed_points=[0,1],correct_option="2",correct_answer="m/s"),
           item("2.a.a","Distance relation",1,"2.a","2","step",score_step=0.5),
           item("2.a.b","Distance evaluation",1,"2.a","2","continuous"),
           item("2.b.a","Time scaling",1,"2.b","2","allowed",allowed_points=[0,1]),
           item("2.b.b","Later distance",2,"2.b","2","step",score_step=0.5)]
    items[-1]["dependencies"]=["2.a.b"]
    items[-1]["notes"]="Follow-through is allowed: a correctly tripled earlier distance receives full credit even if the earlier arithmetic was wrong."
    manifest={"exam_id":config["exam_id"],"expected_total_max_points":6,"items":items}
    for path,data in [(EXAMPLE/"exam_config.json",config),(EXAMPLE/"rubric_manifest.json",manifest)]:
        path.write_text(json.dumps(data,indent=2,ensure_ascii=True)+"\n")
    questions=[("Normal","1(a). Which unit measures speed? Choose one: (1) m; (2) m/s; (3) s; (4) m/s^2."),
               ("Normal","2(a). A cart moves at a constant speed of 4 m/s for 3 s. Find the distance traveled, showing your relation."),
               ("Normal","2(b). At the same speed, how far does it travel in 9 s? Explain the time scaling; you may use your result from 2(a).")]
    rules=["Award 1 only for an unambiguous final selection of option 2, m/s. Wrong, blank or multiple clearly uncancelled choices: 0. For a genuinely ambiguous cancellation, assign provisional 0 and flag review.",
           "Award 1 for distance = speed times time, or an equivalent correct relation. Award 0.5 for an identifiable partly correct relation with a material omission; otherwise 0. A compact evaluated calculation can show the relation.",
           "Award 1 for 12 m with correct arithmetic and units. Partial credit for correct identifiable content with a material omission is allowed within 0..1. This does not remove the independent relation point.",
           "Award 1 for identifying that the time (and distance at constant speed) triples; an explicit multiplication by 3 suffices. Otherwise 0.",
           "Award up to 2 for the later distance: 36 m from correct data, or a correctly tripled earlier distance under follow-through. Use increments of 0.5 for identifiable partially correct content. Do not repeat a deduction for an earlier arithmetic error."]
    sections=[("Title","Synthetic example: constant speed"),("Normal","Combined question sheet and scoring rubric. Five criteria, six points. This is an invented training fixture, not a supplied instructor exam."),*questions]
    for rec,rule in zip(items,rules):
        sections += [("RubricHeading",f"{rec['rubric_item']} - {rec['rubric_name']} - {rec['max_points']} {'point' if rec['max_points']==1 else 'points'}:"),("Normal",rule)]
    pdf(EXAMPLE/"Rubrics/rubric.pdf",sections)
    for n,answers,scores,reason in [
        (1,["1(a): option 2, m/s.","2(a): s = v t = 4 m/s x 3 s = 12 m.","2(b): 9/3 = 3, so the distance triples: 3 x 12 m = 36 m."],[1,1,1,1,2],""),
        (2,["1(a): [synthetic ambiguous final mark between options 2 and 3; no reliable intended choice].",
            "2(a): s = v t = 4 x 3 = 10 m.","2(b): 9/3 = 3, so 3 x my 10 m = 30 m."],[0,1,0,1,2],
         "1.a.a, PDF p. 1: the final selected option is deliberately ambiguous in this synthetic fixture. Check the original response; do not assume the intended correct choice.")]:
        pdf(EXAMPLE/f"RawExams/Exam{n:03d}.pdf",[("Title",f"Synthetic submission {n:03d}"),("Normal","Typed demonstration only; not a real student's work."),*questions,*[("Normal",a) for a in answers]])
        explanations=["PDF p. 1: the final choice is option 2 (m/s)." if n==1 else "PDF p. 1: ambiguous final selection; provisional zero, human review requested.",
                      "PDF p. 1: uses distance = speed times time.",
                      "PDF p. 1: obtains 12 m." if n==1 else "PDF p. 1: 4 x 3 is incorrectly evaluated as 10; relation credit is separate.",
                      "PDF p. 1: identifies a factor of three in the time and distance.",
                      "PDF p. 1: obtains 36 m." if n==1 else "PDF p. 1: correctly triples the earlier 10 m to 30 m; full follow-through credit, without penalizing the arithmetic error again."]
        result={"grades":[dict(rubric_item=i["rubric_item"],rubric_name=i["rubric_name"],max_points=i["max_points"],awarded_points=sc,explanation=e)
                         for i,sc,e in zip(items,scores,explanations)],"human_review_recommended":bool(reason),"human_review_reason":reason}
        (EXAMPLE/f"synthetic_evals/Exam{n:03d}.json").write_text(json.dumps(result,indent=2)+"\n")
    print("Wrote synthetic fixture material only. Run prepare_exam.py to regenerate its prompt.")

if __name__=="__main__":
    main()
