# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import absolute_import

from base64 import b64encode, b64decode
from collections import OrderedDict
from os.path import isfile
import datetime
import json
import os
import pkg_resources
import sys
import time
import bisect
import hashlib
import warnings

import pytest
from execnet.gateway_base import _Serializer

try:
    from ansi2html import Ansi2HTMLConverter, style
    ANSI = True
except ImportError:
    # ansi2html is not installed
    ANSI = False

from py.xml import html, raw

from . import extras
from . import __version__, __pypi_url__

PY3 = sys.version_info[0] == 3

# Python 2.X and 3.X compatibility
if PY3:
    basestring = str
    from html import escape
else:
    from codecs import open
    from cgi import escape


def pytest_addhooks(pluginmanager):
    from . import hooks
    pluginmanager.add_hookspecs(hooks)


def pytest_addoption(parser):
    group = parser.getgroup('terminal reporting')
    group.addoption('--html', action='store', dest='htmlpath',
                    metavar='path', default=None,
                    help='create html report file at given path.')
    group.addoption('--self-contained-html', action='store_true',
                    help='create a self-contained html file containing all '
                    'necessary styles, scripts, and images - this means '
                    'that the report may not render or function where CSP '
                    'restrictions are in place (see '
                    'https://developer.mozilla.org/docs/Web/Security/CSP)')
    group.addoption('--css', action='append', metavar='path',
                    help='append given css file content to report style file.')
    group.addoption('--js', action='append', metavar='path',
                    help='append given js file content to report script file.')
    group.addoption('--no-group-on-worker', action='store_true',
                    help='do not group tests by their xdist worker, like they '
                    'would be grouped for things like packages, modules, and '
                    'classes.')


def pytest_configure(config):
    htmlpath = config.getoption('htmlpath')
    if htmlpath:
        for csspath in config.getoption('css') or []:
            open(csspath)
        for jspath in config.getoption('js') or []:
            open(jspath)
        if not hasattr(config, 'slaveinput'):
            # prevent opening htmlpath on slave nodes (xdist)
            config._html = HTMLReport(htmlpath, config)
            config.pluginmanager.register(config._html)


def pytest_unconfigure(config):
    html = getattr(config, '_html', None)
    if html:
        del config._html
        config.pluginmanager.unregister(html)


def data_uri(content, mime_type='text/plain', charset='utf-8'):
    data = b64encode(content.encode(charset)).decode('ascii')
    return 'data:{0};charset={1};base64,{2}'.format(mime_type, charset, data)


class SerializableParamFixInfo(object):
    """Used to store the current state of the FixtureDef for later comparison.

    While the parameterized FixtureDef is changing from one of its parameters to
    another, it's still the same object. This means that later comparison to
    itself when checking for the same param set won't work. This class is meant
    to store information about the state of the FixtureDef when the test was
    running so it can be compared to the fixtures used by other tests in a more
    logical means to determine if the tests should be grouped together.

    This class also ensures that whenever creating an instance of it, if an
    instance that matches it was already created, the one that was already
    created is the one returned. This prevents dealing with more complicated
    lookups in the tree and allows for simpler comparisons.
    """

    _instances = []
    _alread_initialized = False

    def __new__(cls, name, description, param_index, baseid):
        temp = super(SerializableParamFixInfo, cls).__new__(cls)
        temp.__init__(name, description, param_index, baseid)
        if temp not in cls._instances:
            cls._instances.append(temp)
            return temp
        return cls._instances[cls._instances.index(temp)]

    def __init__(self, name, description, param_index, baseid):
        if self._alread_initialized:
            return

        self.name = name

        methodname = 'save_' + type(description).__name__
        if not hasattr(_Serializer, methodname):
            description = str(description)
        self.description = description

        self.param_index = param_index
        self.baseid = baseid
        self._alread_initialized = True

    def __eq__(self, other):
        if not isinstance(other, SerializableParamFixInfo):
            return False

        same_name = self.name == other.name
        same_description = self.description == other.description
        same_param_index = self.param_index == other.param_index
        same_baseid = self.baseid == other.baseid
        return all((
            same_name,
            same_description,
            same_param_index,
            same_baseid,
        ))

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "param_index": self.param_index,
            "baseid": self.baseid,
        }

    def serialize(self):
        return {
            "name": self.name,
            "description": repr(self.description),
            "param_index": self.param_index,
            "baseid": self.baseid,
        }


