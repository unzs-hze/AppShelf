"""Build the offline anthology from downloaded, attributed classical sources.

Development only. Supply the three upstream JSON files and LICENSE in --sources;
OpenCC is used only while building, never at application runtime.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

SOURCE_PATHS = {
    'tang300': ('tangshisanbaishou.json', '蒙学/tangshisanbaishou.json', '唐诗三百首'),
    'qianjia': ('qianjiashi.json', '蒙学/qianjiashi.json', '千家诗'),
    'shuimo': ('shuimotangshi.json', '水墨唐诗/shuimotangshi.json', '水墨唐诗'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--opencc-path', type=Path)
    args = parser.parse_args()
    if args.opencc_path:
        sys.path.insert(0, str(args.opencc_path))
    from opencc import OpenCC
    convert = OpenCC('t2s').convert
    repo = Path(__file__).resolve().parent.parent
    seen, works, source_info = set(), [], {}
    for key, (filename, remote, label) in SOURCE_PATHS.items():
        raw = (args.sources / filename).read_bytes()
        payload = json.loads(raw)
        source_info[key] = {'collection': label,
            'url': 'https://github.com/chinese-poetry/chinese-poetry/blob/master/' + remote,
            'sha256': hashlib.sha256(raw).hexdigest()}
        if isinstance(payload, dict):
            poems = [poem for section in payload['content'] for poem in section['content']]
        else:
            poems = payload
        for index, poem in enumerate(poems):
            author = convert(poem['author']).strip()
            dynasty = re.match(r'[（(]([^）)]+)[）)]', author)
            author = re.sub(r'^[（(][^）)]+[）)]', '', author).strip()
            author = {'明皇帝': '李隆基', '玄宗皇帝': '李隆基', '张佑': '张祜',
                      '僧志安': '志南', '张文潜': '张耒', '杜小山': '杜耒',
                      '晁无咎': '晁补之', '高菊卿': '高翥', '耿𣲗': '耿湋'}.get(author, author)
            title = convert(poem.get('title', poem.get('chapter', ''))).strip()
            # One source misattributes this poem and has a first-line variant.
            # Omit it rather than guessing at an unsourced correction.
            if key == 'qianjia' and (title == '送朱大入秦' or author == '张演'):
                continue
            for prefix in ('杂曲歌辞 ', '乐府杂曲 ', '琴曲歌辞 ', '鼓吹曲辞 ', '横吹曲辞 ', '相和歌辞 '):
                title = title.removeprefix(prefix)
            candidates = []
            for line_index, original in enumerate(poem['paragraphs']):
                if not isinstance(original, str):
                    continue
                text = convert(original).strip()
                text = re.sub(r'[（(][^）)]*[）)]\s*$', '', text).strip()
                if text.endswith('，'):
                    text = text[:-1] + '。'
                text = text.translate(str.maketrans({'沈': '沉', '鏁': '锁', '劒': '剑', '汚': '污', '悮': '误'}))
                # Intact, compact couplets only: omit notes, uncertain glyphs,
                # editorial parentheses, Latin placeholders and broken lines.
                if not re.fullmatch(r'[\u4e00-\u9fff]{4,12}，[\u4e00-\u9fff]{4,12}[。！？]', text):
                    continue
                normalized = text.translate(str.maketrans('', '', '，。！？'))
                if normalized in seen:
                    continue
                seen.add(normalized)
                identifier = hashlib.sha256((author + '\0' + title + '\0' + text).encode()).hexdigest()[:16]
                candidates.append({'id': 'poem-' + identifier, 'text': text, 'author': author,
                    'title': title, 'dynasty': dynasty.group(1) if dynasty else '唐',
                    'source': key, 'work': index, 'line': line_index})
            if candidates:
                # Prefer imagery and reflection; distribute across works before
                # taking more from a long poem. Source order breaks score ties.
                candidates.sort(key=lambda item: -sum(character in '春秋山水月风云雨花日夜明清海江湖松竹书琴心归'
                                                       for character in item['text']))
                works.append(candidates)
    selected = []
    for layer in range(4):
        for candidates in works:
            if layer < len(candidates):
                selected.append(candidates[layer])
                if len(selected) == 1000:
                    break
        if len(selected) == 1000:
            break
    if len(selected) != 1000:
        raise ValueError('Not enough distinct complete couplets: ' + str(len(selected)))
    # A deterministic ordering makes provenance reviews and future updates easy.
    selected.sort(key=lambda item: (list(SOURCE_PATHS).index(item['source']), item['work'], item['line']))
    data = repo / 'data' / 'poems.json'
    data.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    source_info['selection'] = {'count': 1000, 'uniqueBy': 'Chinese text without punctuation',
        'method': 'Complete couplets, at most four per source work, balanced across anthology works',
        'conversion': 'OpenCC 0.1.7 t2s; trailing variant notes omitted; couplet punctuation and a small set of variant glyphs normalized',
        'outputSHA256': hashlib.sha256(data.read_bytes()).hexdigest(),
        'sourceCounts': dict(Counter(item['source'] for item in selected))}
    (repo / 'docs' / 'poetry-sources.json').write_text(
        json.dumps(source_info, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    third_party = repo / 'docs' / 'licenses'
    third_party.mkdir(exist_ok=True)
    (third_party / 'chinese-poetry-MIT.txt').write_bytes((args.sources / 'LICENSE').read_bytes())
    print(json.dumps({'entries': len(selected), 'authors': len({item['author'] for item in selected}),
        'works': len({(item['author'], item['title']) for item in selected}),
        'sources': source_info['selection']['sourceCounts'],
        'examples': selected[:3]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
