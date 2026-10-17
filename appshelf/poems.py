"""Offline classical poetry; independent launch rotation from the time quotes."""
import json
import logging
from .config import RESOURCE_ROOT
from .quotes import choose_launch_item

FALLBACK_POEM = {'id': 'poem-fallback', 'text': '长风破浪会有时，直挂云帆济沧海。',
                 'author': '李白', 'title': '行路难·其一', 'dynasty': '唐'}


def load_poems(path=None):
    try:
        pool = json.loads((path or RESOURCE_ROOT / 'data' / 'poems.json').read_text(encoding='utf-8'))
        if (not isinstance(pool, list) or len(pool) != 1000
                or any(not isinstance(item, dict) or any(not isinstance(item.get(key), str)
                           or not item[key].strip() for key in ('id', 'text', 'author', 'title', 'dynasty'))
                       for item in pool)
                or len({item['id'] for item in pool}) != 1000
                or len({item['text'] for item in pool}) != 1000):
            raise ValueError('古诗数据不完整')
        return tuple(pool)
    except (OSError, ValueError, TypeError):
        logging.getLogger('appshelf').warning('内置古诗暂不可用，保留首页默认诗句')
        return (FALLBACK_POEM,)


POEMS = load_poems()


def choose_launch_poem(directory, *, rng=None):
    return dict(choose_launch_item(directory, POEMS, 'home-poems', rng=rng))