class SerializableNode(object):
    """Branching node in test suite tree structure.

    This represents a single level of the namespace for the location of a test.
    It can be a branching node, in that parameterization occured at this level,
    which created multiple versions of the tests contained within it. If
    branching occurred, this class serves to track that and make sure the set of
    parameters that were provided to the branch can be referenced. For each set
    of parameters provided for a Node, there will be a separate Node instance.

    This class also ensures that whenever creating an instance of it, if an
    instance that matches it was already created, the one that was already
    created is the one returned. This prevents dealing with more complicated
    lookups in the tree and allows for simpler comparisons. Additionally, adding
    child nodes or tests to a Node is made trivial, as the results_tree doesn't
    have to be traversed to find the Node you want to append a Node/test to.

    In order to support ``pytest-xdist``, this information can't just be passed
    up to the master from the slave that is actually running the test. Instead,
    the slave can only pass serialized information to the master, and, ideally,
    only using established attributes of a normal test report. This class allows
    the node chain information to be serialized in such a way that the slave can
    pass it up to the master, without losing any information needed by the
    master to rebuild the node chain as it generates the HTML report.

    Due to similar functionality being required, this class is used to represent
    the nodes both before and after the slave sends the serialized information
    to the master. The ``before_serialization`` attribute is used to determine
    which side of that event the node is currently being used on. This is
    necessary, as without it, if ``pytest-xdist`` were not being used, there
    would only be one Python environment, and when trying to parse the
    serialized versions of the nodes, they would conflict with the nodes created
    before the serialization event, and some information would be lost (e.g.
    test logs). When a node is serialized, this attribute isn't included, so
    when the nodes are reconstructed, it will automatically be ``False``.
    """

    _instances = []
    _alread_initialized = False

    def __new__(cls, **kwargs):
        temp = super(SerializableNode, cls).__new__(cls)
        temp.__init__(**kwargs)
        if temp not in cls._instances:
            cls._instances.append(temp)
            return temp
        node = cls._instances[cls._instances.index(temp)]
        if node.extra != temp.extra:
            node.extra.extend(temp.extra)
        return node

    def __init__(self, **kwargs):
        if self._alread_initialized:
            return
        self.name = kwargs["name"]
        defaults = (
            ("parent", None),
            ("params", []),
            ("duration", 0.0),
            ("outcome", None),
            ("extra", []),
            ("nodeid", None),
            ("location", None),
            ("log", None),
            ("is_test", False),
            ("is_xdist_slave", False),
            ("children", []),
            ("test_results", []),
            ("before_serialization", False),
        )

        for attr, value in defaults:
            if attr == "params":
                params = kwargs.get(attr, value)
                self.params = [SerializableParamFixInfo(**p) for p in params]
            else:
                setattr(self, attr, kwargs.get(attr, value))
        if not self.is_test:
            self.summary = kwargs.get(
                "summary",
                {
                    "passed": 0,
                    "skipped": 0,
                    "failed": 0,
                    "error": 0,
                    "xfailed": 0,
                    "xpassed": 0,
                },
            )
        else:
            self.summary = None
        self._alread_initialized = True

    def __eq__(self, other):
        if not isinstance(other, SerializableNode):
            return False

        eq_attrs = (
            "name",
            "parent",
            "params",
            "nodeid",
            "location",
            "before_serialization",
        )
        return all(getattr(self, a) == getattr(other, a) for a in eq_attrs)

    @property
    def param_description(self):
        return "-".join(str(p.description) for p in self.params)

    def to_dict(self):
        """Convert the structure to one that is JSON serializable."""
        json_repr = {
            "name": escape(self.name),
            "duration": "{0:.2f}".format(self.duration),
            "params": [p.to_dict() for p in self.params],
            "param_description": escape(self.param_description),
            "extra": self.extra,
            "log": self.log,
        }
        if self.is_test:
            if self.nodeid is not None:
                json_repr["nodeid"] = escape(self.nodeid)
            else:
                json_repr["nodeid"] = "Unknown"
            if self.location is not None:
                json_repr["location"] = self.location
            else:
                json_repr["location"] = "Unknown"
            json_repr["location"] = self.location
            json_repr["outcome"] = self.outcome
        else:
            json_repr["summary"] = self.summary
            json_repr["children"] = [c.to_dict() for c in self.children]
            json_repr["test_results"] = [c.to_dict() for c in self.test_results]
            if self.is_xdist_slave:
                json_repr["is_xdist_slave"] = True
        return json_repr

    def to_serializable_node_chain_link(self):
        """Convert to something that can be serialized in a list of other nodes.

        In the event that ``pytest-xdist`` is used, the information about this
        test, and the node structure it resides in, need to be able to be passed
        up to the master, which means only simple data structures can be used to
        represent them. Enough information needs to be provided so that the
        complete test suite structure can be properly recreated once all the
        tests are done running, and the HTML report is about to be generated.

        The node structure needs to be determined in the slave as this is the
        only time that the parameterized fixtures can be evaluated to figure out
        how and where things like parameterization, scope, and autouse of the
        fixtures are branching the test running flow. This also presents an
        opportune time to allow the test author to handle test complications and
        gather data that can be applied to the node chain at the desired level
        as ``extra``, so it can later be embedded in the HTML report. For
        example, taking a screenshot of a browser when a test fails, but
        attaching it to the module level node, so it shows up in the HTML report
        at the top of that section.
        """
        serialized = {
            "name": self.name,
            "params": [p.serialize() for p in self.params],
            "nodeid": self.nodeid,
            "location": self.location,
            "log": self.log,
            "is_test": self.is_test,
            "is_xdist_slave": self.is_xdist_slave,
            "extra": self.extra,
        }
        if self.is_test:
            serialized["outcome"] = self.outcome
            serialized["duration"] = self.duration
        return serialized


