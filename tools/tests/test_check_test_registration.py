import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_test_registration


class CheckTestRegistrationTests(unittest.TestCase):
    def test_built_parses_executables_and_strips_extensions(self):
        ninja_output = (
            "tests/video_out_flip_tests: CXX_EXECUTABLE_LINKER__video_out_flip_tests_Release\n"
            "tests/sample_test.exe: CXX_EXECUTABLE_LINKER__sample_test_Release\n"
            "tests\\windows_test.exe: CXX_EXECUTABLE_LINKER__windows_test_Release\n"
            "tests/static_lib.a: CXX_STATIC_LIBRARY_LINKER__static_lib_Release\n"
            "core/relinker/relinker: CXX_EXECUTABLE_LINKER__relinker_Release\n"
            "tests/custom_target: CUSTOM_COMMAND\n"
        )
        mock_proc = MagicMock(stdout=ninja_output)
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            names = check_test_registration.built(Path("build"))
            mock_run.assert_called_once_with(
                ["ninja", "-C", "build", "-t", "targets", "all"],
                capture_output=True, encoding="utf-8", errors="replace", check=True
            )
            self.assertEqual(names, {"video_out_flip_tests", "sample_test", "windows_test"})

    def test_registered_parses_ctest_files(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            sub = build / "sub"
            sub.mkdir()
            (build / "CTestTestfile.cmake").write_text(
                'add_test(NAME test_a COMMAND "tests/sample_test" "--arg")\n'
                'add_test(NAME test_b COMMAND tests\\windows_test.exe)\n',
                encoding="utf-8"
            )
            (sub / "CTestTestfile.cmake").write_text(
                'add_test("test_c" "C:/build/tests/sub_test.exe" "1")\n',
                encoding="utf-8"
            )
            names = check_test_registration.registered(build)
            self.assertLessEqual({"sample_test", "windows_test", "sub_test"}, names)

    def test_main_returns_one_when_no_executables_built(self):
        out = io.StringIO()
        with patch.object(check_test_registration, "built", return_value=set()) as mock_built, \
             patch.object(check_test_registration, "registered", return_value=set()), \
             contextlib.redirect_stdout(out):
            code = check_test_registration.main(["custom_build"])
        self.assertEqual(code, 1)
        mock_built.assert_called_once_with(Path("custom_build"))
        self.assertIn("no test executables found under custom_build", out.getvalue())

    def test_main_list_mode(self):
        out = io.StringIO()
        with patch.object(check_test_registration, "built", return_value={"test_a", "test_b"}), \
             patch.object(check_test_registration, "registered", return_value={"test_a"}), \
             contextlib.redirect_stdout(out):
            code = check_test_registration.main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("run  test_a", out.getvalue())
        self.assertIn("NOT RUN  test_b", out.getvalue())

    def test_main_clean_pass(self):
        out = io.StringIO()
        with patch.object(check_test_registration, "KNOWN_UNRUN", {"known_test"}), \
             patch.object(check_test_registration, "built", return_value={"test_registered", "known_test"}), \
             patch.object(check_test_registration, "registered", return_value={"test_registered"}), \
             contextlib.redirect_stdout(out):
            code = check_test_registration.main([])
        self.assertEqual(code, 0)
        self.assertIn("note: known_test is built and not run, as recorded", out.getvalue())
        self.assertIn("none new", out.getvalue())

    def test_main_reports_fresh_unrun_executables(self):
        out = io.StringIO()
        with patch.object(check_test_registration, "KNOWN_UNRUN", set()), \
             patch.object(check_test_registration, "built", return_value={"test_a", "unregistered_test"}), \
             patch.object(check_test_registration, "registered", return_value={"test_a"}), \
             contextlib.redirect_stdout(out):
            code = check_test_registration.main([])
        self.assertEqual(code, 1)
        self.assertIn("error: unregistered_test is built but no ctest test runs it", out.getvalue())

    def test_main_reports_stale_known_unrun_executables(self):
        out = io.StringIO()
        with patch.object(check_test_registration, "KNOWN_UNRUN", {"stale_test"}), \
             patch.object(check_test_registration, "built", return_value={"stale_test"}), \
             patch.object(check_test_registration, "registered", return_value={"stale_test"}), \
             contextlib.redirect_stdout(out):
            code = check_test_registration.main([])
        self.assertEqual(code, 1)
        self.assertIn("error: stale_test is run by ctest now; remove it from KNOWN_UNRUN", out.getvalue())


if __name__ == "__main__":
    unittest.main()
