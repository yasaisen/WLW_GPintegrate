from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.runtime import validate_artifact


ROOT = Path(__file__).resolve().parents[1]


class PipelineSmokeTest(unittest.TestCase):
    def test_end_to_end_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pipeline" / "run_pipeline.py"),
                    "--artifacts",
                    temp_dir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads((Path(temp_dir) / "I_selected_rois.json").read_text(encoding="utf-8"))
            validate_artifact(result, "I.CLEESelectedROIs")
            selected_rois = result["payload"]["selected_rois"]
            self.assertEqual(2, len(selected_rois))
            self.assertTrue(all(item["image_uri"] for item in selected_rois))
            self.assertTrue(all(item["coordinate"]["level"] == 0 for item in selected_rois))


if __name__ == "__main__":
    unittest.main()
