import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import load  # noqa: E402

ppt = load("ppt-generation")


def test_generate_ppt_reads_bom_plan(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(
        '{"aspect_ratio":"16:9","slides":[{"title":"Smoke","key_points":["bom"]}]}',
        encoding="utf-8-sig",
    )
    slide = tmp_path / "slide.png"
    Image.new("RGB", (1280, 720), (38, 99, 235)).save(slide)
    output = tmp_path / "deck.pptx"

    msg = ppt.generate_ppt(str(plan), [str(slide)], str(output))

    assert "Successfully generated presentation" in msg
    deck = Presentation(output)
    assert len(deck.slides) == 1
