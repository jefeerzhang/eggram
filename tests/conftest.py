"""One synchronous Playwright context per session, shared by browser test modules."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import toolchain as tc  # noqa: E402


@pytest.fixture(scope="session")
def browser():
    path = tc.browser_path()
    if not path:
        pytest.skip("no Chrome/Edge available")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=path, headless=True)
        yield b
        b.close()
