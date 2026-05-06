import os
import json
import zipfile
import csv
import io
import logging
from typing import List, Optional
from pathlib import Path

from utils.helpers import parse_cookie_string

logger = logging.getLogger(__name__)


class FileParser:
    """
    Multi-format file parser for Roblox cookies.
    Supports: .txt, .zip, .json, .csv, .tsv, .log, .dat, .cfg, .ini, .xml, and more.
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
        # If no extension or unknown, try to parse anyway
        return True  # Be generous - try to parse any file

    @staticmethod
    def parse_file(filepath: str) -> List[str]:
        """
        Parse a file and extract all cookie values.
        Returns a list of raw .ROBLOSECURITY cookie strings.
        """
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return []

        ext = Path(filepath).suffix.lower()

        try:
            if ext == '.zip':
                return FileParser._parse_zip(filepath)
            elif ext == '.json':
                return FileParser._parse_json(filepath)
            elif ext == '.jsonl':
                return FileParser._parse_jsonl(filepath)
            elif ext == '.csv':
                return FileParser._parse_csv(filepath)
            elif ext == '.tsv':
                return FileParser._parse_tsv(filepath)
            elif ext == '.xml':
                return FileParser._parse_xml(filepath)
            elif ext in ('.yaml', '.yml'):
                return FileParser._parse_yaml(filepath)
            else:
                # Try generic text parsing for all other formats
                return FileParser._parse_text(filepath)
        except Exception as e:
            logger.warning(f"Failed to parse {filepath} as {ext}: {e}. Trying generic parser...")
            try:
                return FileParser._parse_text(filepath)
            except Exception as e2:
                logger.error(f"Generic parser also failed for {filepath}: {e2}")
                return []

    @staticmethod
    def _parse_text(filepath: str) -> List[str]:
        """Parse plain text files. Handles multiple formats per line."""
        cookies = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try latin-1 as fallback
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
    def _parse_zip(filepath: str) -> List[str]:
        """Parse ZIP files - extracts and parses all contained files."""
        cookies = []
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                for name in zf.namelist():
                    # Skip directories and hidden files
                    if name.endswith('/') or name.startswith('.'):
                        continue

                    try:
                        with zf.open(name) as inner_file:
                            content = inner_file.read().decode("utf-8", errors="ignore")
                            inner_cookies = FileParser._parse_content(content, name)
                            cookies.extend(inner_cookies)
                    except Exception as e:
                        logger.warning(f"Failed to parse {name} inside ZIP: {e}")
                        continue
        except zipfile.BadZipFile:
            logger.error(f"Bad ZIP file: {filepath}")
            # Try parsing as text instead
            return FileParser._parse_text(filepath)

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

        # Handle different JSON structures
        if isinstance(data, list):
            for item in data:
                cookie = FileParser._extract_cookie_from_json_obj(item)
                if cookie:
                    cookies.append(cookie)
        elif isinstance(data, dict):
            # Could be a single cookie object or have nested structures
            cookie = FileParser._extract_cookie_from_json_obj(data)
            if cookie:
                cookies.append(cookie)

            # Check for common nested structures
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
                # Check element text
                if elem.text and elem.text.strip():
                    cookie = parse_cookie_string(elem.text.strip())
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
                # Check attributes
                for attr_val in elem.attrib.values():
                    cookie = parse_cookie_string(attr_val)
                    if cookie and len(cookie) > 20:
                        cookies.append(cookie)
                # Recurse
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
        """
        Extract a cookie value from a JSON object by checking common key names.
        """
        if isinstance(obj, str):
            cookie = parse_cookie_string(obj)
            return cookie if cookie and len(cookie) > 20 else None

        if not isinstance(obj, dict):
            return None

        # Priority-ordered list of keys to check
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

        # If no known key found, check all string values
        for key, val in obj.items():
            if isinstance(val, str) and len(val) > 50:
                # Likely a cookie value
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
            if not line or line.startswith("#"):
                continue
            cookie = parse_cookie_string(line)
            if cookie and len(cookie) > 20:
                cookies.append(cookie)
        return cookies