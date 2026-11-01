from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleasePreparationTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / 'publish_release.ps1').read_text(encoding='utf-8')
        self.ignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
        self.notes = (ROOT / 'release_notes.md').read_text(encoding='utf-8')

    def test_signing_requires_clean_exact_source_commit_and_matching_draft(self):
        self.assertIn('[Parameter(Mandatory=$true)][string]$SourceCommit', self.script)
        self.assertIn('git -C $root rev-parse HEAD', self.script)
        self.assertIn('git -C $root status --porcelain', self.script)
        self.assertIn('releases/$ReleaseId', self.script)
        self.assertIn('$remoteRelease.tag_name -cne $tag', self.script)
        self.assertIn('-not $remoteRelease.draft', self.script)
        self.assertIn('$remoteRelease.target_commitish -ine $SourceCommit', self.script)

    def test_release_upload_contains_only_the_four_signed_assets(self):
        upload = next(line for line in self.script.splitlines() if 'gh release upload ' in line)
        assets = re.findall(r"Join-Path \$releaseRoot '([^']+)'", upload)
        self.assertEqual(assets, [
            'Kam3Tweaks.exe', 'Kam3TweaksUpdater.exe',
            'update-manifest.json', 'update-manifest.sig',
        ])
        self.assertNotIn('gh push', self.script.casefold())
        self.assertIn('gh release edit $tag --draft=false', self.script)

    def test_private_and_generated_release_material_is_ignored(self):
        for pattern in ('*.pem', '*.key', '*.p12', '*.pfx', '*.enc', '*.sig',
                        '.env', '.env.*', '/release_assets/', '/candidate_*/',
                        '/build*/', '/dist/', '/backup/', 'tests/pcboost-test-data-*/'):
            self.assertIn(pattern, self.ignore)

    def test_release_notes_have_required_heading_and_scope(self):
        self.assertTrue(self.notes.startswith('# Kam3 Tweaks 4.7.0 release notes\n'))
        for phrase in ('purple bento', 'Gaming, Performance, and Balanced',
                       'DNS configuration', 'pointer acceleration', 'Windows UI effects',
                       'Network information', 'Undo', 'administrator'):
            self.assertIn(phrase.casefold(), self.notes.casefold())


if __name__ == '__main__':
    unittest.main()
