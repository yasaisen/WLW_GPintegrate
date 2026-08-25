from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from components.person_a.table_parsers import (
    _filename_with_extension,
    _portable_path,
    _without_wsi_extension,
    parse_report_tables,
)


class ReportTableParserTests(unittest.TestCase):
    def test_known_wsi_extension_does_not_consume_scan_timestamp(self) -> None:
        filename = "slide-name_15.33.07.ndpi"
        self.assertEqual("slide-name_15.33.07", _without_wsi_extension(filename))
        self.assertEqual("slide-name_15.33.07", _without_wsi_extension(filename[:-5]))
        self.assertEqual(
            "slide-name_15.33.07.mrxs",
            _filename_with_extension("slide-name_15.33.07", ".mrxs"),
        )

    def test_windows_source_directory_is_portable(self) -> None:
        self.assertEqual("batch/patient", _portable_path("batch\\patient").as_posix())

    def test_mounted_case_directory_discovers_only_he_and_groups_blocks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports.csv"
            reports.write_text(
                "case_id,report_id,report_text\n"
                "case-001,report-001,Invasive carcinoma.\n",
                encoding="utf-8",
            )
            case_directory = root / "wsi" / "case-001"
            (case_directory / "C" / "HE").mkdir(parents=True)
            for relative in (
                "case-001_A_HE.mrxs",
                "case-001B,H01,130103.ndpi",
                "case-001_A_ER.mrxs",
                "C/HE/level-1.svs",
            ):
                path = case_directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            parsed = parse_report_tables(
                [
                    {
                        "table_idx": 0,
                        "table_type": "VGHTC2024",
                        "table_path": str(reports),
                    }
                ],
                root,
                {
                    "mode": "case_directory_he",
                    "root": str(root / "wsi"),
                    "he_tokens": ["HE", "H01"],
                },
            )

            self.assertEqual(1, len(parsed.cases))
            wsis = parsed.cases[0]["wsis"]
            self.assertEqual(3, len(wsis))
            self.assertEqual({"A", "B", "C"}, {wsi["block_id"] for wsi in wsis})
            self.assertEqual({"HE"}, {wsi["stain_type"] for wsi in wsis})
            self.assertNotIn("case-001_A_ER", {wsi["wsi_id"] for wsi in wsis})

    def test_mounted_case_directory_uses_unspecified_when_block_is_unknown(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports.csv"
            reports.write_text(
                "case_id,report_text\ncase-001,Invasive carcinoma.\n",
                encoding="utf-8",
            )
            he = root / "wsi" / "case-001" / "HE" / "slide.svs"
            he.parent.mkdir(parents=True)
            he.touch()

            parsed = parse_report_tables(
                [
                    {
                        "table_idx": 0,
                        "table_type": "VGHTC2024",
                        "table_path": str(reports),
                    }
                ],
                root,
                {"mode": "case_directory_he", "root": str(root / "wsi")},
            )

            self.assertEqual("UNSPECIFIED", parsed.cases[0]["wsis"][0]["block_id"])

    def test_mounted_case_directory_supports_hospital_folder_and_block_pattern(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports.csv"
            reports.write_text(
                "case_id,report_text\ncase-001,Invasive carcinoma.\n",
                encoding="utf-8",
            )
            he = root / "wsi" / "VGHTC" / "case-001" / "scan-block-ZZ-HE.svs"
            he.parent.mkdir(parents=True)
            he.touch()

            parsed = parse_report_tables(
                [
                    {
                        "table_idx": 0,
                        "table_type": "VGHTC2024",
                        "table_path": str(reports),
                    }
                ],
                root,
                {
                    "mode": "case_directory_he",
                    "root": str(root / "wsi"),
                    "hospital_subdirectories": {"VGHTC": "VGHTC"},
                    "block_pattern": r"block-(?P<block>[A-Z]+)",
                },
            )

            self.assertEqual("ZZ", parsed.cases[0]["wsis"][0]["block_id"])

    def test_fixture_wsi_path_does_not_require_mounted_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports.csv"
            reports.write_text(
                "case_id,report_text,wsi_id,stain_type,wsi_path\n"
                "case-001,Invasive carcinoma.,case-001-he,HE,/fake/case-001-he.svs\n",
                encoding="utf-8",
            )

            parsed = parse_report_tables(
                [
                    {
                        "table_idx": 0,
                        "table_type": "VGHTC2024",
                        "table_path": str(reports),
                    }
                ],
                root,
                {"mode": "case_directory_he", "root": str(root / "not-mounted")},
            )

            self.assertEqual(1, len(parsed.cases))
            self.assertEqual("case-001-he", parsed.cases[0]["wsis"][0]["wsi_id"])


if __name__ == "__main__":
    unittest.main()
