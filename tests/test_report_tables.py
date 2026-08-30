from __future__ import annotations

import unittest

from components.person_a.table_parsers import (
    _filename_with_extension,
    _portable_path,
    _without_wsi_extension,
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


if __name__ == "__main__":
    unittest.main()
