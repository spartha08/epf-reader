# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Sudarshan Parthasarathy
"""Console entry point that starts the Streamlit page.

``streamlit run`` needs a file path, and an installed package's path is awkward
to type, so this resolves it and hands it over. Extra arguments are passed
through to Streamlit.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        from streamlit.web import cli as stcli
    except ImportError:
        print('Streamlit is not installed. Install it with:')
        print('    pip install "epf-reader[ui]"')
        return 1

    page = Path(__file__).resolve().parent / "streamlit_page.py"
    sys.argv = ["streamlit", "run", str(page), *sys.argv[1:]]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
