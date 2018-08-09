pytest-html
===========

pytest-html is a plugin for `pytest <http://pytest.org>`_ that generates a
HTML report for the test results.

.. image:: https://img.shields.io/badge/license-MPL%202.0-blue.svg
   :target: https://github.com/pytest-dev/pytest-html/blob/master/LICENSE
   :alt: License
.. image:: https://img.shields.io/pypi/v/pytest-html.svg
   :target: https://pypi.python.org/pypi/pytest-html/
   :alt: PyPI
.. image:: https://img.shields.io/conda/vn/conda-forge/pytest-html.svg
   :target: https://anaconda.org/conda-forge/pytest-html
   :alt: Conda Forge
.. image:: https://img.shields.io/travis/pytest-dev/pytest-html.svg
   :target: https://travis-ci.org/pytest-dev/pytest-html/
   :alt: Travis
.. image:: https://img.shields.io/github/issues-raw/pytest-dev/pytest-html.svg
   :target: https://github.com/pytest-dev/pytest-html/issues
   :alt: Issues
.. image:: https://img.shields.io/requires/github/pytest-dev/pytest-html.svg
   :target: https://requires.io/github/pytest-dev/pytest-html/requirements/?branch=master
   :alt: Requirements

Requirements
------------

You will need the following prerequisites in order to use pytest-html:

- Python 2.7, 3.6, PyPy, or PyPy3

Installation
------------

To install pytest-html:

.. code-block:: bash

  $ pip install pytest-html

Then run your tests with:

.. code-block:: bash

  $ pytest --html=report.html

ANSI codes
----------

Note that ANSI code support depends on the
`ansi2html <https://pypi.python.org/pypi/ansi2html/>`_ package. Due to the use
of a less permissive license, this package is not included as a dependency. If
you have this package installed, then ANSI codes will be converted to HTML in
your report.

Creating a self-contained report
--------------------------------

In order to respect the `Content Security Policy (CSP)
<https://developer.mozilla.org/docs/Web/Security/CSP>`_,
several assets such as CSS and images are stored separately by default.
You can alternatively create a self-contained report, which can be more
convenient when sharing your results. This can be done in the following way:

.. code-block:: bash

   $ pytest --html=report.html --self-contained-html

Images added as files or links are going to be linked as external resources,
meaning that the standalone report HTML-file may not display these images
as expected.

The plugin will issue a warning when adding files or links to the standalone report.

Test result output
~~~~~~~~~~~~~~~~~~

The output of the tests is grouped based on the effective branching logic of the
tests and their fixtures, which is determined by the file structure of your
project and how parameterized fixtures are defined/used. If using the
`pytest-xdist` plugin to run tests in parallel, the workers are, by default,
factored into this grouping logic, as this can have meaningful impact on how the
tests operate. This can be turned off by using the :code:`--no-group-on-worker`
option.

When using parameterized fixtures with `autouse`, the plugin will determine what
level is effectively being branched off for each permutation, based on the scope
the fixture was defined in, and the scope is was meant to apply for. The level
it's branching on will show as multiple copies of the same group, but each with
a description of their respective instance of the parameterized fixture.

By default, everything is collapsed. As groups are expanded, their contents are
generated at that moment. When they are collapsed, their contents are removed
from the DOM.

Enhancing reports
-----------------

Appearance
~~~~~~~~~~

Custom CSS (Cascasding Style Sheets) can be passed on the command line using
the :code:`--css` option. These will be applied in the order specified, and can
be used to change the appearance of the report.

.. code-block:: bash

  $ pytest --html=report.html --css=highcontrast.css --css=accessible.css

Structure & Functionality
~~~~~~~~~~~~~~~~~~~~~~~~~

Custom JavaScript additions can be passed on the command line using the
:code:`--js` option. These will be applied in the order specified, and can
be used to change the scripts of the report that are used to generate the
structure of the test output, and define the behavior of interactive elements.

.. code-block:: bash

  $ pytest --html=report.html --js=slideshow.js --css=structure.js

Environment
~~~~~~~~~~~

