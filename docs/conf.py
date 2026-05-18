"""Sphinx configuration for saia-python documentation."""

import importlib.metadata
import sys
from pathlib import Path

# -- Read project metadata from pyproject.toml --------------------------------

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

_pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
_pyproject = tomllib.loads(_pyproject_path.read_text(encoding="utf-8"))
_project_meta = _pyproject["project"]

# -- Project information -----------------------------------------------------

project = _project_meta["name"]
author = _project_meta["authors"][0]["name"]
release = _project_meta["version"]
version = ".".join(release.split(".")[:2])
_repo_url = _project_meta.get("urls", {}).get("Repository", "")

from datetime import date
copyright = f"{date.today().year}, {author}"

html_title = "SAIA Python"

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.linkcode",
    "sphinx_design",
    "sphinx_copybutton",
    "myst_parser",
]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Napoleon (Google-style docstrings) --------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_ivar = True
napoleon_use_param = True
napoleon_use_rtype = True

# -- Autodoc -----------------------------------------------------------------

autodoc_typehints = "signature"
autodoc_member_order = "bysource"

# -- MyST parser (Markdown support) ------------------------------------------

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

# -- Intersphinx -------------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
}

# -- HTML output -------------------------------------------------------------

html_theme = "pydata_sphinx_theme"

templates_path = ["_templates"]

html_theme_options = {
    "show_toc_level": 2,
    "navigation_with_keys": True,
    "footer_start": ["copyright"],
    "footer_center": ["sphinx-version"],
    "footer_end": ["package-version"],
}

if _repo_url:
    html_theme_options["github_url"] = _repo_url

html_static_path = ["_static"]

# -- Link to GitHub source (sphinx.ext.linkcode) ----------------------------

import inspect
import saia_python


def linkcode_resolve(domain, info):
    """Map autodoc entries to GitHub source URLs."""
    if domain != "py" or not info["module"]:
        return None

    mod_name = info["module"]
    obj_name = info["fullname"]

    try:
        mod = __import__(mod_name, fromlist=[obj_name.split(".")[0]])
        obj = mod
        for part in obj_name.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None

        sourcefile = inspect.getfile(obj)
    except (TypeError, ImportError, AttributeError):
        return None

    # Resolve to path relative to package root
    import os
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(saia_python.__file__)))
    try:
        rel_path = os.path.relpath(sourcefile, pkg_dir)
    except ValueError:
        return None

    # Get line numbers
    try:
        source, lineno = inspect.getsourcelines(obj)
        linespec = f"#L{lineno}-L{lineno + len(source) - 1}"
    except (TypeError, OSError):
        linespec = ""

    return f"{_repo_url}/blob/main/{rel_path}{linespec}"


# -- CHANGELOG integration ---------------------------------------------------
# docs/CHANGELOG.md is rendered directly via myst-parser and linked
# from the toctree in docs/index.rst.