class HTMLReport(object):

    results_tree = {
        "summary": {
            "passed": 0,
            "skipped": 0,
            "failed": 0,
            "error": 0,
            "xfailed": 0,
            "xpassed": 0,
        },
        "results": [],
    }

    def __init__(self, logfile, config):
        logfile = os.path.expanduser(os.path.expandvars(logfile))
        self.logfile = os.path.abspath(logfile)
        self.test_logs = []
        self.results = []
        self.errors = self.failed = 0
        self.passed = self.skipped = 0
        self.xfailed = self.xpassed = 0
        has_rerun = config.pluginmanager.hasplugin('rerunfailures')
        self.rerun = 0 if has_rerun else None
        self.self_contained = config.getoption('self_contained_html')
        self.config = config

    def results_tree_to_dict(self, session):
        rslts_tree = self.__class__.results_tree
        return {
            "name": session.name,
            "summary": rslts_tree["summary"],
            "results": [n.to_dict() for n in rslts_tree["results"]],
            "suite_info": {
                "generated": rslts_tree["suite_info"]["generated"].isoformat(),
                "run_time": rslts_tree["suite_info"]["run_time"],
                "numtests": rslts_tree["suite_info"]["numtests"],
                "environment": rslts_tree["suite_info"]["environment"],
            },
        }

    def _appendrow(self, outcome, report):
        outcome = outcome.lower()
        node_chain = None
        if not hasattr(report, "user_properties"):
            return
        for prop in report.user_properties:
            if prop[0] == "pytest_html_report_node_chain":
                node_chain = prop[1]
                report.user_properties.remove(prop)
                break

        if node_chain is None:
            raise Exception(
                (
                    "'pytest_html_report_node_chain' not found in "
                    "'report.user_properties'"
                ),
            )

        duration = node_chain[-1]["duration"]

        results_tree = self.__class__.results_tree
        results_tree["summary"][outcome] += 1

        prev_node = None
        for n in node_chain:
            if n.get("is_test", False):
                n["log"] = get_log_from_report(report)
            node = SerializableNode(parent=prev_node, **n)
            if node.is_test:
                if prev_node is None:
                    raise Exception("'prev_node' is None when it shouldn't be.")
                prev_node.test_results.append(node)
                continue
            node.summary[outcome] += 1
            node.duration += duration
            if prev_node is None and node not in results_tree["results"]:
                results_tree["results"].append(node)
            if prev_node is not None and node not in prev_node.children:
                prev_node.children.append(node)
            prev_node = node

    def append_passed(self, report):
        if report.when == 'call':
            if hasattr(report, "wasxfail"):
                self.xpassed += 1
                self._appendrow('XPassed', report)
            else:
                self.passed += 1
                self._appendrow('Passed', report)

    def append_failed(self, report):
        if getattr(report, 'when', None) == "call":
            if hasattr(report, "wasxfail"):
                # pytest < 3.0 marked xpasses as failures
                self.xpassed += 1
                self._appendrow('XPassed', report)
            else:
                self.failed += 1
                self._appendrow('Failed', report)
        else:
            self.errors += 1
            self._appendrow('Error', report)

    def append_skipped(self, report):
        if hasattr(report, "wasxfail"):
            self.xfailed += 1
            self._appendrow('XFailed', report)
        else:
            self.skipped += 1
            self._appendrow('Skipped', report)

    def append_other(self, report):
        # For now, the only "other" the plugin give support is rerun
        self.rerun += 1
        self._appendrow('Rerun', report)

    def _generate_report(self, session):
        suite_stop_time = time.time()
        suite_time_delta = suite_stop_time - self.suite_start_time
        numtests = self.passed + self.failed + self.xpassed + self.xfailed
        generated = datetime.datetime.now()
        environment = []
        metadata = getattr(session.config, "_metadata", None)
        if metadata is not None:
            environment = metadata

        self.__class__.results_tree["suite_info"] = {
            "generated": generated,
            "run_time": suite_time_delta,
            "numtests": numtests,
            "environment": environment,
        }

        self.style_css = pkg_resources.resource_string(
            __name__, os.path.join('resources', 'style.css'))
        if PY3:
            self.style_css = self.style_css.decode('utf-8')

        if ANSI:
            ansi_css = [
                '\n/******************************',
                ' * ANSI2HTML STYLES',
                ' ******************************/\n']
            ansi_css.extend([str(r) for r in style.get_styles()])
            self.style_css += '\n'.join(ansi_css)

        # <DF> Add user-provided CSS
        for path in self.config.getoption('css') or []:
            self.style_css += '\n/******************************'
            self.style_css += '\n * CUSTOM CSS'
            self.style_css += '\n * {}'.format(path)
            self.style_css += '\n ******************************/\n\n'
            with open(path, 'r') as f:
                self.style_css += f.read()

        css_href = '{0}/{1}'.format('assets', 'style.css')
        html_css = html.link(href=css_href, rel='stylesheet',
                             type='text/css')
        if self.self_contained:
            html_css = html.style(raw(self.style_css))

        self.js_script = pkg_resources.resource_string(
            __name__, os.path.join('resources', 'main.js'))
        if PY3:
            self.js_script = self.js_script.decode('utf-8')

        # <DF> Add user-provided JS
        for path in self.config.getoption('js') or []:
            self.js_script += '\n/******************************'
            self.js_script += '\n * CUSTOM JS'
            self.js_script += '\n * {}'.format(path)
            self.js_script += '\n ******************************/\n\n'
            with open(path, 'r') as f:
                self.js_script += f.read()

        results_tree_dict = self.results_tree_to_dict(session)
        results_tree_json = json.dumps(results_tree_dict, indent=2)
        project_name = results_tree_dict["name"]
        self.js_script += "\n\nprojectName = '{}'".format(project_name)
        self.js_script += "\n\nresultsTree = {}".format(results_tree_json)

        js_ref = '{0}/{1}'.format('assets', 'script.js')
        html_script = html.script(src=js_ref, type='text/javascript')
        if self.self_contained:
            html_script = html.script(raw(self.js_script))

        html_head = html.head(
            html.meta(charset='utf-8'),
            html.title('Test Report'),
            html_css,
            html_script,
        )

        html_body = self._generate_body(results_tree_dict)

        doc = html.html()

        doc.extend(
            [
                html_head,
                html_body,
            ],
        )

        unicode_doc = u'<!DOCTYPE html>\n{0}'.format(doc.unicode(indent=2))
        if PY3:
            # Fix encoding issues, e.g. with surrogates
            unicode_doc = unicode_doc.encode('utf-8',
                                             errors='xmlcharrefreplace')
            unicode_doc = unicode_doc.decode('utf-8')
        return unicode_doc

    def _generate_environment(self, environment_details):
        rows = []

        keys = [k for k in environment_details.keys() if environment_details[k]]
        if not isinstance(environment_details, OrderedDict):
            keys.sort()

        for key in keys:
            value = environment_details[key]
            if isinstance(value, basestring) and value.startswith("http"):
                value = html.a(value, href=value, target="_blank")
            elif isinstance(value, (list, tuple, set)):
                value = ", ".join((str(i) for i in value))
            rows.append(html.tr(html.td(key), html.td(value)))

        environment = html.div(
            html.h2("Environment"),
            html.div(
                html.table(rows, id="environment"),
                class_="environment-info",
            ),
            class_="environment-details",
        )
        return environment

    def _generate_summary_count(self, numtests, summary, run_time):
        summary_count = html.div(
            html.h2("Summary"),
            html.div(
                html.p(
                    "{0} tests ran in {1:.2f} seconds.".format(
                        numtests,
                        run_time,
                    ),
                ),
                html.p(
                    "Toggle the buttons to filter the results.",
                    class_="filter",
                ),
                html.div(
                    html.button(
                        html.div("Passes", class_="button-text"),
                        html.div(
                            summary["passed"],
                            class_="summary-result-count passed",
                        ),
                        class_="count-toggle-button passed",
                        title="Passes",
                    ),
                    html.button(
                        html.div("Skips", class_="button-text"),
                        html.div(
                            summary["skipped"],
                            class_="summary-result-count skipped",
                        ),
                        class_="count-toggle-button skipped",
                        title="Skips",
                    ),
                    html.button(
                        html.div("Failures", class_="button-text"),
                        html.div(
                            summary["failed"],
                            class_="summary-result-count failed",
                        ),
                        class_="count-toggle-button failed",
                        title="Failures",
                    ),
                    html.button(
                        html.div("Errors", class_="button-text"),
                        html.div(
                            summary["error"],
                            class_="summary-result-count error",
                        ),
                        class_="count-toggle-button error",
                        title="Errors",
                    ),
                    html.button(
                        html.div("Expected failures", class_="button-text"),
                        html.div(
                            summary["xfailed"],
                            class_="summary-result-count xfailed",
                        ),
                        class_="count-toggle-button xfailed",
                        title="Expected failures",
                    ),
                    html.button(
                        html.div("Unexpected passes", class_="button-text"),
                        html.div(
                            summary["xpassed"],
                            class_="summary-result-count xpassed",
                        ),
                        class_="count-toggle-button xpassed",
                        title="Unexpected passes",
                    ),
                    class_="results-summary-numbers",
                ),
                class_="summary-info",
            ),
            class_="summary-details",
        )
        return summary_count

    def _generate_body(self, results_tree):
        body = html.body(onload="init()")

        generated_time = datetime.datetime.strptime(
            results_tree["suite_info"]["generated"].split(".")[0],
            "%Y-%I-%dT%X",
        )
        summary_div = [html.div(
            html.div(results_tree["name"], class_="project-title"),
            html.div(
                html.p(
                    'Report generated on {0} at {1} by'.format(
                        generated_time.strftime('%d-%b-%Y'),
                        generated_time.strftime('%H:%M:%S')
                    ),
                    html.a(' pytest-html', href=__pypi_url__),
                    ' v{0}'.format(__version__),
                    class_="generated-time"
                ),
                class_="generated-info",
            ),
            self._generate_environment(
                results_tree["suite_info"]["environment"],
            ),
            self._generate_summary_count(
                results_tree["suite_info"]["numtests"],
                results_tree["summary"],
                results_tree["suite_info"]["run_time"],
            ),
            class_="project-test-results-summary",
        )]
        self.config.hook.pytest_html_results_summary(summary=summary_div)
        results_div = [html.div(
            html.h2("Results"),
            html.div(
                html.button("expand all", id="expand-all-button"),
                html.button("collapse all", id="collapse-all-button"),
                class_="show-hide-buttons",
            ),
            html.div(class_="results-info"),
            class_="results-details",
        )]
        body.extend([
            summary_div,
            results_div,
        ])
        return body

    def _save_report(self, report_content):
        dir_name = os.path.dirname(self.logfile)
        assets_dir = os.path.join(dir_name, 'assets')

        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        if not self.self_contained and not os.path.exists(assets_dir):
            os.makedirs(assets_dir)

        with open(self.logfile, 'w', encoding='utf-8') as f:
            f.write(report_content)
        if not self.self_contained:
            style_path = os.path.join(assets_dir, 'style.css')
            with open(style_path, 'w', encoding='utf-8') as f:
                f.write(self.style_css)

    def pytest_runtest_logreport(self, report):
        if report.passed:
            self.append_passed(report)
        elif report.failed:
            self.append_failed(report)
        elif report.skipped:
            self.append_skipped(report)
        else:
            self.append_other(report)

    def pytest_collectreport(self, report):
        if report.failed:
            self.append_failed(report)

    def pytest_sessionstart(self, session):
        self.suite_start_time = time.time()

    def pytest_sessionfinish(self, session):
        report_content = self._generate_report(session)
        self._save_report(report_content)

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_sep('-', 'generated html file: {0}'.format(
            self.logfile))


