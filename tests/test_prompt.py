from __future__ import annotations

from nexus.prompt import system_prompt


def test_prompt_states_native_pdf_and_image_reading():
    prompt = system_prompt()

    assert "Native file reading" in prompt
    assert "Do not convert a PDF or image" in prompt
    assert "read_file returns text, and opens images/PDFs as native visual content" in prompt


def test_prompt_requires_python_for_complex_math():
    prompt = system_prompt()

    assert "Use Python for complex math" in prompt
    assert "write and run a short script in the sandbox" in prompt
