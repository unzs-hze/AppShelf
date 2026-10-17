"""Optional build-time publisher favicon cache; requires Pillow and HTTPS access."""
import concurrent.futures
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
# Use a separate encoder so this tool also works without Win32 icon extraction.
import base64


class IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'link' and 'icon' in attrs.get('rel', '').lower() and attrs.get('href'):
            self.links.append(attrs['href'])


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 AppShelf-icon-cache'})
    with urllib.request.urlopen(request, timeout=5) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Image too large')
        return data, response.geturl()


def icon(site):
    for base in [f'https://{site}/', f'https://www.{site}/'] if not site.startswith('www.') else [f'https://{site}/']:
        candidates = [urllib.parse.urljoin(base, 'favicon.ico')]
        try:
            html, page = download(base)
            parser = IconLinks()
            parser.feed(html.decode('utf-8', errors='ignore'))
            candidates = [urllib.parse.urljoin(page, href) for href in parser.links[-4:]] + candidates
        except Exception:
            pass
        for url in dict.fromkeys(candidates):
            if urllib.parse.urlsplit(url).scheme != 'https':
                continue
            try:
                raw, actual = download(url)
                image = Image.open(io.BytesIO(raw)).convert('RGBA')
                image.thumbnail((64, 64))
                if min(image.size) < 8 or not image.getchannel('A').getbbox():
                    continue
                out = io.BytesIO()
                image.save(out, format='PNG', optimize=True)
                return site, 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode(), actual
            except Exception:
                continue
    return site, None, None


def main():
    target = ROOT / 'assets' / 'logos.js'
    text = target.read_text(encoding='utf-8')
    logos = json.loads(text.split('const APP_LOGOS = ', 1)[1].rsplit(';', 1)[0])
    apps = json.loads((ROOT / 'data' / 'apps.json').read_text(encoding='utf-8-sig'))
    sites = sorted({a.get('site') for a in apps if a.get('site') and a.get('site') not in logos['bySite']})
    sources = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for site, data, url in pool.map(icon, sites):
            if data:
                logos['bySite'][site] = data
                sources[site] = url
    target.write_text('/* Offline logos: installed application icons and official website favicons. */\nconst APP_LOGOS = ' + json.dumps(logos, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    (ROOT / 'assets' / 'web-icon-sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'downloaded': len(sources), 'covered': sum(a['name'].casefold().strip() in logos['byName'] or a.get('site', '').casefold() in logos['bySite'] for a in apps), 'total': len(apps)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
