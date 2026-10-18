import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launcher", ROOT / "run.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def invoke(self, args, serials):
        devices = [SimpleNamespace(serial=s) for s in serials]
        with patch.object(launcher.adbutils.adb, "device_list", return_value=devices), \
                patch.object(launcher.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            result = launcher.main(args)
        return result, run

    def test_no_device_does_not_start_automation(self):
        result, run = self.invoke(["trial"], [])
        self.assertEqual(result, 1)
        run.assert_not_called()

    def test_multiple_devices_require_serial(self):
        result, run = self.invoke(["trial"], ["phone-a", "phone-b"])
        self.assertEqual(result, 1)
        run.assert_not_called()

    def test_unknown_serial_does_not_start_automation(self):
        result, run = self.invoke(["trial", "--serial", "absent"], ["phone-a"])
        self.assertEqual(result, 1)
        run.assert_not_called()

    def test_check_does_not_start_automation(self):
        result, run = self.invoke(["check"], ["phone-a"])
        self.assertEqual(result, 0)
        run.assert_not_called()

    def test_default_only_opens_activity(self):
        result, run = self.invoke([], ["phone-a"])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0][-3:], ["--serial", "phone-a", "--open-only"])

    def test_trial_uses_selected_device_and_limits_tasks(self):
        result, run = self.invoke(["trial", "--serial", "phone-b"], ["phone-a", "phone-b"])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0][-5:], ["--serial", "phone-b", "--max-tasks", "3", "--skip-race"])

    def test_adb_failure_returns_error_without_starting_automation(self):
        with patch.object(launcher.adbutils.adb, "device_list", side_effect=OSError("ADB unavailable")), \
                patch.object(launcher.subprocess, "run") as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(["check"]), 1)
        run.assert_not_called()

    def test_child_failure_is_reported_to_caller(self):
        with patch.object(launcher.adbutils.adb, "device_list", return_value=[SimpleNamespace(serial="phone-a")]), \
                patch.object(launcher.subprocess, "run", return_value=SimpleNamespace(returncode=2)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(["trial"]), 2)


if __name__ == "__main__":
    unittest.main()
