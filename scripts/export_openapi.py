"""Export the actual FastAPI contract; fail CI when the committed copy drifts."""
import argparse
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'docs' / 'openapi.yaml'
    with tempfile.TemporaryDirectory() as directory:
        schema = create_app(Settings(data_dir=Path(directory))).openapi()
    # FastAPI uses an untyped manual multipart parser to enforce exact fields/size.
    upload = schema['paths']['/api/v1/documents']['post']
    upload['requestBody'] = {'required': True, 'content': {'multipart/form-data': {'schema': {
        'type':'object', 'required':['file'], 'additionalProperties':False,
        'properties': {'file': {'type':'string','format':'binary'}}}}}}
    if args.check:
        if not target.exists() or yaml.safe_load(target.read_text(encoding='utf-8')) != schema:
            raise SystemExit('OpenAPI drift: run python scripts/export_openapi.py')
        print('OpenAPI matches implementation.')
    else:
        target.write_text(yaml.safe_dump(schema, allow_unicode=True, sort_keys=False), encoding='utf-8')
        print(target)


if __name__ == '__main__':
    main()
