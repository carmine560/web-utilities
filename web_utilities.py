"""HTTP HEAD request utilities with error handling."""

import requests

from core_utilities.errors import ExternalServiceError


def make_head_request(url):
    """Perform HTTP HEAD request and handle errors."""
    try:
        head = requests.head(url, timeout=5)
        head.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise ExternalServiceError(
            f"HEAD request failed for {url}: {e}"
        ) from e
    return head
