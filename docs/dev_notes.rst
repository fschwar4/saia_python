Developer Notes
===============

Installation Options
--------------------

The package provides three optional dependency groups:

.. code-block:: bash

   pip install -e .            # Core only (requests + tqdm)
   pip install -e ".[test]"    # Testing (pytest)
   pip install -e ".[docs]"    # Documentation (Sphinx + extensions)
   pip install -e ".[dev]"     # All of the above + jupyter

.. list-table::
   :header-rows: 1
   :widths: 15 35 50

   * - Extra
     - Installs
     - Use case
   * - ``test``
     - ``pytest>=7.0``
     - Running the test suite.
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

Two GitHub Actions workflows automate testing and documentation deployment:

**Tests** (``.github/workflows/tests.yml``):

- Triggered on push and pull request to ``main``.
- Runs ``pytest`` across Python 3.10, 3.11, 3.12, and 3.13.

**Documentation** (``.github/workflows/docs.yml``):

- Triggered on push to ``main``.
- Builds Sphinx documentation with warnings as errors (``-W``).
- Deploys to GitHub Pages automatically.

To enable GitHub Pages deployment:

1. Go to the repository **Settings > Pages**.
2. Under **Source**, select **GitHub Actions**.

Once configured, the documentation is published on every push to ``main``
and available at https://fschwar4.github.io/saia_python/.


Versioning
----------

The project follows `Semantic Versioning <https://semver.org/>`_
(``MAJOR.MINOR.PATCH``). The version is defined in ``pyproject.toml``
under ``[project] version`` and read at runtime via ``importlib.metadata``,
exposed as ``saia_python.__version__``.

Release procedure:

1. Update the version in ``pyproject.toml``.

2. Commit:

   .. code-block:: bash

      git add pyproject.toml
      git commit -m "Bump version to X.Y.Z"

3. Create an annotated tag:

   .. code-block:: bash

      git tag -a vX.Y.Z -m "Release vX.Y.Z"

4. Push:

   .. code-block:: bash

      git push origin main --tags


Publishing to PyPI
------------------

1. Install build tools:

   .. code-block:: bash

      pip install build twine

2. Build source distribution and wheel:

   .. code-block:: bash

      python -m build

3. Validate the package:

   .. code-block:: bash

      twine check dist/*

4. Upload to `TestPyPI <https://test.pypi.org/>`_ (recommended first):

   .. code-block:: bash

      twine upload --repository testpypi dist/*

5. Upload to PyPI:

   .. code-block:: bash

      twine upload dist/*
