"""Hospital report-table adapters used internally by Report Decompose."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterable

from components.person_a.xlsx_reader import iter_xlsx_records


SUPPORTED_TABLE_TYPES = {"VGHTC2024", "CGMH2019"}
WSI_EXTENSIONS = (".ndpi", ".mrxs", ".svs", ".tif", ".tiff")


@dataclass(frozen=True)
class ParsedReportTables:
    cases: list[dict[str, Any]]
    skipped_cases: list[dict[str, str]]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(record: dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = _text(record.get(name))
        if value:
            return value
    return ""


def _normalize_stain(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())
    aliases = {
        "HE": "HE",
        "H01": "HE",
        "HER2": "HER2",
        "HER2NEU": "HER2",
        "ER": "ER",
        "PR": "PR",
        "KI67": "KI67",
        "NC": "NC",
    }
    return aliases.get(compact, value.strip().upper() or "UNKNOWN")


def _new_case(case_id: str, hospital: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "hospital": hospital,
        "reports": [],
        "wsis": [],
        "observations": [],
        "_report_keys": set(),
        "_wsi_paths": set(),
        "_wsi_ids": set(),
        "_observation_keys": set(),
    }


def _case(
    cases: dict[str, dict[str, Any]], case_id: str, hospital: str
) -> dict[str, Any]:
    case = cases.setdefault(case_id, _new_case(case_id, hospital))
    if case["hospital"] != hospital:
        raise ValueError(
            f"Case {case_id!r} occurs in multiple hospitals: "
            f"{case['hospital']!r} and {hospital!r}"
        )
    return case


def _add_report(
    case: dict[str, Any], report_id: str, raw_text: str, table_idx: int, source: str
) -> None:
    if not raw_text:
        return
    key = (report_id, raw_text)
    if key in case["_report_keys"]:
        return
    case["_report_keys"].add(key)
    case["reports"].append(
        {
            "report_id": report_id or f"{case['case_id']}-report-{len(case['reports']) + 1:03d}",
            "raw_text": raw_text,
            "table_idx": table_idx,
            "source": source,
        }
    )


def _unique_wsi_id(case: dict[str, Any], requested: str) -> str:
    base = requested or f"{case['case_id']}-wsi-{len(case['wsis']) + 1:03d}"
    candidate = base
    suffix = 2
    while candidate in case["_wsi_ids"]:
        candidate = f"{base}-{suffix}"
        suffix += 1
    case["_wsi_ids"].add(candidate)
    return candidate


def _add_wsi(
    case: dict[str, Any], wsi_id: str, stain_type: str, wsi_path: str, block_id: str = ""
) -> None:
    if not wsi_path or wsi_path in case["_wsi_paths"]:
        return
    case["_wsi_paths"].add(wsi_path)
    case["wsis"].append(
        {
            "wsi_id": _unique_wsi_id(case, wsi_id),
            "stain_type": _normalize_stain(stain_type),
            "wsi_path": wsi_path,
            "block_id": block_id,
        }
    )


def _parse_reference_ids(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;|]", raw) if item.strip()]


def _add_observation(
    case: dict[str, Any], report_id: str, dx_item: str, dx_result: str, references: list[str]
) -> None:
    if not dx_item or not dx_result:
        return
    key = (report_id, dx_item, dx_result, tuple(references))
    if key in case["_observation_keys"]:
        return
    case["_observation_keys"].add(key)
    case["observations"].append(
        {
            "report_id": report_id,
            "dx_item": dx_item,
            "dx_result": dx_result,
            "reference_wsi_ids": references,
        }
    )


def _iter_combined_records(path: Path) -> Iterable[tuple[str, int, dict[str, str]]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row_number, record in enumerate(csv.DictReader(stream), start=2):
                yield path.name, row_number, dict(record)
        return
    if path.suffix.lower() == ".xlsx":
        yield from iter_xlsx_records(path)
        return
    raise ValueError(f"Unsupported report table file: {path}; expected .csv or .xlsx")


def _parse_combined_table(
    path: Path, table_idx: int, hospital: str, cases: dict[str, dict[str, Any]]
) -> None:
    for sheet_name, row_number, record in _iter_combined_records(path):
        case_id = _first(record, ["case_id", "Path_ID", "病理序號"])
        if not case_id:
            continue
        case = _case(cases, case_id, hospital)
        report_id = _first(record, ["report_id", "Path_ID", "病理序號"]) or case_id
        report_text = _first(record, ["report_text", "pathology_report", "病理報告"])
        source = f"{path.name}:{sheet_name}:{row_number}"
        _add_report(case, report_id, report_text, table_idx, source)

        wsi_path = _first(record, ["wsi_path", "image_path", "filepath"])
        wsi_id = _first(record, ["wsi_id", "WSI_name", "file_name"])
        _add_wsi(
            case,
            wsi_id or Path(wsi_path).stem,
            _first(record, ["stain_type", "stain"]),
            wsi_path,
            _first(record, ["block_id"]),
        )

        _add_observation(
            case,
            report_id,
            _first(record, ["dx_item"]),
            _first(record, ["dx_result"]),
            _parse_reference_ids(_first(record, ["reference_wsi_ids"])),
        )


def _read_data_paths(source_dir: Path) -> list[str]:
    path = source_dir / "data_path"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _filename_with_extension(filename: str, extension: str) -> str:
    if filename.lower().endswith(WSI_EXTENSIONS):
        return filename
    return f"{filename}{extension}"


def _without_wsi_extension(filename: str) -> str:
    """Remove a real slide-image extension without mistaking scan timestamps for one."""

    lowered = filename.lower()
    for extension in WSI_EXTENSIONS:
        if lowered.endswith(extension):
            return filename[: -len(extension)]
    return filename


def _portable_path(value: str) -> Path:
    """Interpret source-table path separators consistently on Linux containers."""

    return Path(value.replace("\\", "/"))


def _match_case_id(filename: str, case_ids: list[str]) -> tuple[str, str] | None:
    prefix = filename.split(",", 1)[0].strip()
    for case_id in case_ids:
        if prefix.startswith(case_id):
            block_id = prefix[len(case_id) :].strip().split("-", 1)[0]
            return case_id, block_id
    return None


def _parse_vghtc_directory(
    source_dir: Path,
    table_idx: int,
    cases: dict[str, dict[str, Any]],
    *,
    include_legacy_wsi: bool = True,
) -> None:
    source_case_ids: set[str] = set()
    report_paths = sorted(source_dir.glob("乳癌病理報告_*.xlsx"))
    for report_path in report_paths:
        for sheet_name, row_number, record in iter_xlsx_records(
            report_path, lambda name: "M85003" in name
        ):
            case_id = _first(record, ["病理序號"])
            report_text = _first(record, ["病理報告"])
            if case_id and report_text:
                source_case_ids.add(case_id)
                case = _case(cases, case_id, "VGHTC")
                _add_report(
                    case,
                    case_id,
                    report_text,
                    table_idx,
                    f"{report_path.name}:{sheet_name}:{row_number}",
                )

    if not include_legacy_wsi:
        return

    case_ids = sorted(source_case_ids, key=len, reverse=True)
    data_paths = _read_data_paths(source_dir)
    base_root = Path(os.path.commonpath(data_paths)) if data_paths else source_dir
    wsi_table = source_dir / "VGHTC_list_total_2.xlsx"
    for _, _, record in iter_xlsx_records(wsi_table):
        filename = _first(record, ["file_name"])
        match = _match_case_id(filename, case_ids)
        if not filename or match is None:
            continue
        case_id, block_id = match
        relative_dir = _first(record, ["file_path"])
        full_name = _filename_with_extension(filename, ".mrxs")
        directory = _portable_path(relative_dir)
        if not directory.is_absolute():
            directory = base_root / directory
        _add_wsi(
            cases[case_id],
            filename,
            _first(record, ["stain"]),
            str(directory / full_name),
            block_id,
        )


def _parse_cgmh_directory(
    source_dir: Path,
    table_idx: int,
    cases: dict[str, dict[str, Any]],
    *,
    include_legacy_wsi: bool = True,
) -> None:
    source_case_ids: set[str] = set()
    report_path = source_dir / "Pathology_Report_v1.xlsx"
    for sheet_name, row_number, record in iter_xlsx_records(report_path):
        case_id = _first(record, ["Path_ID"])
        report_text = _first(record, ["pathology_report", "病理報告"])
        if case_id and report_text:
            source_case_ids.add(case_id)
            case = _case(cases, case_id, "CGMH")
            _add_report(
                case,
                case_id,
                report_text,
                table_idx,
                f"{report_path.name}:{sheet_name}:{row_number}",
            )

    if not include_legacy_wsi:
        return

    data_paths = _read_data_paths(source_dir)
    base_root = Path(data_paths[0]) if data_paths else source_dir

    stains_by_filename: dict[str, str] = {}
    wsi_table = source_dir / "CGMH_list_total.xlsx"
    for _, _, record in iter_xlsx_records(wsi_table):
        filename = _without_wsi_extension(_first(record, ["file_name"])).strip()
        if filename:
            stains_by_filename[filename] = _first(record, ["stain"])

    image_table = source_dir / "Pathology_image_path_v1.csv"
    with image_table.open("r", encoding="utf-8-sig", newline="") as stream:
        records = csv.DictReader(stream)
        for record in records:
            case_id = _first(record, ["Path_ID"])
            if case_id not in source_case_ids:
                continue
            filename = _first(record, ["WSI_name"])
            if not filename:
                continue
            # The CGMH codebook defines the on-disk layout as
            # <data_path>/<anony_ID>/<WSI_name>.  ``image_path`` is a Windows-style
            # legacy location and must not be appended to the Linux mount path.
            relative_dir = _first(record, ["anony_ID"])
            if not relative_dir:
                relative_dir = _portable_path(_first(record, ["image_path"])).name
            directory = _portable_path(relative_dir)
            if not directory.is_absolute():
                directory = base_root / directory
            filename_key = _without_wsi_extension(filename).strip()
            block_id = filename_key[len(case_id) :].strip().split("-", 1)[0]
            _add_wsi(
                cases[case_id],
                filename_key,
                stains_by_filename.get(filename_key, "UNKNOWN"),
                str(directory / filename),
                block_id,
            )


def _normalized_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _path_tokens(path: Path) -> list[str]:
    tokens: list[str] = []
    for part in path.parts:
        stem = Path(part).stem
        tokens.extend(token for token in re.split(r"[^A-Za-z0-9]+", stem) if token)
    return tokens


def _is_he_path(path: Path, case_directory: Path, he_tokens: set[str]) -> bool:
    relative = path.relative_to(case_directory)
    return any(_normalized_token(token) in he_tokens for token in _path_tokens(relative))


def _block_id_from_he_path(
    path: Path,
    case_directory: Path,
    case_id: str,
    he_tokens: set[str],
    block_pattern: re.Pattern[str] | None,
    default_block_id: str,
) -> str:
    relative = path.relative_to(case_directory)
    if block_pattern is not None:
        match = block_pattern.search(relative.as_posix())
        if match:
            if "block" in match.groupdict():
                return match.group("block")
            if match.groups():
                return match.group(1)
            raise ValueError("wsi_discovery.block_pattern must capture a block value")

    # Prefer a meaningful directory between <case_id>/ and the file.  This
    # supports both <case>/A/HE/file and <case>/HE/A/file layouts.
    for part in relative.parent.parts:
        compact = _normalized_token(part)
        if compact and compact not in he_tokens and compact != _normalized_token(case_id):
            return part

    # Hospital exports commonly use names such as
    # CASE001A,H01,130103.mrxs or CASE001_A_HE.mrxs.  In both forms the first
    # suffix token after the case id is the block id.
    stem = path.stem
    if stem.casefold().startswith(case_id.casefold()):
        tail = stem[len(case_id) :].strip(" _,-")
        for token in re.split(r"[^A-Za-z0-9]+", tail):
            if not token:
                continue
            if _normalized_token(token) in he_tokens:
                break
            return token

    return default_block_id


def _case_directory(case_id: str, root: Path, hospital_subdirectory: str) -> Path:
    if Path(case_id).name != case_id or any(separator in case_id for separator in ("/", "\\")):
        raise ValueError(f"case_id cannot be used as a WSI directory name: {case_id!r}")
    return root / _portable_path(hospital_subdirectory) / case_id


def _attach_case_directory_he_wsis(
    cases: dict[str, dict[str, Any]],
    config: dict[str, Any],
    manifest_directory: Path,
) -> None:
    pending = [case for case in cases.values() if case["reports"] and not case["wsis"]]
    if not pending:
        return

    root_value = _text(config.get("root"))
    if not root_value:
        raise ValueError("wsi_discovery.root is required for case_directory_he mode")
    root = _portable_path(os.path.expandvars(root_value))
    if not root.is_absolute():
        root = (manifest_directory / root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Mounted WSI root does not exist: {root}")

    extensions = {
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in config.get("extensions", WSI_EXTENSIONS)
    }
    he_tokens = {
        _normalized_token(_text(token)) for token in config.get("he_tokens", ["HE", "H01"])
    }
    if not he_tokens:
        raise ValueError("wsi_discovery.he_tokens must contain at least one token")

    hospital_subdirectories = config.get("hospital_subdirectories", {})
    if not isinstance(hospital_subdirectories, dict):
        raise ValueError("wsi_discovery.hospital_subdirectories must be an object")
    recursive = bool(config.get("recursive", True))
    default_block_id = _text(config.get("default_block_id")) or "UNSPECIFIED"
    pattern_value = _text(config.get("block_pattern"))
    block_pattern = re.compile(pattern_value) if pattern_value else None

    for case in pending:
        hospital_subdirectory = _text(hospital_subdirectories.get(case["hospital"]))
        case_directory = _case_directory(case["case_id"], root, hospital_subdirectory)
        if not case_directory.is_dir():
            continue

        paths = case_directory.rglob("*") if recursive else case_directory.glob("*")
        for path in sorted(paths):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            if not _is_he_path(path, case_directory, he_tokens):
                continue
            _add_wsi(
                case,
                path.stem,
                "HE",
                path.as_posix(),
                _block_id_from_he_path(
                    path,
                    case_directory,
                    case["case_id"],
                    he_tokens,
                    block_pattern,
                    default_block_id,
                ),
            )


def _finalize_cases(cases: dict[str, dict[str, Any]]) -> ParsedReportTables:
    finalized: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for case_id in sorted(cases):
        case = cases[case_id]
        if not case["reports"]:
            skipped.append({"case_id": case_id, "reason": "missing report"})
            continue
        if not case["wsis"]:
            skipped.append({"case_id": case_id, "reason": "missing WSI"})
            continue

        wsi_ids = [wsi["wsi_id"] for wsi in case["wsis"]]
        dx_pairs = []
        for index, observation in enumerate(case["observations"], start=1):
            references = observation["reference_wsi_ids"]
            unknown = sorted(set(references) - set(wsi_ids))
            if unknown:
                raise ValueError(
                    f"Case {case_id!r} DxPair references unknown WSI IDs: {unknown!r}"
                )
            dx_pairs.append(
                {
                    "dx_pair_id": f"{case_id}-dx-{index:03d}",
                    "case_id": case_id,
                    "source_report_id": observation["report_id"],
                    "dx_item": observation["dx_item"],
                    "dx_result": observation["dx_result"],
                    "reference_wsi_ids": references,
                }
            )

        finalized.append(
            {
                "case_id": case_id,
                "hospital": case["hospital"],
                "reports": case["reports"],
                "wsis": sorted(case["wsis"], key=lambda item: item["wsi_id"]),
                "dx_pairs": dx_pairs,
            }
        )
    return ParsedReportTables(cases=finalized, skipped_cases=skipped)


def parse_report_tables(
    tables: list[dict[str, Any]],
    manifest_directory: str | Path,
    wsi_discovery: dict[str, Any] | None = None,
) -> ParsedReportTables:
    cases: dict[str, dict[str, Any]] = {}
    seen_indexes: set[int] = set()
    base = Path(manifest_directory)
    discovery = wsi_discovery or {}
    discovery_mode = _text(discovery.get("mode")) or "legacy_tables"
    if discovery_mode not in {"legacy_tables", "case_directory_he", "disabled"}:
        raise ValueError(f"Unsupported wsi_discovery.mode: {discovery_mode!r}")
    include_legacy_wsi = discovery_mode == "legacy_tables"

    for table in sorted(tables, key=lambda item: item["table_idx"]):
        table_idx = table["table_idx"]
        if table_idx in seen_indexes:
            raise ValueError(f"Duplicate table_idx: {table_idx}")
        seen_indexes.add(table_idx)

        table_type = table["table_type"]
        if table_type not in SUPPORTED_TABLE_TYPES:
            raise ValueError(f"Unsupported table_type: {table_type!r}")
        source = Path(table["table_path"])
        if not source.is_absolute():
            source = (base / source).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Report table source does not exist: {source}")

        if source.is_dir() and table_type == "VGHTC2024":
            _parse_vghtc_directory(
                source, table_idx, cases, include_legacy_wsi=include_legacy_wsi
            )
        elif source.is_dir() and table_type == "CGMH2019":
            _parse_cgmh_directory(
                source, table_idx, cases, include_legacy_wsi=include_legacy_wsi
            )
        else:
            hospital = "VGHTC" if table_type == "VGHTC2024" else "CGMH"
            _parse_combined_table(source, table_idx, hospital, cases)

    if discovery_mode == "case_directory_he":
        _attach_case_directory_he_wsis(cases, discovery, base)

    return _finalize_cases(cases)
