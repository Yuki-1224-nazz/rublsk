import os
import json
import zipfile
import csv
import io
import logging
from typing import List, Optional, Tuple
from pathlib import Path

from utils.helpers import parse_cookie_string

logger = logging.getLogger(__name__)


class FileParser:
    """
    Multi-format file parser for Roblox cookies.
    Supports: .txt, .zip, .rar, .7z, .json, .csv, .tsv, .log, .dat, .cfg, .ini, .xml, and more.
    
    For archive files (.zip, .rar, .7z):
    - Extracts and parses EACH inner file individually
    - Supports nested archives (archives inside archives)
    - Reports per-file breakdown
    """

    SUPPORTED_EXTENSIONS = {
        '.txt', '.text',
        '.zip', '.rar', '.7z',
        '.json', '.jsonl',
        '.csv', '.tsv',
        '.log',
        '.dat', '.cfg', '.ini', '.conf',
        '.xml',
        '.html', '.htm',
        '.yaml', '.yml',
    }

    # Extensions that are archives
    ARCHIVE_EXTENSIONS = {'.zip', '.rar', '.7z'}

    # Extensions treated as text files inside archives
    TEXT_EXTENSIONS = {
        '.txt', '.text', '.log', '.dat', '.cfg', '.ini', '.conf',
        '.csv', '.tsv', '.json', '.jsonl', '.xml', '.yaml', '.yml',
        '.html', '.htm',
    }

    @staticmethod
    def get_supported_extensions_str() -> str:
        exts = sorted(FileParser.SUPPORTED_EXTENSIONS)
        return ", ".join(exts)

    @staticmethod
    def is_supported(filename: str) -> bool:
        """Check if the file extension is supported."""
        ext = Path(filename).suffix.lower()
        if ext in FileParser.SUPPORTED_EXTENSIONS:
            return True
        return True  # Be generous - try to parse any file

    @staticmethod
    def parse_file(filepath: str) -> Tuple[List[str], List[dict]]:
        """
        Parse a file and extract all cookie values.
        
        Returns:
            Tuple of (cookies_list, file_breakdown)
            - cookies_list: List of raw .ROBLOSECURITY cookie strings
            - file_breakdown: List of dicts with per-file info:
                [{"filename": "file1.txt", "cookies": 5}, {"filename": "file2.txt", "cookies": 3}, ...]
        """
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return [], []

        ext = Path(filepath).suffix.lower()
        breakdown = []

        try:
            if ext in FileParser.ARCHIVE_EXTENSIONS:
                cookies = FileParser._parse_archive(filepath, breakdown)
            elif ext == '.json':
                cookies = FileParser._parse_json(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            elif ext == '.jsonl':
                cookies = FileParser._parse_jsonl(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            elif ext == '.csv':
                cookies = FileParser._parse_csv(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            elif ext == '.tsv':
                cookies = FileParser._parse_tsv(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            elif ext == '.xml':
                cookies = FileParser._parse_xml(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            elif ext in ('.yaml', '.yml'):
                cookies = FileParser._parse_yaml(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            else:
                cookies = FileParser._parse_text(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
        except Exception as e:
            logger.warning(f"Failed to parse {filepath} as {ext}: {e}. Trying generic parser...")
            try:
                cookies = FileParser._parse_text(filepath)
                breakdown.append({"filename": Path(filepath).name, "cookies": len(cookies)})
            except Exception as e2:
                logger.error(f"Generic parser also failed for {filepath}: {e2}")
                return [], []

        return cookies, breakdown

    @staticmethod
    def _parse_archive(filepath: str, breakdown: List[dict]) -> List[str]:
        """
        Parse archive files (.zip, .rar, .7z).
        Extracts and processes EACH inner file individually.
        Supports nested archives (archives inside archives).
        """
        ext = Path(filepath).suffix.lower()
        cookies = []

        if ext == '.zip':
            cookies = FileParser._parse_zip(filepath, breakdown)
        elif ext in ('.rar', '.7z'):
            # Try using py7zr / rarfile, fallback to treating as zip
            cookies = FileParser._parse_archive_fallback(filepath, breakdown)

        return cookies

    @staticmethod
    def _parse_zip(filepath: str, breakdown: List[dict]) -> List[str]:
        """Parse ZIP files - extracts and parses each inner file individually."""
        cookies = []
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                for name in sorted(zf.namelist()):
                    # Skip directories, hidden files, and macOS metadata
                    if name.endswith('/') or name.startswith('.') or name.startswith('__MACOSX'):
                        continue

                    try:
                        with zf.open(name) as inner_file:
                            content = inner_file.read().decode("utf-8", errors="ignore")
                    except Exception as e:
                        logger.warning(f"Failed to read {name} inside ZIP: {e}")
                        continue

                    inner_ext = Path(name).suffix.lower()
                    inner_name = Path(name).name

                    # If it's a nested archive, recursively parse it
                    if inner_ext in FileParser.ARCHIVE_EXTENSIONS:
                        nested_cookies = FileParser._parse_nested_archive(content, inner_name, inner_ext, breakdown)
                        cookies.extend(nested_cookies)
                    else:
                        # Parse as text/JSON/CSV based on extension
                        inner_cookies = FileParser._parse_content(content, inner_name)
                        cookies.extend(inner_cookies)
                        breakdown.append({
                            "filename": inner_name,
                            "cookies": len(inner_cookies),
                        })

        except zipfile.BadZipFile:
            logger.error(f"Bad ZIP file: {filepath}")
            # Try parsing as text instead
            fallback_cookies = FileParser._parse_text(filepath)
            breakdown.append({"filename": Path(filepath).name, "cookies": len(fallback_cookies), "note": "fallback_text_parse"})
            return fallback_cookies

        return cookies

    @staticmethod
    def _parse_nested_archive(content: str, name: str, ext: str, breakdown: List[dict]) -> List[str]:
        """
        Parse a nested archive (archive inside another archive).
        Writes temporarily to disk and parses it.
        """
        import tempfile
        cookies = []

        try:
            # Write the nested archive to a temp file
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content.encode('utf-8', errors='ignore') if isinstance(content, str) else content)
                tmp_path = tmp.name

            # Parse the nested archive
            if ext == '.zip':
                cookies = FileParser._parse_zip(tmp_path, breakdown)
            else:
                cookies = FileParser._parse_archive_fallback(tmp_path, breakdown)

            # Clean up
            os.unlink(tmp_path)

        except Exception as e:
            logger.warning(f"Failed to parse nested archive {name}: {e}")
            # Try parsing the content as plain text
            cookies = FileParser._parse_content(content, name)
            breakdown.append({"filename": name, "cookies": len(cookies), "note": "nested_fallback"})

        return cookies

    @staticmethod
    def _parse_archive_fallback(filepath: str, breakdown: List[dict]) -> List[str]:
        """
        Parse .rar and .7z files.
        Tries py7zr/rarfile libraries first, falls back to treating as zip or text.
        """
        ext = Path(filepath).suffix.lower()
        cookies = []

        # Try .7z with py7zr
        if ext == '.7z':
            try:
                import py7zr
                with py7zr.SevenZipFile(filepath, mode='r') as archive:
                    for name, bio in archive.readall().items():
                        if name.endswith('/') or name.startswith('.'):
                            continue
                        try:
                            content = bio.read().decode("utf-8", errors="ignore")
                            inner_cookies = FileParser._parse_content(content, name)
                            cookies.extend(inner_cookies)
                            breakdown.append({"filename": Path(name).name, "cookies": len(inner_cookies)})
                        except Exception as e:
                            logger.warning(f"Failed to parse {name} inside 7z: {e}")
                return cookies
            except ImportError:
                logger.warning("py7zr not installed. Trying fallback for .7z file.")
            except Exception as e:
                logger.warning(f"7z parsing failed: {e}")

        # Try .rar with rarfile
        if ext == '.rar':
            try:
                import rarfile
                with rarfile.RarFile(filepath, 'r') as rf:
                    for name in sorted(rf.namelist()):
                        if name.endswith('/') or name.startswith('.'):
                            continue
                        try:
                            with rf.open(name) as inner_file:
                                content = inner_file.read().decode("utf-8", errors="ignore")
                                inner_cookies = FileParser._parse_content(content, name)
                                cookies.extend(inner_cookies)
                                breakdown.append({"filename": Path(name).name, "cookies": len(inner_cookies)})
                        except Exception as e:
                            logger.warning(f"Failed to parse {name} inside RAR: {e}")
                return cookies
            except ImportError:
                logger.warning("rarfile not installed. Trying fallback for .rar file.")
            except Exception as e:
                logger.warning(f"RAR parsing failed: {e}")

        # Fallback: try as ZIP (some files are mislabeled)
        try:
            cookies = FileParser._parse_zip(filepath, breakdown)
            if cookies:
                return cookies
        except Exception:
            pass

        # Final fallback: parse as text
        fallback_cookies = FileParser._parse_text(filepath)
        breakdown.append({"filename": Path(filepath).name, "cookies": len(fallback_cookies), "note": "text_fallback"})
        return fallback_cookies

    @staticmethod
    def _parse_text(filepath: str) -> List[str]:
        """Parse plain text files. Handles multiple formats per line."""
        cookies = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1", errors="ignore") as f:
                content = f.read()

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            cookie = parse_cookie_string(line)
            if cookie and len(cookie) > 20:
                cookies.append(cookie)

        return cookies

    @staticmethod
    def _parse_json(filepath: str) -> List[str]:
        """Parse JSON files with various structures."""
        cookies = []
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return FileParser._parse_text(filepath)

        if isinstance(data, list):
            for item in data:
                cookie = FileParser._extract_cookie_from_json_obj(item)
                if cookie:
                    cookies.append(cookie)
        elif isinstance(data, dict):
            cookie = FileParser._extract_cookie_from_json_obj(data)
            if cookie:
                cookies.append(cookie)
            for key in ["cookies", "accounts", "data", "items", "results", "entries"]:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        cookie = FileParser._extract_cookie_from_json_obj(item)
                        if cookie:
                            cookies.append(cookie)

        return cookies

    @staticmethod
    def _parse_jsonl(filepath: str) -> List[str]:
        """Parse JSON Lines files (one JSON object per line)."""
        cookies = []
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    cookie = FileParser._extract_cookie_from_json_obj(obj)
                    if cookie:
                        cookies.append(cookie)
                except json.JSONDecodeError:
                    cookie = parse_cookie_string(line)
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
        return cookies

    @staticmethod
    def _parse_csv(filepath: str) -> List[str]:
        """Parse CSV files."""
        cookies = []
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                for cell in row:
                    cell = cell.strip()
                    if not cell:
                        continue
                    cookie = parse_cookie_string(cell)
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
        return cookies

    @staticmethod
    def _parse_tsv(filepath: str) -> List[str]:
        """Parse TSV (tab-separated) files."""
        cookies = []
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                cells = line.split("\t")
                for cell in cells:
                    cell = cell.strip()
                    if not cell:
                        continue
                    cookie = parse_cookie_string(cell)
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
        return cookies

    @staticmethod
    def _parse_xml(filepath: str) -> List[str]:
        """Parse XML files - extract cookie values from attributes or text."""
        cookies = []
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(filepath)
            root = tree.getroot()

            def extract_from_element(elem):
                if elem.text and elem.text.strip():
                    cookie = parse_cookie_string(elem.text.strip())
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
                for attr_val in elem.attrib.values():
                    cookie = parse_cookie_string(attr_val)
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
                for child in elem:
                    extract_from_element(child)

            extract_from_element(root)
        except Exception as e:
            logger.warning(f"XML parsing failed: {e}. Falling back to text parser.")
            return FileParser._parse_text(filepath)
        return cookies

    @staticmethod
    def _parse_yaml(filepath: str) -> List[str]:
        """Parse YAML files."""
        cookies = []
        try:
            import yaml
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                data = yaml.safe_load(f)

            def extract_from_yaml(obj):
                if isinstance(obj, str):
                    cookie = parse_cookie_string(obj)
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
                elif isinstance(obj, dict):
                    for v in obj.values():
                        extract_from_yaml(v)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_from_yaml(item)

            extract_from_yaml(data)
        except ImportError:
            logger.warning("PyYAML not installed. Falling back to text parser.")
            return FileParser._parse_text(filepath)
        except Exception as e:
            logger.warning(f"YAML parsing failed: {e}. Falling back to text parser.")
            return FileParser._parse_text(filepath)
        return cookies

    @staticmethod
    def _extract_cookie_from_json_obj(obj) -> Optional[str]:
        """Extract a cookie value from a JSON object by checking common key names."""
        if isinstance(obj, str):
            cookie = parse_cookie_string(obj)
            return cookie if cookie and len(cookie) > 20 else None

        if not isinstance(obj, dict):
            return None

        cookie_keys = [
            ".ROBLOSECURITY", "roblosecurity", "cookie", "token",
            "auth_token", "auth_cookie", "security_token",
            "value", "cookie_value", "session", "session_token",
            "access_token", "secret",
        ]

        for key in cookie_keys:
            if key in obj:
                val = obj[key]
                if isinstance(val, str) and len(val) > 20:
                    return val.strip()

        for key, val in obj.items():
            if isinstance(val, str) and len(val) > 50:
                cookie = parse_cookie_string(val)
                if cookie and len(cookie) > 20:
                    return cookie

        return None

    @staticmethod
    def _parse_content(content: str, filename: str = "") -> List[str]:
        """Parse content string based on filename extension or heuristics."""
        fname_lower = filename.lower()

        if fname_lower.endswith('.json'):
            try:
                data = json.loads(content)
                cookies = []
                if isinstance(data, list):
                    for item in data:
                        cookie = FileParser._extract_cookie_from_json_obj(item)
                        if cookie:
                            cookies.append(cookie)
                elif isinstance(data, dict):
                    cookie = FileParser._extract_cookie_from_json_obj(data)
                    if cookie:
                        cookies.append(cookie)
                return cookies
            except json.JSONDecodeError:
                pass

        if fname_lower.endswith('.csv'):
            cookies = []
            reader = csv.reader(io.StringIO(content))
            for row in reader:
                for cell in row:
                    cookie = parse_cookie_string(cell.strip())
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
            return cookies

        # Default: parse as text
        cookies = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            cookie = parse_cookie_string(line)
            if cookie and len(cookie) > 20:
                cookies.append(cookie)
        return cookies