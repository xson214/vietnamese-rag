"""Regression for slide line wraps: source offsets stay raw, answer stays whole."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.generation import Generator


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/az_wrapped_text.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('question', ['Availability Zone là gì?', FIXTURE['question']])
def test_az_definition_does_not_stop_at_pdf_line_break(question):
    text = FIXTURE['text']
    hit = {
        'chunk_id': 'az-page-nine', 'document_id': 'az-doc', 'document_version': 1,
        'filename': 'aws-slide.pdf', 'text': text,
        'source_spans': [{'page_number': FIXTURE['page_number'], 'start_offset': 0,
                          'end_offset': len(text), 'quote': text}],
    }
    settings = SimpleNamespace(generation_backend='extractive', context_char_budget=12000)
    response = Generator(settings).answer(question, [hit], {})
    assert response['status'] == 'answered'
    answer = re.sub(r'\s+', ' ', response['answer'])
    for fragment in FIXTURE['expected_fragments']:
        assert fragment in answer
    for fragment in FIXTURE['forbidden_answer_fragments']:
        assert fragment not in answer
    assert FIXTURE['expected_definition'] in answer
    for citation in response['citations']:
        start, end = citation['source_span']['start_offset'], citation['source_span']['end_offset']
        assert citation['quote'] == text[start:end]
        assert citation['page_number'] == FIXTURE['page_number']
    assert response['confidence'] is None
