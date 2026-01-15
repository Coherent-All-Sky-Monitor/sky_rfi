"""Sphinx configuration for CASM RFI Sky Monitor."""

import os
import sys

# Add parent directory to path so Sphinx can import modules
sys.path.insert(0, os.path.abspath(".."))

# Project information
project = "CASM RFI Sky Monitor"
copyright = "2026, CASM"
author = "CASM"
version = "1.0"
release = "1.0.0"

# Sphinx extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
]

# Configure autodoc to include private members
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}

# Napoleon settings for Google-style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True

# HTML theme
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "logo_only": False,
    "prev_next_buttons_location": "bottom",
    "style_external_links": False,
    "vcs_pageview_mode": "",
    "style_nav_header_background": "#2980B9",
}

# HTML output
html_static_path = ["_static"]
html_css_files = ["custom.css"]

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# Source file extensions
source_suffix = ".rst"
master_doc = "index"

# Exclude patterns
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Pygments syntax highlighting
pygments_style = "sphinx"
