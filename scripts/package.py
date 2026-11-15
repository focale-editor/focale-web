"""Package and verify immutable browser releases before staging GitHub Pages."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

REPOSITORY = 'focale-editor/focale-web'
DOMAIN = 'web.focale-editor.app'
MAX_SITE_BYTES = 950 * 1024 * 1024
MAX_FILES = 20000


def digest(path):
    """Hash an artifact without loading its contents into memory."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(version, tag, source_sha):
    """Require the source version, tag and full commit to describe one release."""
    match = re.fullmatch(r'((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\+([1-9]\d*)', version)
    if not match or tag not in (match[1], 'v' + match[1]):
        raise ValueError('Expected a numeric version and its matching source tag.')
    if not re.fullmatch(r'[a-f0-9]{40}', source_sha):
        raise ValueError('Expected a full source commit SHA.')
    return {
        'schemaVersion': 1,
        'version': version,
        'tag': tag,
        'sourceSha': source_sha,
        'basePath': f'/releases/{tag}/',
        'domain': DOMAIN,
    }


def names(tag):
    """Return canonical public archive and metadata names."""
    if not re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag):
        raise ValueError('Invalid release tag.')
    stem = f'focale-{tag.removeprefix("v")}-web'
    return stem + '.zip', stem + '.json'


def safe_path(name):
    """Reject archive traversal, private inputs and platform-dependent paths."""
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in ('', '.', '..') or part.startswith('.') for part in path.parts)
        or re.search(r'[\\\x00-\x20:%?#]', name)
        or path.suffix in ('.dart', '.map')
        or name.endswith('.deps')
    ):
        raise ValueError(f'Unsafe or private browser asset: {name!r}')
    return path


def build_only(name):
    """Identify Flutter's generated build bookkeeping and source maps."""
    return name == '.last_build_id' or name.endswith(('.map', '.deps'))