def get_fixture_dependancies(name, fixturedefs):
    if name not in fixturedefs.keys():
        return set()
    fix = fixturedefs[name][0]
    dependancies = set()
    for arg in fix.argnames:
        dependancies.add(arg)
        dependancies.update(get_fixture_dependancies(arg, fixturedefs))
    return dependancies


def pytest_fixture_setup(fixturedef, request):
    fixturedef.param_index = request.param_index


def get_namespace_chain(nodeid):
    try:
        param_start_index = nodeid.index("[")
        package_chain = nodeid[:param_start_index]
    except ValueError:
        package_chain = nodeid
    package_chain = package_chain.split("/")
    local_chain = package_chain.pop()
    local_chain = local_chain.replace("::()", "")
    local_chain = local_chain.split("::")
    chain = package_chain + local_chain
    return chain


def get_parameterized_fixtures_with_effective_autouse(item):
    # determine all the dependancies each fixture has of other fixtures
    dependancies = {}
    for fname, v in item._fixtureinfo.name2fixturedefs.items():
        fix = v[-1]

        fix.param_index = item.callspec.indices.get(fix.argname, 0)
        dependancies[fname] = get_fixture_dependancies(
            fname,
            item._fixtureinfo.name2fixturedefs,
        )

    # find the fixtures that are parameterized
    param_fixtures = {}
    for k, v in item._fixtureinfo.name2fixturedefs.items():
        fix = v[-1]
        if fix.params:
            if hasattr(fix, "cached_result"):
                param_description = fix.params[fix.param_index]
                if fix.ids:
                    # assume iterable
                    try:
                        param_description = fix.ids[fix.param_index]
                    except TypeError:
                        # assume callable
                        param_description = fix.ids(param_description)
            else:
                param_description = None
        else:
            param_description = None
        autouse = getattr(
            getattr(fix.func, "_pytestfixturefunction", True),
            "autouse",
            True,
        )
        param_fixtures[k] = {
            "name": fix.argname,
            "description": param_description,
            "param_index": fix.param_index,
            "scopenum": fix.scopenum,
            "scope": fix.scope,
            "autouse": autouse,
            "baseid": fix.baseid,
            "fixturedef": fix,
            "parameterized": bool(fix.params),
        }

    # determine how `autouse` is being cascaded through the fixtures based
    # on fixture dependancy
    for fixname in param_fixtures.keys():
        for fixk, fixd in dependancies.items():
            if not param_fixtures[fixk]["autouse"]:
                # won't cascade autouse anyway
                continue
            if fixname in fixd:
                # fixk is dependant on fixname and fixk is autouse, so
                # fixname is now also autouse
                param_fixtures[fixname]["autouse"] = True
                break

    param_fixtures = [d for d in param_fixtures.values()]

    param_fixtures = sorted(param_fixtures, key=lambda d: d["scopenum"])

    return param_fixtures


