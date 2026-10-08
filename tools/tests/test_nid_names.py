import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nid_names


class NidNamesTests(unittest.TestCase):
    def test_compute_nid_known_vectors(self):
        vectors = {
            "sceMsgDialogProgressBarSetValue": "wTpfglkmv34",
            "sceKernelExitProcess": "FnBKHp+gr04",
            "sceKernelUsleep": "1jfXLRVzisc",
            "sceVideoOutOpen": "Up36PTk687E",
            "sceVideoOutClose": "uquVH4-Du78",
        }
        for name, expected in vectors.items():
            result = nid_names.compute_nid(name)
            self.assertEqual(result, expected)
            self.assertEqual(len(result), 11)
            self.assertTrue(all(char in nid_names.CHARSET for char in result))

    def test_load_db_reads_file_and_skips_short_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test_db.csv"
            db_path.write_text(
                "wTpfglkmv34 sceMsgDialogProgressBarSetValue\n"
                "\n"
                "single_token\n"
                "1jfXLRVzisc sceKernelUsleep extra_detail\n",
                encoding="utf-8"
            )
            db = nid_names.load_db(db_path)
            self.assertEqual(db, {
                "wTpfglkmv34": "sceMsgDialogProgressBarSetValue",
                "1jfXLRVzisc": "sceKernelUsleep",
            })

    def test_load_db_downloads_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "subdir" / "aerolib.csv"

            def mock_urlretrieve(url, path):
                Path(path).write_text("wTpfglkmv34 sceMsgDialogProgressBarSetValue\n", encoding="utf-8")

            with patch.object(nid_names.urllib.request, "urlretrieve", side_effect=mock_urlretrieve) as mock_retrieve, \
                 contextlib.redirect_stderr(io.StringIO()):
                db = nid_names.load_db(missing_path)
                mock_retrieve.assert_called_once_with(nid_names.DB_URL, str(missing_path))
                self.assertEqual(db, {"wTpfglkmv34": "sceMsgDialogProgressBarSetValue"})

    def test_collect_unknowns_parses_cpp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prx = root / "core" / "libs" / "prx"
            prx.mkdir(parents=True)
            (prx / "sample.cpp").write_text(
                'APS5_EXPORT("wTpfglkmv34", sceMsgDialogUnknown_test);\n'
                'APS5_EXPORT("Up36PTk687E", sceVideoOutOpen);\n',
                encoding="utf-8"
            )
            with patch.object(nid_names, "ROOT", root), patch.object(nid_names, "PRX", prx):
                unknowns = nid_names.collect_unknowns()
                self.assertIn("wTpfglkmv34", unknowns)
                self.assertNotIn("Up36PTk687E", unknowns)
                self.assertTrue(unknowns["wTpfglkmv34"].endswith("sample.cpp:sceMsgDialogUnknown_test"))

    def test_collect_real_names_parses_definitions_and_strips_postfix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libs = root / "core" / "libs"
            libs.mkdir(parents=True)
            (libs / "sample.cpp").write_text(
                'int APS5_VABI my_function(int a) { return a; }\n'
                'int APS5_VABI hook_nid_postfix(int a) noexcept try { return a; } catch (...) {}\n',
                encoding="utf-8"
            )
            with patch.object(nid_names, "ROOT", root):
                names = nid_names.collect_real_names()
                self.assertEqual(names, {"my_function", "hook_nid_postfix", "hook"})

    def test_main_reports_rename_ready_status(self):
        with tempfile.TemporaryDirectory() as directory:
            db_file = Path(directory) / "aerolib.csv"
            db_file.write_text("wTpfglkmv34 sceMsgDialogProgressBarSetValue\n", encoding="utf-8")
            out = io.StringIO()
            with patch.object(nid_names, "collect_real_names", return_value=set()), \
                 contextlib.redirect_stdout(out):
                code = nid_names.main(["--db", str(db_file), "--nid", "wTpfglkmv34"])
            self.assertEqual(code, 0)
            self.assertIn("rename-ready", out.getvalue())

    def test_main_reports_already_implemented_status(self):
        with tempfile.TemporaryDirectory() as directory:
            db_file = Path(directory) / "aerolib.csv"
            db_file.write_text("wTpfglkmv34 sceMsgDialogProgressBarSetValue\n", encoding="utf-8")
            out = io.StringIO()
            with patch.object(nid_names, "collect_real_names", return_value={"sceMsgDialogProgressBarSetValue"}), \
                 contextlib.redirect_stdout(out):
                code = nid_names.main(["--db", str(db_file), "--nid", "wTpfglkmv34"])
            self.assertEqual(code, 0)
            self.assertIn("already-implemented", out.getvalue())

    def test_main_reports_mismatch_and_exits_one(self):
        with tempfile.TemporaryDirectory() as directory:
            db_file = Path(directory) / "aerolib.csv"
            db_file.write_text("1jfXLRVzisc mismatch_name\n", encoding="utf-8")
            out = io.StringIO()
            with patch.object(nid_names, "collect_real_names", return_value=set()), \
                 contextlib.redirect_stdout(out):
                code = nid_names.main(["--db", str(db_file), "--nid", "1jfXLRVzisc"])
            self.assertEqual(code, 1)
            self.assertIn("MISMATCH", out.getvalue())

    def test_main_emits_json_format(self):
        with tempfile.TemporaryDirectory() as directory:
            db_file = Path(directory) / "aerolib.csv"
            db_file.write_text("wTpfglkmv34 sceMsgDialogProgressBarSetValue\n", encoding="utf-8")
            out = io.StringIO()
            with patch.object(nid_names, "collect_real_names", return_value=set()), \
                 contextlib.redirect_stdout(out):
                code = nid_names.main(["--db", str(db_file), "--nid", "wTpfglkmv34", "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["db_entries"], 1)
            self.assertEqual(payload["rows"][0]["status"], "rename-ready")


if __name__ == "__main__":
    unittest.main()
