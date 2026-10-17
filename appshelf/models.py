"""Validation and the canonical path model, independent of HTTP and storage."""
import copy
import datetime as dt
import hashlib
import math
import ntpath
import re

CATEGORIES = frozenset('sys-asus sys-hw sys-os dev-ide dev-lang dev-db dev-tool dev-net ai-code ai-tool off-doc off-media net-web net-im net-tool game-plat game-app game-tool lib-rt lib-ac tool-sys'.split())
PATH_START = re.compile(r'^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)')
DOMAIN = re.compile(r'^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$')


class ValidationError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def normalize_path(value):
    if not isinstance(value, str):
        raise ValidationError('请填写完整的磁盘或共享目录路径', 'path')
    value = value.strip().strip('"')
    if not PATH_START.match(value):
        raise ValidationError('请填写完整的磁盘或共享目录路径', 'path')
    if '\x00' in value or any(ord(c) < 32 for c in value):
        raise ValidationError('路径包含无效字符', 'path')
    result = ntpath.normpath(value.strip().strip('"').replace('/', '\\'))
    if any(c in result[2:] for c in '<>"|?*') or ':' in result[2:]:
        raise ValidationError('路径包含无效字符', 'path')
    return result


def parse_locations(text):
    """Import the old display string once; retain explanatory text as notes."""
    if not isinstance(text, str):
        raise ValidationError('路径必须是文本', 'path')
    locations = []
    seen = set()
    for segment in re.split(r'[·\n\r]+', text):
        segment = segment.strip().strip('"')
        if not segment:
            continue
        note = ''
        candidate = segment
        # Old Steam data embeds an additional library path in parentheses.
        library = re.search(r'（游戏库\s*([^）]+)）', candidate)
        extra = library.group(1).strip() if library else None
        annotated = re.match(r'^(.*?)(?:（([^）]*)）|\s+—\s+(.*))$', candidate)
        if annotated and PATH_START.match(annotated.group(1)):
            candidate = annotated.group(1).strip()
            note = annotated.group(2) or annotated.group(3) or ''
        if PATH_START.match(candidate):
            path = normalize_path(candidate)
            key = ntpath.normcase(path)
            if key not in seen:
                locations.append({'path': path, 'kind': 'unknown', 'note': note})
                seen.add(key)
        else:
            locations.append({'path': '', 'kind': 'unknown', 'note': segment})
        if extra and PATH_START.match(extra):
            path = normalize_path(extra)
            key = ntpath.normcase(path)
            if key not in seen:
                locations.append({'path': path, 'kind': 'directory', 'note': '游戏库'})
                seen.add(key)
    return locations


def validate_locations(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValidationError('路径列表格式无效（最多 100 项）', 'paths')
    out, seen = [], set()
    for loc in value:
        if not isinstance(loc, dict) or set(loc) - {'path', 'kind', 'note'}:
            raise ValidationError('路径列表格式无效', 'paths')
        path, kind, note = loc.get('path', ''), loc.get('kind', 'unknown'), loc.get('note', '')
        if not isinstance(path, str) or not isinstance(note, str) or len(path) > 32767 or len(note) > 2000:
            raise ValidationError('路径或说明格式无效', 'paths')
        if kind not in ('directory', 'file', 'unknown'):
            raise ValidationError('路径类型无效', 'paths')
        path = normalize_path(path) if path else ''
        if not path and not note.strip():
            continue
        key = (ntpath.normcase(path), note.strip())
        if key not in seen:
            out.append({'path': path, 'kind': kind, 'note': note.strip()})
            seen.add(key)
    return out


def display_path(locations):
    return ' · '.join((x['path'] + (f"（{x['note']}）" if x.get('note') else '')) if x.get('path') else x.get('note', '') for x in locations)


def paths_of(app_or_path):
    if isinstance(app_or_path, dict):
        locations = app_or_path.get('paths')
        if locations is None:
            locations = parse_locations(app_or_path.get('path', ''))
    else:
        locations = parse_locations(app_or_path or '')
    return [x['path'] for x in locations if x.get('path')]


def migrate_app(app):
    if not isinstance(app, dict) or not isinstance(app.get('name'), str):
        raise ValidationError('应用清单包含无效条目')
    a = copy.deepcopy(app)
    if not a.get('id'):
        a['id'] = hashlib.sha256((a['name'] + '\n' + a.get('path', '')).encode()).hexdigest()[:16]
    a['paths'] = validate_locations(a['paths']) if 'paths' in a else parse_locations(a.get('path', ''))
    a['path'] = display_path(a['paths'])
    if a.get('status') == 'removed' and not a.get('registryId') and not a.get('removalConfirmed'):
        a['status'] = 'missing'
    return a


def validate_patch(patch):
    if not isinstance(patch, dict):
        raise ValidationError('修改内容必须是对象')
    allowed = {'name', 'category', 'site', 'description', 'path', 'paths', 'size', 'source', 'installDate', 'group'}
    if set(patch) - allowed:
        raise ValidationError('修改内容包含不允许的字段')
    out = copy.deepcopy(patch)
    for key, limit in [('name', 300), ('description', 20000), ('site', 253), ('group', 200), ('path', 64000)]:
        if key not in out:
            continue
        if key == 'group' and out[key] is None:
            continue
        if not isinstance(out[key], str) or len(out[key]) > limit or '\x00' in out[key]:
            raise ValidationError(f'{key} 格式无效', key)
        out[key] = out[key].strip()
        if key in ('name', 'description') and not out[key]:
            raise ValidationError('名称和介绍不能为空', key)
    if 'category' in out and (not isinstance(out['category'], str) or out['category'] not in CATEGORIES):
        raise ValidationError('分类无效', 'category')
    if 'source' in out and out['source'] not in ('bundled', 'downloaded', 'unknown'):
        raise ValidationError('来源无效', 'source')
    if 'site' in out and out['site'] and not DOMAIN.fullmatch(out['site']):
        raise ValidationError('官网请填写域名，例如 example.com', 'site')
    if 'size' in out and out['size'] is not None:
        value = out['size']
        if isinstance(value, bool) or not isinstance(value, (float, int)) or value < 0 or value > 2**63 - 1 or not math.isfinite(value):
            raise ValidationError('大小必须是非负数', 'size')
        out['size'] = round(value)
    if out.get('installDate') is not None:
        value = out['installDate']
        try:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError
            dt.date.fromisoformat(value)
        except ValueError:
            raise ValidationError('安装日期无效', 'installDate') from None
    if 'paths' in out:
        out['paths'] = validate_locations(out['paths'])
        out['path'] = display_path(out['paths'])
    elif 'path' in out:
        out['paths'] = parse_locations(out['path'])
        out['path'] = display_path(out['paths'])
    return out