def get_parameterized_simple_node_chain(item, simple_node_chain,
                                        param_fixtures):
    SESSION_SCOPE = "session"
    MODULE_SCOPE = "module"
    CLASS_SCOPE = "class"
    FUNCTION_SCOPE = "function"

    # determine where a parameterized fixture effectively caused a branch in the
    # flow of tests, and associate it with that node.
    for pf in param_fixtures:
        if not pf["parameterized"]:
            continue
        simplified_fixture = {
            "name": pf["name"],
            "description": pf["description"],
            "param_index": pf["param_index"],
            "baseid": pf["baseid"],
        }
        chain = get_namespace_chain(pf["baseid"])

        if pf["scope"] == FUNCTION_SCOPE or pf["autouse"] is False:
            # if a parameterized fixture isn't set for autouse, or the
            # parameterized fixture is of function scope, then no matter
            # where the fixture is defined, it will only branch on the
            # function.
            simple_node_chain[-1]["params"].append(simplified_fixture)
        elif pf["scope"] == SESSION_SCOPE:
            # parameterized session scope fixtures will branch on whatever
            # scope they are defined in, e.g. one defined in a class will
            # branch on that class and won't impact anything else.
            index = len(chain) - 1
            simple_node_chain[index]["params"].append(simplified_fixture)
        elif pf["scope"] == MODULE_SCOPE:
            # parameterized module scope fixtures will mostly branch on
            # whatever scope they are defined in, e.g. one defined in a
            # class will branch on that class and won't impact anything
            # else. But if it's defined in the conftest.py, it will branch
            # on each module within the package.
            module_depth = len(item.module.__name__.split("."))
            fixture_depth = len(pf["baseid"].split("/"))
            if fixture_depth <= module_depth:
                # the fixture was defined either outside the module, or in
                # the namespace of the module, so it will be applied on the
                # module.
                index = module_depth - 1
            else:
                # the fixture was defined in the namespace of something in
                # the module, so it will be applied only to the scope it was
                # defined in.
                index = index = len(chain) - 1
            simple_node_chain[index]["params"].append(simplified_fixture)
        elif pf["scope"] == CLASS_SCOPE:
            # parameterized class scope fixtures will branch on classes
            # whatever scope they are defined in, e.g. one defined in a
            # class will branch on that class and won't impact anything
            # else. But if it's defined in the conftest.py, it will branch
            # on each module within the package.
            simple_node_chain[-2]["params"].append(simplified_fixture)
        continue

    return simple_node_chain


