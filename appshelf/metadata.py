"""Conservative product descriptions and metadata from local installation evidence."""
import datetime
import re
from urllib.parse import urlsplit


PRODUCTS = (
    (r'^typora(?:\s+(?:version\s+)?[\d.]+)?$', 'typora', 'off-doc', 'typora.io',
     'Markdown 编辑器，支持即时预览、数学公式、表格和代码块，适合编写笔记与文档。'),
    (r'^天选姬(?:\s+[\d.]+)?$', 'tx-mascot', 'sys-asus', 'asus.com',
     '华硕天选系列的桌面助手，提供桌面角色互动和设备相关功能。'),
    (r'^github cli(?:\s+[\d.]+)?$', 'github-cli', 'dev-tool', 'cli.github.com',
     'GitHub 官方命令行工具，可在终端管理仓库、Issue、Pull Request 和工作流。'),
    (r'^mysql server\s+[\d.]+$', 'mysql-server', 'dev-db', 'mysql.com',
     'MySQL 关系数据库服务端，负责存储和查询数据，可作为本机开发项目的数据库。'),
    (r'^geek(?: uninstaller)?(?:\s+[\d.]+)?$', 'geek', 'tool-sys', 'geekuninstaller.com',
     '便携式软件卸载工具，支持卸载应用并检查残留的文件和注册表记录。'),
    (r'^nvidia app(?:\s+[\d.]+)?$', 'nvidia-app', 'sys-hw', 'nvidia.com',
     'NVIDIA 显卡管理工具，可管理驱动更新、图形设置与游戏相关功能。'),
    (r'^(?:microsoft )?onedrive(?:\s+[\d.]+)?$', 'onedrive', 'net-tool', 'onedrive.com',
     '微软文件同步工具，可同步本机文件与 OneDrive 云端内容。'),
    (r'^(?:oracle vm )?virtualbox(?:\s+[\d.]+)?$', 'virtualbox', 'dev-net', 'virtualbox.org',
     '桌面虚拟机软件，可在本机运行独立的操作系统环境。'),
    (r'^python\s+3\.14(?:\.[\d.]+)?\s*\(64-bit\)$', 'python-314-x64', 'dev-lang', 'python.org',
     'Python 3.14 的 64 位解释器，用于运行 Python 程序与开发工具。'),
    (r'^mysql installer(?: - community)?(?:\s+[\d.]+)?$', 'mysql-installer', 'dev-db', 'mysql.com',
     'MySQL 的安装与配置管理器，可管理本机的 MySQL 产品组件。'),
)
PLACEHOLDER = '扫描发现的应用，介绍待补充。'


def product(name):
    text = str(name or '').strip().casefold()
    return next((p for p in PRODUCTS if re.fullmatch(p[0], text)), None)


def same_product(first, second):
    left, right = product(first), product(second)
    return bool(left and right and left[1] == right[1])


def website(value):
    try:
        host = urlsplit(value if '://' in value else 'https://' + value).hostname or ''
        if re.fullmatch(r'(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,63}', host):
            return host.lower()
    except (TypeError, ValueError):
        pass
    return ''


def calendar_date(value):
    """Accept a calendar date only; file timestamps are not installation dates."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def fill_metadata(app, record, templates=()):
    """Fill evidence-backed gaps while preserving existing catalogue metadata."""
    rule = product(app['name']) or product(record.get('name'))
    template = next((a for a in templates if a is not app and
                     (a['name'].casefold() == app['name'].casefold() or same_product(a['name'], app['name']))
                     and a.get('description') and a['description'] != PLACEHOLDER), None)
    generated = not app.get('description') or app.get('description') == PLACEHOLDER
    if generated:
        app['description'] = template['description'] if template else rule[4] if rule else (
            f"{record.get('publisher') or '本机软件'}发布的应用。" +
            (f"当前安装版本为 {record['ver']}。" if record.get('ver') else '') +
            '用途介绍可在编辑中补充。')
        app['category'] = template.get('category', 'tool-sys') if template else rule[2] if rule else 'tool-sys'
    if not app.get('site'):
        app['site'] = (template or {}).get('site') or (rule[3] if rule else website(record.get('site', '')))
    if not app.get('group') and (rule or template):
        group = (template or {}).get('group') or (rule[1] if rule else None)
        if group:
            app['group'] = group
    for source, target in [('publisher', 'publisher'), ('ver', 'version'), ('discovery', 'discovery'), ('architecture','architecture')]:
        if record.get(source):
            app[target] = record[source]
    if app.get('size') is None and isinstance(record.get('size'), int) and record['size'] >= 0:
        app['size'] = record['size']
        app['sizeSource'] = 'registry' if record.get('registryId') else 'file'
    date = calendar_date(record.get('date'))
    date_source = record.get('dateSource')
    if not isinstance(date_source, str) or not date_source.strip():
        date_source = 'registry' if record.get('registryId') or record.get('discovery') == 'registry' else None
    if not app.get('installDate') and date and date_source:
        app['installDate'] = date
        app['dateSource'] = date_source
    return app
