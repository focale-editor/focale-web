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
        'index.html': (
            '<!doctype html><html><head>'
            f'<base href="/releases/{tag}/">'
            '<title>Focale</title><link rel="manifest" href="manifest.json">'
            '</head><body><script src="flutter_bootstrap.js" async></script></body></html>'
        ).encode(),
        'flutter_bootstrap.js': b'bootstrap',
        'manifest.json': b'{"start_url":"."}',
        'main.dart.12345678.wasm': b'wasm',
        'main.dart.12345678.js': b'js',
        'workers/focale_worker.1234567890abcdef.js': b'codec',
    }
    for name, extension in (('drift_worker', 'js'), ('sqlite3', 'wasm')):
        data = f'{name}:{tag}'.encode() if name == 'drift_worker' else b'sqlite'
        fingerprint = hashlib.sha256(data).hexdigest()[:16]
        files[f'workers/{name}.{fingerprint}.{extension}'] = data
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
        self.assertEqual((site / 'index.html').read_bytes(), (newer / 'index.html').read_bytes())
        for tag in ('v1.0.0', 'v1.1.0'):
            self.assertTrue((site / 'releases' / tag / 'flutter_bootstrap.js').is_file())
            for worker in (site / 'releases' / tag / 'workers').iterdir():
                if worker.name.startswith(('drift_worker.', 'sqlite3.')):
                    self.assertEqual((site / 'workers' / worker.name).read_bytes(), worker.read_bytes())
        self.assertEqual(len(list((site / 'workers').iterdir())), 3)
        self.assertEqual((site / 'CNAME').read_text(), 'web.focale-editor.app\n')

    def test_root_serves_the_verified_app_without_a_redirect(self):
        metadata = self.pack()
        site = self.root / 'site'
        package.stage(self.output, 'v1.0.0', site)
        self.assertEqual(package.digest(site / 'index.html'), metadata['files']['index.html']['sha256'])
        html = (site / 'index.html').read_text()
        self.assertIn('<base href="/releases/v1.0.0/">', html)
        self.assertIn('<script src="flutter_bootstrap.js"', html)
        self.assertNotIn('http-equiv="refresh"', html)
        self.assertFalse((site / 'flutter_bootstrap.js').exists())
        for worker in (self.source / 'workers').iterdir():
            if worker.name.startswith(('drift_worker.', 'sqlite3.')):
                self.assertEqual((site / 'workers' / worker.name).read_bytes(), worker.read_bytes())

    def test_truncated_archive_is_rejected_without_partial_site(self):
        metadata = self.pack()
        archive = self.output / metadata['archive']
        archive.write_bytes(archive.read_bytes()[:-10])
        with self.assertRaisesRegex(ValueError, 'checksum or size'):
            package.stage(self.output, 'v1.0.0', self.root / 'site')
        self.assertFalse((self.root / 'site').exists())

    def test_conflicting_database_worker_paths_are_rejected(self):
        self.pack()
        newer = self.root / 'newer'
        fixture(newer, 'v1.1.0')
        worker = next((newer / 'workers').glob('drift_worker.*.js'))
        reused_name = next((self.source / 'workers').glob('drift_worker.*.js')).name
        worker.rename(worker.with_name(reused_name))
        manifest = json.loads((newer / 'precache_manifest.json').read_text())
        for entry in manifest['entries']:
            if entry['url'] == f'workers/{worker.name}':
                entry['url'] = f'workers/{reused_name}'
        package.write_json(newer / 'precache_manifest.json', manifest)
        package.pack(newer, self.root / 'new-package', '1.1.0+2', 'v1.1.0', SHA)
        with self.assertRaisesRegex(ValueError, 'conflicting database worker'):
            package.stage(self.root / 'new-package', 'v1.1.0', self.root / 'site', self.output, 'v1.0.0')
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