def write_json(path, value):
    """Write stable metadata for byte-identical publication retries."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def check_app(directory, metadata):
    """Require both compiler backends and the versioned browser runtime manifest."""
    required = ('index.html', 'flutter_bootstrap.js', 'manifest.json', 'precache_manifest.json')
    if any(not (directory / name).is_file() for name in required):
        raise ValueError('Incomplete Flutter browser distribution.')
    if f'<base href="{metadata["basePath"]}">' not in (directory / 'index.html').read_text():
        raise ValueError('Build with the release base path before packaging.')
    if not list(directory.glob('main.dart.*.wasm')) or not list(directory.glob('main.dart.*.js')):
        raise ValueError('Both Wasm and JavaScript fallback bundles are required.')
    manifest = json.loads((directory / 'precache_manifest.json').read_text())
    urls = set()
    for entry in manifest['entries']:
        name = entry['url']
        if build_only(name):
            continue
        safe_path(name)
        path = directory / name
        if name in urls or not path.is_file() or path.stat().st_size != entry['size']:
            raise ValueError(f'Missing, duplicate or changed precache asset: {name}')
        if not digest(path).startswith(entry['hash']):
            raise ValueError(f'Precache checksum differs: {name}')
        urls.add(name)
    for pattern in (
        r'workers/focale_worker\.[a-f0-9]+\.js',
        r'workers/drift_worker\.[a-f0-9]+\.js',
        r'workers/sqlite3\.[a-f0-9]+\.wasm',
        *(
            rf'runtimes/[a-f0-9]+/{name}/.+\.wasm'
            for name in ('chromalib', 'imcodec_native', 'rawkit', 'textshaperlib')
        ),
    ):
        if not any(re.fullmatch(pattern, name) for name in urls):
            raise ValueError(f'Missing versioned runtime: {pattern}')


def pack(directory, output, version, tag, source_sha):
    """Create a deterministic ZIP and per-file manifest from a clean web build."""
    metadata = identity(version, tag, source_sha)
    archive_name, metadata_name = names(tag)
    check_app(directory, metadata)
    paths = sorted(
        path
        for path in directory.rglob('*')
        if (not path.is_dir() or path.is_symlink()) and not build_only(path.relative_to(directory).as_posix())
    )
    if not paths or len(paths) > MAX_FILES:
        raise ValueError('Invalid browser file count.')
    for path in paths:
        safe_path(path.relative_to(directory).as_posix())
        if path.is_symlink() or not path.is_file():
            raise ValueError('Only regular browser files may be published.')
    if sum(path.stat().st_size for path in paths) > MAX_SITE_BYTES:
        raise ValueError('Browser release exceeds the Pages size budget.')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Package output must be empty.')
    metadata['files'] = {}
    manifest = json.loads((directory / 'manifest.json').read_text())
    manifest.update(start_url='/', scope='/', id='/')
    replacements = {'manifest.json': (json.dumps(manifest, indent=2) + '\n').encode()}
    precache = json.loads((directory / 'precache_manifest.json').read_text())
    precache['entries'] = [entry for entry in precache['entries'] if not build_only(entry['url'])]
    for entry in precache['entries']:
        if entry['url'] in replacements:
            data = replacements[entry['url']]
            entry.update(size=len(data), hash=hashlib.sha256(data).hexdigest()[:8])
    replacements['precache_manifest.json'] = (json.dumps(precache, indent=2) + '\n').encode()
    archive_path = output / archive_name
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            name = path.relative_to(directory).as_posix()
            # Installed shortcuts always enter through the current release.
            data = replacements[name] if name in replacements else path.read_bytes()
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
            metadata['files'][name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    metadata.update(archive=archive_name, size=archive_path.stat().st_size, sha256=digest(archive_path))
    write_json(output / metadata_name, metadata)
    return metadata


def read_metadata(directory, tag):
    """Validate the archive manifest before using any of its paths or sizes."""
    archive_name, metadata_name = names(tag)
    metadata = json.loads((directory / metadata_name).read_text())
    expected = identity(metadata['version'], tag, metadata['sourceSha'])
    if any(metadata.get(key) != value for key, value in expected.items()) or metadata['archive'] != archive_name:
        raise ValueError('Browser metadata identity differs.')
    files = metadata['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('Invalid browser manifest file count.')
    for name, entry in files.items():
        safe_path(name)
        if type(entry['size']) is not int or entry['size'] < 0 or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256']):
            raise ValueError('Invalid browser manifest entry.')
    if sum(entry['size'] for entry in files.values()) > MAX_SITE_BYTES:
        raise ValueError('Browser release exceeds the Pages size budget.')
    archive = directory / archive_name
    if (
        archive.is_symlink()
        or not archive.is_file()
        or archive.stat().st_size != metadata['size']
        or digest(archive) != metadata['sha256']
    ):
        raise ValueError('Browser archive checksum or size differs.')
    return metadata


def extract(directory, tag, output):
    """Verify all members before making a release available to Pages."""
    metadata = read_metadata(directory, tag)
    if output.exists():
        raise ValueError('Extraction output must not exist.')
    with zipfile.ZipFile(directory / metadata['archive']) as archive:
        members = archive.infolist()
        if len(members) != len(metadata['files']) or {item.filename for item in members} != set(metadata['files']):
            raise ValueError('Archive members differ from the browser manifest.')
        for item in members:
            safe_path(item.filename)
            entry = metadata['files'][item.filename]
            if (
                stat.S_IFMT(item.external_attr >> 16) != stat.S_IFREG
                or item.file_size != entry['size']
                or item.flag_bits & 1
            ):
                raise ValueError('Invalid browser archive member.')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
            staging = Path(temporary) / 'release'
            staging.mkdir()
            for item in members:
                target = staging / item.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
                if digest(target) != metadata['files'][item.filename]['sha256']:
                    raise ValueError('Browser member checksum differs.')
            check_app(staging, metadata)
            staging.rename(output)
    return metadata


def stage(current, tag, output, previous=None, previous_tag=None):
    """Stage the current and previous complete releases with a stable entry URL."""
    if output.exists():
        raise ValueError('Pages output must not exist.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        site = Path(temporary) / 'site'
        metadata = extract(current, tag, site / 'releases' / tag)
        if previous is not None:
            if previous_tag == tag:
                raise ValueError('Previous release must differ from the current one.')
            extract(previous, previous_tag, site / 'releases' / previous_tag)
        if sum(path.stat().st_size for path in site.rglob('*') if path.is_file()) > MAX_SITE_BYTES:
            raise ValueError('Current and previous releases exceed the Pages size budget.')
        destination = metadata['basePath']
        (site / 'index.html').write_text(
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>Focale</title>\n'
            f'<meta http-equiv="refresh" content="0;url={destination}">\n'
            '</head><body>'
            f'<a href="{destination}">Open Focale</a></body></html>\n'
        )
        (site / 'CNAME').write_text(DOMAIN + '\n')
        (site / '.nojekyll').touch()
        write_json(
            site / 'release.json',
            {key: metadata[key] for key in ('schemaVersion', 'version', 'tag', 'sourceSha', 'basePath', 'domain')},
        )
        site.rename(output)
