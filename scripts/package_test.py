"""Exercise byte integrity, safe extraction and retention across releases."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import package

SHA = 'a' * 40


def fixture(directory, tag='v1.0.0'):
    """Create a minimal dual-backend distribution with real precache checksums."""
    files = {
        'index.html': f'<base href="/releases/{tag}/">'.encode(),
        'flutter_bootstrap.js': b'bootstrap',
        'manifest.json': b'{"start_url":"."}',
        'main.dart.12345678.wasm': b'wasm',
        'main.dart.12345678.js': b'js',
        'workers/focale_worker.1234567890abcdef.js': b'codec',
        'workers/drift_worker.1234567890abcdef.js': b'drift',
        'workers/sqlite3.1234567890abcdef.wasm': b'sqlite',
    }
    for name in ('chromalib', 'imcodec_native', 'rawkit', 'textshaperlib'):
        files[f'runtimes/1234567890abcdef/{name}/{name}.wasm'] = name.encode()
    entries = []
    for name, data in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append({'url': name, 'hash': hashlib.sha256(data).hexdigest()[:8], 'size': len(data)})
    package.write_json(directory / 'precache_manifest.json', {'version': 1, 'entries': entries})


class PackageTests(unittest.TestCase):
    """Verify the publication boundary using real ZIP files and temporary sites."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.output = self.root / 'package'
        fixture(self.source)

    def pack(self, output=None):
        return package.pack(self.source, output or self.output, '1.0.0+1', 'v1.0.0', SHA)

    def test_deterministic_package_and_installed_shortcut_use_current_release(self):
        first = self.pack()
        second = self.pack(self.root / 'second')
        self.assertEqual(first, second)
        restored = self.root / 'restored'
        package.extract(self.output, 'v1.0.0', restored)
        self.assertEqual(json.loads((restored / 'manifest.json').read_text())['start_url'], '/')
        self.assertEqual((self.source / 'manifest.json').read_text(), '{"start_url":"."}')

    def test_build_bookkeeping_and_maps_are_not_published(self):
        for name in ('.last_build_id', 'flutter.js.map', 'focale_worker.js.deps'):
            (self.source / name).write_text('private source path')
        metadata = self.pack()
        self.assertFalse(any(package.build_only(name) for name in metadata['files']))

    def test_current_and_previous_complete_releases_survive_staging(self):
        self.pack()
        newer = self.root / 'newer'
        fixture(newer, 'v1.1.0')
        package.pack(newer, self.root / 'new-package', '1.1.0+2', 'v1.1.0', 'b' * 40)
        site = self.root / 'site'
        package.stage(self.root / 'new-package', 'v1.1.0', site, self.output, 'v1.0.0')
        self.assertIn('/releases/v1.1.0/', (site / 'index.html').read_text())
        for tag in ('v1.0.0', 'v1.1.0'):
            self.assertTrue((site / 'releases' / tag / 'flutter_bootstrap.js').is_file())
        self.assertEqual((site / 'CNAME').read_text(), 'web.focale-editor.app\n')

    def test_truncated_archive_is_rejected_without_partial_site(self):
        metadata = self.pack()
        archive = self.output / metadata['archive']
        archive.write_bytes(archive.read_bytes()[:-10])
        with self.assertRaisesRegex(ValueError, 'checksum or size'):
            package.stage(self.output, 'v1.0.0', self.root / 'site')
        self.assertFalse((self.root / 'site').exists())

    def test_changed_member_is_rejected_even_when_archive_hash_is_updated(self):
        metadata = self.pack()
        archive = self.output / metadata['archive']
        with zipfile.ZipFile(archive) as source:
            entries = [(info, source.read(info)) for info in source.infolist()]
        with zipfile.ZipFile(archive, 'w') as target:
            for info, data in entries:
                target.writestr(info, b'X' * len(data) if info.filename.endswith('.wasm') else data)
        metadata.update(size=archive.stat().st_size, sha256=package.digest(archive))
        package.write_json(self.output / package.names('v1.0.0')[1], metadata)
        with self.assertRaisesRegex(ValueError, 'member checksum'):
            package.extract(self.output, 'v1.0.0', self.root / 'verified')
        self.assertFalse((self.root / 'verified').exists())

    def test_unsafe_paths_and_private_source_are_rejected(self):
        for name in (
            '../escape',
            '/escape',
            'a/../escape',
            'a//b',
            'a\\b',
            '%2e%2e/a',
            '.env',
            'main.dart',
            'main.js.map',
            'worker.js.deps',
            'a/.git/config',
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.safe_path(name)
        (self.source / 'private.dart').write_text('source')
        with self.assertRaisesRegex(ValueError, 'private browser asset'):
            self.pack()

    def test_symlink_and_wrong_base_path_are_rejected(self):
        (self.source / 'linked.txt').symlink_to(self.source / 'index.html')
        with self.assertRaisesRegex(ValueError, 'regular browser'):
            self.pack()
        (self.source / 'linked.txt').unlink()
        (self.source / 'index.html').write_text('<base href="/">')
        with self.assertRaisesRegex(ValueError, 'base path'):
            self.pack()

    def test_size_budget_is_checked_for_retained_history(self):
        metadata = self.pack()
        total = sum(item['size'] for item in metadata['files'].values())
        newer = self.root / 'newer'
        fixture(newer, 'v1.1.0')
        package.pack(newer, self.root / 'new-package', '1.1.0+2', 'v1.1.0', SHA)
        with (
            patch.object(package, 'MAX_SITE_BYTES', total + 100),
            self.assertRaisesRegex(ValueError, 'previous releases'),
        ):
            package.stage(self.root / 'new-package', 'v1.1.0', self.root / 'site', self.output, 'v1.0.0')
        self.assertFalse((self.root / 'site').exists())

    def test_missing_worker_and_duplicate_manifest_entries_are_rejected(self):
        path = self.source / 'precache_manifest.json'
        manifest = json.loads(path.read_text())
        manifest['entries'].append(manifest['entries'][0])
        package.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.pack()
        manifest['entries'] = [entry for entry in manifest['entries'][:-1] if 'focale_worker' not in entry['url']]
        package.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'Missing versioned runtime'):
            self.pack()


if __name__ == '__main__':
    unittest.main()
