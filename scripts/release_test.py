"""Exercise publication retries and protection against stale deployments."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import package
from package_test import fixture, SHA
import release


class ReleaseTests(unittest.TestCase):
    """Use fake GitHub responses around real verified packages."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fixture(self.root / 'source')
        self.input = self.root / 'input'
        package.pack(self.root / 'source', self.input, '1.0.0+1', 'v1.0.0', SHA)
        self.current = {
            'tag_name': 'v1.0.0',
            'draft': False,
            'prerelease': False,
            'assets': [{'name': name} for name in package.names('v1.0.0')],
        }

    def test_retry_reuses_identical_published_assets_and_requests_pages(self):
        def download(tag, directory):
            shutil.copytree(self.input, directory)

        with (
            patch.object(release, 'releases', return_value=[self.current]),
            patch.object(release, 'download', side_effect=download),
            patch.object(release, 'run', return_value='{"private":false}') as run,
        ):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', SHA)
        commands = [call.args for call in run.call_args_list]
        self.assertFalse(any(command[:3] == ('gh', 'release', 'upload') for command in commands))
        self.assertEqual(commands[-1][:4], ('gh', 'workflow', 'run', 'pages.yml'))

    def test_first_release_is_uploaded_as_draft_before_publication(self):
        with (
            patch.object(release, 'releases', return_value=[]),
            patch.object(release, 'run', return_value='{"private":false}') as run,
        ):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', SHA)
        commands = [call.args for call in run.call_args_list]
        self.assertEqual(commands[1][:3], ('gh', 'release', 'create'))
        self.assertIn('--draft', commands[1])
        self.assertEqual(commands[2][:3], ('gh', 'release', 'upload'))
        self.assertNotIn('--clobber', commands[2])
        self.assertIn('--draft=false', commands[3])
        self.assertEqual(commands[4][:4], ('gh', 'workflow', 'run', 'pages.yml'))

    def test_pages_fetch_stages_both_versions_and_checks_latest_again(self):
        newer_source = self.root / 'newer-source'
        newer_input = self.root / 'newer-input'
        fixture(newer_source, 'v1.1.0')
        package.pack(newer_source, newer_input, '1.1.0+2', 'v1.1.0', SHA)
        newer = {**self.current, 'tag_name': 'v1.1.0'}

        def download(tag, directory):
            shutil.copytree(newer_input if tag == 'v1.1.0' else self.input, directory)

        with (
            patch.object(release, 'releases', return_value=[self.current, newer]) as releases,
            patch.object(release, 'download', side_effect=download),
        ):
            release.fetch('v1.1.0', self.root / 'site')
        self.assertEqual(releases.call_count, 2)
        self.assertEqual({path.name for path in (self.root / 'site/releases').iterdir()}, {'v1.0.0', 'v1.1.0'})

    def test_changed_published_bytes_are_not_overwritten(self):
        def download(tag, directory):
            shutil.copytree(self.input, directory)
            metadata_file = directory / package.names(tag)[1]
            metadata = json.loads(metadata_file.read_text())
            metadata['sourceSha'] = 'b' * 40
            package.write_json(metadata_file, metadata)

        with (
            patch.object(release, 'releases', return_value=[self.current]),
            patch.object(release, 'download', side_effect=download),
            patch.object(release, 'run', return_value='{"private":false}') as run,
            self.assertRaisesRegex(ValueError, 'immutable'),
        ):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', SHA)
        self.assertEqual(run.call_count, 1)

    def test_incomplete_published_release_is_not_repaired(self):
        self.current['assets'] = []
        with (
            patch.object(release, 'releases', return_value=[self.current]),
            patch.object(release, 'run', return_value='{"private":false}') as run,
            self.assertRaisesRegex(ValueError, 'incomplete'),
        ):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', SHA)
        self.assertEqual(run.call_count, 1)

    def test_partial_draft_can_be_resumed(self):
        self.current.update(draft=True, assets=[])
        with (
            patch.object(release, 'releases', return_value=[self.current]),
            patch.object(release, 'run', return_value='{"private":false}') as run,
        ):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', SHA)
        self.assertTrue(any('--clobber' in call.args for call in run.call_args_list))

    def test_wrong_source_identity_is_rejected_before_network_access(self):
        with patch.object(release, 'run') as run, self.assertRaisesRegex(ValueError, 'immutable source'):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', 'b' * 40)
        run.assert_not_called()

    def test_stale_deployment_is_rejected_before_downloading(self):
        newer = {**self.current, 'tag_name': 'v1.10.0'}
        with (
            patch.object(release, 'releases', return_value=[self.current, newer]),
            patch.object(release, 'download') as download,
            self.assertRaisesRegex(ValueError, 'latest stable'),
        ):
            release.fetch('v1.0.0', self.root / 'site')
        download.assert_not_called()

    def test_newer_release_blocks_publication(self):
        newer = {**self.current, 'tag_name': 'v1.10.0'}
        with (
            patch.object(release, 'releases', return_value=[newer]),
            patch.object(release, 'run', return_value='{"private":false}') as run,
            self.assertRaisesRegex(ValueError, 'older web release'),
        ):
            release.publish(self.input, '1.0.0+1', 'v1.0.0', SHA)
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
