#!/usr/bin/env python3
"""Publish immutable web assets and prepare the latest release for GitHub Pages."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package


def run(*arguments):
    """Run GitHub CLI commands without shell interpolation."""
    result = subprocess.run([str(value) for value in arguments], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'GitHub command failed with exit code {result.returncode}.')
    return result.stdout


def releases():
    """Read every release, including drafts needed for interrupted uploads."""
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp', f'repos/{package.REPOSITORY}/releases?per_page=100'))
    return [release for page in pages for release in page]


def version_key(tag):
    """Compare numeric application versions rather than release creation dates."""
    package.names(tag)
    return tuple(int(part) for part in tag.removeprefix('v').split('.'))


def stable_releases(items):
    """Select stable releases in descending numeric order."""
    stable = [item for item in items if not item['draft'] and not item['prerelease']]
    return sorted(stable, key=lambda item: version_key(item['tag_name']), reverse=True)


def download(tag, directory):
    """Download only the canonical archive and manifest, never arbitrary assets."""
    directory.mkdir(parents=True)
    archive, metadata = package.names(tag)
    run(
        'gh',
        'release',
        'download',
        tag,
        '--repo',
        package.REPOSITORY,
        '--pattern',
        archive,
        '--pattern',
        metadata,
        '--dir',
        directory,
    )


def publish(directory, version, tag, source_sha):
    """Publish verified stable bytes idempotently, then request Pages deployment."""
    expected = package.identity(version, tag, source_sha)
    metadata = package.read_metadata(directory, tag)
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError('Web build does not match the immutable source release.')
    if json.loads(run('gh', 'api', f'repos/{package.REPOSITORY}'))['private']:
        raise ValueError('The web distribution repository must be public.')
    items = releases()
    stable = stable_releases(items)
    if stable and version_key(stable[0]['tag_name']) > version_key(tag):
        raise ValueError('Refusing to publish an older web release.')
    existing = next((item for item in items if item['tag_name'] == tag), None)
    archive_name, metadata_name = package.names(tag)
    with tempfile.TemporaryDirectory(prefix='focale-web-publication-') as temporary:
        work = Path(temporary)
        package.extract(directory, tag, work / 'verified')
        if existing:
            if existing['prerelease']:
                raise ValueError('A prerelease cannot replace the stable web channel.')
            asset_names = {asset['name'] for asset in existing['assets']}
            if asset_names == {archive_name, metadata_name}:
                download(tag, work / 'existing')
                published = package.read_metadata(work / 'existing', tag)
                if published != metadata:
                    raise ValueError('Published web release bytes are immutable.')
            elif not existing['draft']:
                raise ValueError('Published web release is incomplete; refusing mutation.')
            else:
                # A partial draft has never been deployed and can be repaired.
                run(
                    'gh',
                    'release',
                    'upload',
                    tag,
                    '--repo',
                    package.REPOSITORY,
                    '--clobber',
                    directory / archive_name,
                    directory / metadata_name,
                )
        else:
            notes = work / 'notes.md'
            notes.write_text(
                f'Focale {version} for the browser.\n\n'
                f'[Open Focale](https://{package.DOMAIN}) · '
                f'[Release notes](https://github.com/focale-editor/get-focale/releases/tag/{tag})\n'
            )
            run(
                'gh',
                'release',
                'create',
                tag,
                '--repo',
                package.REPOSITORY,
                '--target',
                'main',
                '--draft',
                '--title',
                f'Focale v{tag.removeprefix("v")}',
                '--notes-file',
                notes,
            )
            run(
                'gh',
                'release',
                'upload',
                tag,
                '--repo',
                package.REPOSITORY,
                directory / archive_name,
                directory / metadata_name,
            )
        # Recheck after upload so a delayed publication cannot mark an older release latest.
        newest = stable_releases(releases())
        if newest and version_key(newest[0]['tag_name']) > version_key(tag):
            raise ValueError('A newer web release was published while uploading.')
        run('gh', 'release', 'edit', tag, '--repo', package.REPOSITORY, '--draft=false', '--latest')
        run('gh', 'workflow', 'run', 'pages.yml', '--repo', package.REPOSITORY, '--ref', 'main', '-f', f'tag={tag}')


def fetch(tag, output):
    """Stage the latest stable release and its immediate predecessor."""
    stable = stable_releases(releases())
    if not stable or stable[0]['tag_name'] != tag:
        raise ValueError('Only the latest stable web release may be deployed.')
    with tempfile.TemporaryDirectory(prefix='focale-web-download-') as temporary:
        work = Path(temporary)
        download(tag, work / 'current')
        previous_tag = stable[1]['tag_name'] if len(stable) > 1 else None
        if previous_tag:
            download(previous_tag, work / 'previous')
        package.stage(work / 'current', tag, output, work / 'previous' if previous_tag else None, previous_tag)
    # Fail before uploading Pages if another publication superseded this run.
    if stable_releases(releases())[0]['tag_name'] != tag:
        raise ValueError('A newer web release is ready; deploy that release instead.')


def main():
    """Expose local packaging/verification separately from remote publication."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('pack', 'publish', 'verify', 'stage', 'fetch'):
        child = commands.add_parser(command)
        child.add_argument('--tag', required=True)
        if command != 'fetch':
            child.add_argument('--input', type=Path, required=True)
        if command in ('pack', 'publish'):
            child.add_argument('--version', required=True)
            child.add_argument('--source-sha', required=True)
        if command in ('pack', 'stage', 'fetch'):
            child.add_argument('--output', type=Path, required=True)
        if command == 'stage':
            child.add_argument('--previous', type=Path)
            child.add_argument('--previous-tag')
    arguments = parser.parse_args()
    if arguments.command == 'pack':
        package.pack(arguments.input, arguments.output, arguments.version, arguments.tag, arguments.source_sha)
    elif arguments.command == 'publish':
        publish(arguments.input, arguments.version, arguments.tag, arguments.source_sha)
    elif arguments.command == 'verify':
        with tempfile.TemporaryDirectory() as temporary:
            package.extract(arguments.input, arguments.tag, Path(temporary) / 'verified')
    elif arguments.command == 'stage':
        if bool(arguments.previous) != bool(arguments.previous_tag):
            parser.error('--previous and --previous-tag must be supplied together')
        package.stage(arguments.input, arguments.tag, arguments.output, arguments.previous, arguments.previous_tag)
    else:
        if os.environ.get('GITHUB_REPOSITORY', package.REPOSITORY) != package.REPOSITORY:
            raise ValueError('Pages must run in the canonical web repository.')
        fetch(arguments.tag, arguments.output)


if __name__ == '__main__':
    main()
