Developer Notes
===============

Installation Options
--------------------

The package provides several optional dependency groups:

.. code-block:: bash

   pip install -e .            # Core only (requests + tqdm + tomlkit)
   pip install -e ".[test]"    # Testing (pytest + pytest-cov)
   pip install -e ".[lint]"    # Linting + type-checking (ruff, mypy)
   pip install -e ".[docs]"    # Documentation (Sphinx + extensions)
   pip install -e ".[dev]"     # All of the above + jupyter

.. list-table::
   :header-rows: 1
   :widths: 15 35 50

   * - Extra
     - Installs
     - Use case
   * - ``test``
     - ``pytest>=7.0``, ``pytest-cov>=4.0``
     - Running the test suite (with coverage).
   * - ``lint``
     - ``ruff>=0.6``, ``mypy>=1.10``, ``types-requests``
     - Linting, formatting, and type-checking.
   * - ``docs``
     - ``sphinx>=7.0``, ``pydata-sphinx-theme>=0.15``, ``sphinx-design``, ``sphinx-copybutton``, ``myst-parser``
     - Building the HTML documentation.
   * - ``dev``
     - All of the above + ``jupyter``
     - Full development environment including notebooks.


Building the Documentation
--------------------------

.. code-block:: bash

   sphinx-build -b html -w warnings_sphinx_build.txt docs docs/_build/html

The ``-w`` flag writes warnings to ``warnings_sphinx_build.txt``. The CI
build uses ``-W`` (warnings as errors) to enforce clean builds.

To preview locally:

.. code-block:: bash

   python3 -m http.server 8000 --directory docs/_build/html

Then open http://localhost:8000.


CI/CD
-----

Four GitHub Actions workflows run the project:

**Tests** (``.github/workflows/tests.yml``):

- Push / pull request to ``main``.
- Runs ``pytest --cov`` across Python 3.10, 3.11, 3.12, and 3.13.

**Quality** (``.github/workflows/quality.yml``):

- Push / pull request to ``main``.
- Runs ``ruff check``, ``ruff format --check``, and ``mypy``.

**Documentation** (``.github/workflows/docs.yml``):

- Push to ``main``.
- Builds the docs with warnings as errors (``-W``) and deploys to GitHub Pages.

**Publish** (``.github/workflows/publish.yml``):

- Runs when a GitHub Release is *published*.
- Builds the sdist + wheel, runs ``twine check --strict``, and uploads to
  PyPI via OIDC Trusted Publishing (no API token is stored).

Optionally enable the local ``pre-commit`` hooks (ruff lint + format plus basic
hygiene) so commits are checked before they reach CI:

.. code-block:: bash

   pip install -e ".[lint]" pre-commit
   pre-commit install


One-time setup
--------------

These configure the automation and are done **once** per repository, not per
release:

- **GitHub Pages** — repository **Settings → Pages → Source: GitHub Actions**.
  The docs then publish on every push to ``main`` at
  https://fschwar4.github.io/saia_python/.
- **PyPI Trusted Publisher** — at https://pypi.org/manage/account/publishing/,
  add a publisher (a *pending publisher* before the project's first upload)
  with project ``saia-python``, owner ``fschwar4``, repository ``saia_python``,
  workflow ``publish.yml``, environment ``pypi``. This lets the Publish
  workflow upload without a stored token.
- **Zenodo archiving** — at https://zenodo.org/account/settings/github/, log in
  with GitHub and toggle the ``saia_python`` repository **on** *before* the
  next release, so each Release is archived and assigned a DOI.


Versioning
----------

The project follows `Semantic Versioning <https://semver.org/>`_
(``MAJOR.MINOR.PATCH``). The version lives in ``pyproject.toml`` under
``[project] version`` and is read at runtime via ``importlib.metadata`` as
``saia_python.__version__``.


Releasing
---------

The established release flow (assumes the one-time setup above is done).
Publishing to PyPI happens through the **Publish** workflow on a GitHub
Release — no manual upload to PyPI and no stored token.

1. **Bump the version** in ``pyproject.toml`` and update
   ``docs/CHANGELOG.md`` — promote the ``[Unreleased]`` entries into a dated
   ``[X.Y.Z]`` section and update the compare links at the bottom.

2. **Check locally** (CI enforces the same):

   .. code-block:: bash

      ruff check saia_python tests
      ruff format --check saia_python tests
      mypy
      pytest --cov=saia_python
      sphinx-build -b html -W docs docs/_build/html
      python -m build && twine check --strict dist/*

3. *(Optional)* **TestPyPI dry-run** — preview the upload and rendered
   metadata before the real release. TestPyPI versions are immutable, so use a
   throwaway suffix (e.g. ``X.Y.Z.dev1``) if you need to re-test:

   .. code-block:: bash

      python -m build
      twine upload --repository testpypi dist/*
      # verify in a clean venv (dependencies resolve from real PyPI):
      pip install --index-url https://test.pypi.org/simple/ \
          --extra-index-url https://pypi.org/simple/ saia-python

4. **Commit, tag, and push:**

   .. code-block:: bash

      git add -A
      git commit -m "Release X.Y.Z: <summary>"
      git push origin main
      git tag -a vX.Y.Z -m "saia-python X.Y.Z"
      git push origin vX.Y.Z

5. **Create the GitHub Release** for tag ``vX.Y.Z`` (for example
   ``gh release create vX.Y.Z --notes-file <changelog-section>``). Publishing
   the Release fires the **Publish** workflow, which uploads to PyPI via
   Trusted Publishing; Zenodo simultaneously archives the Release and mints a
   DOI.

6. **Wire the DOI** — add the Zenodo concept and version DOIs to
   ``CITATION.cff`` (``identifiers:``) and the DOI badge to ``README.md``,
   then commit.