The *Environment* section is provided by the `pytest-metadata
<https://pypi.python.org/pypi/pytest-metadata/>`_, plugin, and can be accessed
via the :code:`pytest_configure` hook:

.. code-block:: python

  def pytest_configure(config):
      config._metadata['foo'] = 'bar'

The generated table will be sorted alphabetically unless the metadata is a
:code:`collections.OrderedDict`.

Additional summary information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can edit the *Summary* section by using the :code:`pytest_html_results_summary` hook:

.. code-block:: python

   import pytest
   from py.xml import html

   @pytest.mark.optionalhook
   def pytest_html_results_summary(summary):
       summary.extend([html.p("foo: bar")])

Extra content
~~~~~~~~~~~~~

You can add details to the HTML reports by appending to the 'extra' list on one
of the nodes in the :code:`pytest_html_add_node_chain_extra` hook. The nodes
represent the different levels of branching logic of your tests, and extra
content can be added for each of them. The extra content added to the nodes is
also persistent from test to test, so you can see what was added as the tests
run. The :code:`item` argument is also provided immediately following each
test's execution, and can provide a gateway to accessing resources used by the
test.

Here are the types of extra content that can be added:

==========  ============================================
Type        Example
==========  ============================================
Raw HTML    ``extra.html('<div>Additional HTML</div>')``
`JSON`_     ``extra.json({'name': 'pytest'})``
Plain text  ``extra.text('Add some simple Text')``
URL         ``extra.url('http://www.example.com/')``
Image       ``extra.image(image, mime_type='image/gif', extension='gif')``
Image       ``extra.image('/path/to/file.png')``
Image       ``extra.image('http://some_image.png')``
==========  ============================================

**Note**: When adding an image from file, the path can be either absolute
or relative.

**Note**: When using ``--self-contained-html``, images added as files or links
may not work as expected, see section `Creating a self-contained report`_ for
more info.

There are also convenient types for several image formats:

============  ====================
Image format  Example
============  ====================
PNG           ``extra.png(image)``
JPEG          ``extra.jpg(image)``
SVG           ``extra.svg(image)``
============  ====================

The following example adds the various types of extras using a
:code:`pytest_html_add_node_chain_extra` hook, which can be implemented in a
plugin or conftest.py file:

.. code-block:: python

  import pytest

  def pytest_html_add_node_chain_extra(item, outcome, extra, node_chain):
      pytest_html = item.config.pluginmanager.getplugin('html')
      module_node = None
      for node in node_chain:
          if node.name.endswith(".py"):
              module_node = node
              break
      if module_node.extra:
          # already has extra
          return
      # always add url to report
      module_node.extra.append(pytest_html.extras.url('http://www.example.com/'))
      if outcome == 'Failed':
          # only add additional html on failure
          module_node.extra.append(pytest_html.extras.html('<div>Additional HTML</div>'))

You can also specify the :code:`name` argument for all types other than :code:`html` which will change the title of the
created hyper link:

.. code-block:: python

    extra.append(pytest_html.extras.text('some string', name='Different title'))

Display options
---------------

By default, all rows in the **Results** table will be expanded except those that have :code:`Passed`.

This behavior can be customized with a query parameter: :code:`?collapsed=Passed,XFailed,Skipped`.


Screenshots
-----------

.. image:: https://cloud.githubusercontent.com/assets/122800/11952194/62daa964-a88e-11e5-9745-2aa5b714c8bb.png
   :target: https://cloud.githubusercontent.com/assets/122800/11951695/f371b926-a88a-11e5-91c2-499166776bd3.png
   :alt: Enhanced HTML report

Contributing
------------

Fork the repository and submit PRs with bug fixes and enhancements,  contributions are very welcome.

Tests can be run locally with `tox`_, for example to execute tests for Python 2.7 and 3.6 execute::

    tox -e py27,py36


.. _`tox`: https://tox.readthedocs.org/en/latest/

Resources
---------

- `Release Notes <http://github.com/pytest-dev/pytest-html/blob/master/CHANGES.rst>`_
- `Issue Tracker <http://github.com/pytest-dev/pytest-html/issues>`_
- `Code <http://github.com/pytest-dev/pytest-html/>`_

.. _JSON: http://json.org/