def get_node_chain(item, outcome, duration):
    namespace_chain = get_namespace_chain(item.nodeid)
    simple_node_chain = [{"name": n, "params": []} for n in namespace_chain]

    param_fixtures = get_parameterized_fixtures_with_effective_autouse(item)

    simple_node_chain = get_parameterized_simple_node_chain(
        item,
        simple_node_chain,
        param_fixtures,
    )

    node_chain = []

    prev_node = None

    if not item.config.getoption('no_group_on_worker'):
        if hasattr(item.config, 'slaveinput'):
            node = SerializableNode(
                name=item.config.slaveinput['slaveid'],
                is_xdist_slave=True,
                before_serialization=True,
            )
            node_chain.append(node)
            prev_node = node

    for n in simple_node_chain:
        is_test = n is simple_node_chain[-1]
        kwargs = {
            "name": n["name"],
            "is_test": is_test,
            "params": n["params"],
            "parent": prev_node,
            "before_serialization": True,
        }
        if is_test:
            kwargs["location"] = item.location
            kwargs["nodeid"] = item.nodeid
            kwargs["outcome"] = outcome
            kwargs["duration"] = duration

        node = SerializableNode(**kwargs)
        node_chain.append(node)
        prev_node = node

    return node_chain


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    for prop in item.user_properties:
        if isinstance(prop, tuple):
            if prop[0] == "pytest_html_report_node_chain":
                yield
                return

    outcome = yield
    report = outcome.get_result()

    outcome = None

    wasxfail = hasattr(report, "wasxfail")
    if report.skipped:
        if wasxfail:
            outcome = "XFailed"
        else:
            outcome = "Skipped"
    elif getattr(report, "when", None) == "call":
        if report.passed:
            if wasxfail:
                outcome = "XPassed"
            else:
                outcome = "Passed"
        elif report.failed:
            if wasxfail:
                outcome = "XPassed"
            else:
                outcome = "Failed"
    elif report.failed:
        outcome = "Error"

    if outcome is None:
        return

    duration = getattr(report, "duration", 0.0)

    node_chain = get_node_chain(item, outcome, duration)

    extra = getattr(report, "extra", [])

    item.config.hook.pytest_html_add_node_chain_extra(
        item=item,
        outcome=outcome,
        extra=extra,
        node_chain=node_chain,
    )
    report.user_properties.append((
        "pytest_html_report_node_chain",
        list(node.to_serializable_node_chain_link() for node in node_chain),
    ))


def get_log_from_report(report):
    log = html.div(class_='log')
    if report.longrepr:
        for line in report.longreprtext.splitlines():
            separator = line.startswith('_ ' * 10)
            if separator:
                log.append(line[:80])
            else:
                exception = line.startswith("E   ")
                if exception:
                    log.append(html.span(raw(escape(line)),
                                         class_='error'))
                else:
                    log.append(raw(escape(line)))
            log.append(html.br())

    for section in report.sections:
        header, content = map(escape, section)
        log.append(' {0} '.format(header).center(80, '-'))
        log.append(html.br())
        if ANSI:
            converter = Ansi2HTMLConverter(inline=False, escaped=False)
            content = converter.convert(content, full=False)
        log.append(raw(content))

    if len(log) == 0:
        log = html.div(class_='empty log')
        log.append('No log output captured.')

    unicode_log = log.unicode(indent=2)
    if PY3:
        # Fix encoding issues, e.g. with surrogates
        unicode_log = unicode_log.encode('utf-8',
                                         errors='xmlcharrefreplace')
        unicode_log = unicode_log.decode('utf-8')
    return unicode_log
