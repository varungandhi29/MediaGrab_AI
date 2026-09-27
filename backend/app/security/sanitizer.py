import re
import html
import uuid
from pathlib import Path

# Regex for control characters and newlines (prevent CRLF log injection)
CONTROL_CHARS_PATTERN = re.compile(r'[\r\n\x00-\x1f\x7f-\x9f\x1b]')
# Regex for safe filename characters
SAFE_FILENAME_CHARS = re.compile(r'[^a-zA-Z0-9_\-\. ]')
# Dangerous file extensions to reject/override
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".sh", ".bash", ".ps1", ".vbs",
    ".js", ".jar", ".msi", ".dll", ".so", ".dylib", ".scr", ".pif"
}


def sanitize_for_logging(text: str, max_len: int = 256) -> str:
    """
    Sanitize untrusted text for logging to prevent CRLF injection,
    terminal ANSI escape sequences, or memory exhaustion.
    """
    if not text:
        return ""
    # Strip control chars and escape sequences
    cleaned = CONTROL_CHARS_PATTERN.sub(" ", str(text))
    # Normalize multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "...[truncated]"
    return cleaned


def sanitize_html_text(text: str) -> str:
    """
    Escape text for safe HTML presentation.
    """
    if not text:
        return ""
    return html.escape(str(text))


def generate_storage_key(extension: str = "mp4") -> str:
    """
    Generate an unguessable random storage filename (UUIDv4) to guarantee
    zero path traversal risk in server filesystem.
    """
    ext = extension.lstrip(".").lower()
    if not ext or f".{ext}" in DANGEROUS_EXTENSIONS:
        ext = "bin"
    return f"{uuid.uuid4().hex}.{ext}"


def sanitize_download_filename(title: str, extension: str = "mp4") -> str:
    """
    Produces a safe, clean filename for the Content-Disposition header.
    Removes path traversal patterns and replaces illegal characters.
    """
    title_clean = (title or "media").strip()
    # Strip path separators
    title_clean = title_clean.replace("/", "_").replace("\\", "_")
    # Replace unsafe characters
    title_clean = SAFE_FILENAME_CHARS.sub("_", title_clean)
    # Collapse consecutive underscores/spaces
    title_clean = re.sub(r'[_ ]+', '_', title_clean).strip("._ ")

    if not title_clean:
        title_clean = "download"

    # Truncate to reasonable length
    title_clean = title_clean[:100]

    ext_clean = extension.lstrip(".").lower()
    if not ext_clean or f".{ext_clean}" in DANGEROUS_EXTENSIONS:
        ext_clean = "mp4"

    return f"{title_clean}.{ext_clean}"


def sanitize_error_message(error: Exception | str) -> str:
    """
    Sanitizes system/library errors to ensure internal directory paths,
    passwords, or server environment details are not leaked to the user.
    """
    msg = str(error)
    # Remove local drive letters and absolute paths (e.g. C:\Users\... or /home/...)
    msg = re.sub(r'[A-Za-z]:\\[^ \t\n\r"\'<>]+', '[redacted-path]', msg)
    msg = re.sub(r'/[a-zA-Z0-9_\-\.\/]+', '[redacted-path]', msg)
    # Strip control chars
    msg = sanitize_for_logging(msg, max_len=300)
    return msg
