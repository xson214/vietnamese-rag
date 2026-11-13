"""Build an additional immutable experiment generation while the server is stopped."""
import argparse
import json
from dataclasses import replace

from .config import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Experiment JSON config')
    args = parser.parse_args()
    with open(args.config, encoding='utf-8') as handle:
        config = json.load(handle)
    allowed = {'embedding_backend','embedding_model','embedding_revision','reranker_backend',
               'reranker_model','reranker_revision','chunking_strategy','chunk_size','chunk_overlap'}
    unknown = set(config) - allowed - {'description','retrieval_config'}
    if unknown:
        parser.error(f'Unknown config keys: {unknown}')
    settings = replace(Settings(), **{k:v for k,v in config.items() if k in allowed})
    store = Store(settings)
    store.acquire_lease()
    try:
        with store.db() as db:
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
                raise RuntimeError('Có job chưa hoàn tất. Chạy server để hoàn tất trước khi reindex.')
        store._publish()
        version, _ = store.pin(None, None)
        print(json.dumps({'active_index_version': version, 'data_dir': str(settings.data_dir)}))
    finally:
        store.close()


if __name__ == '__main__':
    main()
