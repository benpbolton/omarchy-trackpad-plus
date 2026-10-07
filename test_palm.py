import importlib.util
from pathlib import Path
import os
import stat
import tempfile
import unittest
from unittest import mock
import fcntl

spec = importlib.util.spec_from_file_location('palm_system', Path(__file__).with_name('palm-system.py'))
palm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(palm)

class PalmRulesTest(unittest.TestCase):
    def test_custom_targets_only_supported_apple_model_and_preserves_unrelated_rules(self):
        original = '[Other device]\nMatchVendor=0x1234\nAttrPalmSizeThreshold=300\n'
        updated = palm.update_rules(original, 700)
        self.assertIn(original, updated)
        self.assertEqual(updated.count('AttrPalmSizeThreshold=700'), 2)
        self.assertIn('MatchVendor=0x004C', updated)
        self.assertIn('MatchVendor=0x05AC', updated)
        self.assertEqual(palm.read_threshold(updated), 700)
        self.assertNotIn('0x06CB', updated)

    def test_restore_removes_only_managed_rules(self):
        original = '[Other device]\nMatchVendor=0x1234\nAttrPalmSizeThreshold=300\n'
        updated = palm.update_rules(palm.update_rules(original, 700), None)
        self.assertIn(original, updated)
        self.assertNotIn('AttrPalmSizeThreshold=700', updated)
        self.assertIsNone(palm.read_threshold(updated))

    def test_adopts_the_existing_trial_without_duplicating_rules(self):
        trial = '[David Apple Magic Trackpad palm rejection]\nMatchUdevType=touchpad\nMatchVendor=0x004C\nMatchProduct=0x0265\nAttrPalmSizeThreshold=700\n\n[David Apple Magic Trackpad USB palm rejection]\nMatchUdevType=touchpad\nMatchVendor=0x05AC\nMatchProduct=0x0265\nAttrPalmSizeThreshold=700\n'
        updated = palm.update_rules(trial, 650)
        self.assertNotIn('[David Apple', updated)
        self.assertEqual(updated.count('AttrPalmSizeThreshold='), 2)
        self.assertEqual(palm.read_threshold(updated), 650)

    def test_existing_manual_override_is_not_overwritten(self):
        original = '[My Apple tweak]\nMatchVendor=0x004C\nMatchProduct=0x0265\nAttrPalmSizeThreshold=750\n'
        with self.assertRaises(ValueError):
            palm.update_rules(original, 700)

    def test_dell_name_only_rule_is_preserved_and_does_not_block_apple(self):
        original = '[Dell palm tweak]\nMatchName=DELL*\nMatchUdevType=touchpad\nAttrPalmSizeThreshold=300\n'
        updated = palm.update_rules(original, 700)
        self.assertIn(original, updated)
        self.assertEqual(palm.read_threshold(updated), 700)

    def test_non_touchpad_and_non_usb_bluetooth_rules_do_not_conflict(self):
        for qualifier in ['MatchUdevType=mouse', 'MatchBus=ps2']:
            original = '[Unrelated rule]\n' + qualifier + '\nAttrPalmSizeThreshold=300\n'
            self.assertIn(original, palm.update_rules(original, 700))

    def test_incomplete_managed_block_is_not_overwritten(self):
        with self.assertRaises(ValueError):palm.update_rules(palm.BEGIN + '\n', 700)

    def test_symlink_and_hardlink_configs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'original'
            source.write_text('')
            link = root / 'link'
            link.symlink_to(source)
            with self.assertRaises(OSError):palm.checked_read(link)
            link.unlink()
            os.link(source, link)
            with self.assertRaises(ValueError):palm.checked_read(link)

    def test_invalid_threshold_is_rejected(self):
        for value in [True, -1, 0, 1021, 700.5, '700']:
            with self.assertRaises(ValueError):palm.update_rules('', value)

    def test_restrictive_umask_does_not_make_saved_rules_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rules'
            old_umask = os.umask(0o077)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                palm.write_contents(fd, palm.update_rules('', 700), 0o644)
            finally:
                os.umask(old_umask)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(palm.read_threshold(path.read_text()), 700)

class PalmApplyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name) / 'local-overrides.quirks'
        original_lstat, original_fstat = Path.lstat, os.fstat
        def root_owned(info):
            fields = list(info)
            fields[4] = 0
            return os.stat_result(fields)
        patches = [mock.patch.object(palm, 'TARGET', self.target),
                   mock.patch.object(os, 'geteuid', return_value=0),
                   mock.patch.object(Path, 'lstat', lambda path: root_owned(original_lstat(path))),
                   mock.patch.object(os, 'fstat', lambda fd: root_owned(original_fstat(fd)))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_apply_preserves_backup_bytes_and_mode_then_noops(self):
        original = '[Dell tweak]\nMatchName=DELL*\nAttrPalmSizeThreshold=300\n'
        self.target.write_text(original)
        self.target.chmod(0o644)
        palm.apply(700)
        backups = list(self.target.parent.glob('*.trackpad-plus-backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original.encode())
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)
        self.assertEqual(palm.read_threshold(self.target.read_text()), 700)
        before = self.target.stat().st_mtime_ns
        palm.apply(700)
        self.assertEqual(self.target.stat().st_mtime_ns, before)
        self.assertEqual(list(self.target.parent.glob('*.trackpad-plus-backup-*')), backups)

    def test_failed_replace_preserves_original_cleans_temporary_and_releases_lock(self):
        original = b'# existing rules\n'
        self.target.write_bytes(original)
        with mock.patch.object(os, 'replace', side_effect=OSError('injected write failure')):
            with self.assertRaises(OSError):palm.apply(700)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(list(self.target.parent.glob('.trackpad-plus-palm-*')), [])
        with open(self.target.parent / '.trackpad-plus-palm.lock', 'r') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):palm.apply(700)
        palm.apply(700)
        self.assertEqual(palm.read_threshold(self.target.read_text()), 700)

if __name__ == '__main__':unittest.main()
