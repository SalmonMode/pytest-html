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

try:
    from ansi2html import Ansi2HTMLConverter, style
    ANSI = True
except ImportError:
    # ansi2html is not installed
    ANSI = False

from py.xml import html, raw
import pytest

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


def pytest_configure(config):
    htmlpath = config.getoption('htmlpath')
    if htmlpath:
        for csspath in config.getoption('css') or []:
            open(csspath)
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


class ParameterizedFixtureStateInfo(object):
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

    _pfsi_instances = []
    _alread_initialized = False

    def __new__(cls, fixture_def, param_index):
        temp = super(ParameterizedFixtureStateInfo, cls).__new__(cls)
        temp.__init__(fixture_def, param_index)
        if temp not in cls._pfsi_instances:
            cls._pfsi_instances.append(temp)
            return temp
        return cls._pfsi_instances[cls._pfsi_instances.index(temp)]

    def __init__(self, fixture_def, param_index):
        if self._alread_initialized:
            return
        self.fixture_def = fixture_def
        self.param_index = param_index
        if hasattr(self.fixture_def, "cached_result"):
            self.cached_result = list(escape(str(i)) for i in self.fixture_def.cached_result)
        else:
            self.cached_result = None

    @property
    def name(self):
        return self.fixture_def.argname

    @property
    def baseid(self):
        return self.fixture_def.baseid

    @property
    def fixture_scope(self):
        return self.fixture_def.scope

    @property
    def value(self):
        if self.param_index is not None:
            return self.fixture_def.params[self.param_index]
        else:
            return "unknown"

    @property
    def description(self):
        if self.fixture_def.ids and self.param_index is not None:
            # assume iterable
            try:
                return self.fixture_def.ids[self.param_index]
            except TypeError:
                try:
                    # assume callable
                    return self.fixture_def.ids(self.value)
                except TypeError:
                    # just return the value
                    return self.value
        return self.value

    def __eq__(self, other):
        if not isinstance(other, ParameterizedFixtureStateInfo):
            return False
        same_fix_def = self.fixture_def == other.fixture_def
        same_param_index = self.param_index == other.param_index
        return same_fix_def and same_param_index

    def to_dict(self):
        return {
            "param_index": self.param_index,
            "cached_result": self.cached_result,
            "name": escape(self.name),
            "baseid": escape(self.baseid),
            "fixture_scope": self.fixture_scope,
            "value": escape(str(self.value)),
            "description": escape(str(self.description)),
        }


class Node(object):
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
    """

    _node_instances = []
    _alread_initialized = False

    def __new__(cls, name, namespace, parent, params=()):
        temp = super(Node, cls).__new__(cls)
        temp.__init__(name, namespace, parent, params)
        if temp not in cls._node_instances:
            cls._node_instances.append(temp)
            return temp
        node = cls._node_instances[cls._node_instances.index(temp)]
        return node

    def __init__(self, name, namespace, parent, params=()):
        if self._alread_initialized:
            return
        self.name = name
        self.namespace = namespace
        self.params = tuple(params)
        self.children = []
        self.extra = []
        self.test_results = []
        self.summary = {
            "passed": 0,
            "skipped": 0,
            "failed": 0,
            "error": 0,
            "xfailed": 0,
            "xpassed": 0,
        }
        self.duration = 0.0
        self.parent_node = parent
        self._alread_initialized = True

    @property
    def param_description(self):
        return "-".join(str(p.description) for p in self.params)

    def __eq__(self, other):
        if not isinstance(other, Node):
            return False
        same_name = self.name == other.name
        same_params = self.params == other.params
        same_namespace = self.namespace == other.namespace
        same_parent = self.parent_node == other.parent_node
        return same_name and same_namespace and same_params and same_parent

    def to_dict(self):
        return {
            "name": escape(self.name),
            "namespace":escape(self.namespace),
            "summary": self.summary,
            "duration": "{0:.2f}".format(self.duration),
            "params": [p.to_dict() for p in self.params],
            "param_description": escape(self.param_description),
            "children": [c.to_dict() for c in self.children],
            "test_results": [t.to_dict() for t in self.test_results],
            "extra": self.extra,
        }


class SimplifiedTestResult(object):

    def __init__(self, name, nodeid, location, outcome, duration, log, extra=None, params=()):
        if extra is None:
            extra = []
        self.name = name
        self.nodeid = nodeid
        self.outcome = outcome
        self.params = params
        self.location = location
        self.duration = duration
        self.log = log
        self.extra = extra

    @property
    def param_description(self):
        return "-".join(p.description for p in self.params)

    def to_dict(self):
        return {
            "name": escape(self.name),
            "nodeid": escape(self.nodeid),
            "outcome": self.outcome,
            "params": [p.to_dict() for p in self.params],
            "location": self.location,
            "param_description": escape(self.param_description),
            "duration": "{0:.2f}".format(self.duration),
            "log": self.log,
            "extra": self.extra,
        }


class HTMLReport(object):

    def __init__(self, logfile, config):
        logfile = os.path.expanduser(os.path.expandvars(logfile))
        self.logfile = os.path.abspath(logfile)
        self.test_logs = []
        self.results = []
        self.results_tree = {
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
        self.errors = self.failed = 0
        self.passed = self.skipped = 0
        self.xfailed = self.xpassed = 0
        has_rerun = config.pluginmanager.hasplugin('rerunfailures')
        self.rerun = 0 if has_rerun else None
        self.self_contained = config.getoption('self_contained_html')
        self.config = config

    class TestResult:

        def __init__(self, outcome, report, logfile, config):
            self.test_id = report.nodeid
            if getattr(report, 'when', 'call') != 'call':
                self.test_id = '::'.join([report.nodeid, report.when])
            self.time = getattr(report, 'duration', 0.0)
            self.outcome = outcome
            self.additional_html = []
            self.links_html = []
            self.self_contained = config.getoption('self_contained_html')
            self.logfile = logfile
            self.config = config
            self.row_table = self.row_extra = None

            test_index = hasattr(report, 'rerun') and report.rerun + 1 or 0

            # for extra_index, extra in enumerate(getattr(report, 'extra', [])):
            #     self.append_extra_html(extra, extra_index, test_index)

            self.append_log_html(report, self.additional_html)

            cells = [
                html.td(self.outcome, class_='col-result'),
                html.td(self.test_id, class_='col-name'),
                html.td('{0:.2f}'.format(self.time), class_='col-duration'),
                html.td(self.links_html, class_='col-links')]

            self.config.hook.pytest_html_results_table_row(
                report=report, cells=cells)

            self.config.hook.pytest_html_results_table_html(
                report=report, data=self.additional_html)

            if len(cells) > 0:
                self.row_table = html.tr(cells)
                self.row_extra = html.tr(html.td(self.additional_html,
                                                 class_='extra',
                                                 colspan=len(cells)))

        def __lt__(self, other):
            order = ('Error', 'Failed', 'Rerun', 'XFailed',
                     'XPassed', 'Skipped', 'Passed')
            return order.index(self.outcome) < order.index(other.outcome)

        def create_asset(self, content, extra_index,
                         test_index, file_extension, mode='w'):
            hash_key = ''.join([self.test_id, str(extra_index),
                                str(test_index)]).encode('utf-8')
            hash_generator = hashlib.md5()
            hash_generator.update(hash_key)
            asset_file_name = '{0}.{1}'.format(hash_generator.hexdigest(),
                                               file_extension)
            asset_path = os.path.join(os.path.dirname(self.logfile),
                                      'assets', asset_file_name)
            if not os.path.exists(os.path.dirname(asset_path)):
                os.makedirs(os.path.dirname(asset_path))

            relative_path = '{0}/{1}'.format('assets', asset_file_name)

            kwargs = {'encoding': 'utf-8'} if 'b' not in mode else {}
            with open(asset_path, mode, **kwargs) as f:
                f.write(content)
            return relative_path

        def append_extra_html(self, extra, extra_index, test_index):
            href = None
            if extra.get('format') == extras.FORMAT_IMAGE:
                content = extra.get('content')
                try:
                    is_uri_or_path = (content.startswith(('file', 'http')) or
                                      isfile(content))
                except ValueError:
                    # On Windows, os.path.isfile throws this exception when
                    # passed a b64 encoded image.
                    is_uri_or_path = False
                if is_uri_or_path:
                    if self.self_contained:
                        warnings.warn('Self-contained HTML report '
                                      'includes link to external '
                                      'resource: {}'.format(content))
                    html_div = html.a(html.img(src=content), href=content)
                elif self.self_contained:
                    src = 'data:{0};base64,{1}'.format(
                        extra.get('mime_type'),
                        content)
                    html_div = html.img(src=src)
                else:
                    if PY3:
                        content = b64decode(content.encode('utf-8'))
                    else:
                        content = b64decode(content)
                    href = src = self.create_asset(
                        content, extra_index, test_index,
                        extra.get('extension'), 'wb')
                    html_div = html.a(html.img(src=src), href=href)
                self.additional_html.append(html.div(html_div, class_='image'))

            elif extra.get('format') == extras.FORMAT_HTML:
                self.additional_html.append(html.div(
                                            raw(extra.get('content'))))

            elif extra.get('format') == extras.FORMAT_JSON:
                content = json.dumps(extra.get('content'))
                if self.self_contained:
                    href = data_uri(content,
                                    mime_type=extra.get('mime_type'))
                else:
                    href = self.create_asset(content, extra_index,
                                             test_index,
                                             extra.get('extension'))

            elif extra.get('format') == extras.FORMAT_TEXT:
                content = extra.get('content')
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                if self.self_contained:
                    href = data_uri(content)
                else:
                    href = self.create_asset(content, extra_index,
                                             test_index,
                                             extra.get('extension'))

            elif extra.get('format') == extras.FORMAT_URL:
                href = extra.get('content')

            if href is not None:
                self.links_html.append(html.a(
                    extra.get('name'),
                    class_=extra.get('format'),
                    href=href,
                    target='_blank'))
                self.links_html.append(' ')

        def append_log_html(self, report, additional_html):
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
            additional_html.append(log)

    def results_tree_to_dict(self):
        return {
            "summary": self.results_tree["summary"],
            "results": [n.to_dict() for n in self.results_tree["results"]],
            "suite_info": {
                "generated": self.results_tree["suite_info"]["generated"].isoformat(),
                "run_time": self.results_tree["suite_info"]["run_time"],
                "numtests": self.results_tree["suite_info"]["numtests"],
                "environment": self.results_tree["suite_info"]["environment"],
            },
        }

    def _appendrow(self, outcome, report):
        item = report.user_properties[0][1]

        # determine all the dependancies of each fixture of other fixtures
        dependancies = {}
        for fname, v in item._fixtureinfo.name2fixturedefs.items():
            fix = v[0]
            fix.param_index = item.callspec.indices.get(fix.argname, 0)
            dependancies[fname] = get_fixture_dependancies(
                fname,
                item._fixtureinfo.name2fixturedefs,
            )

        param_fixtures = {}

        for k, v in item._fixtureinfo.name2fixturedefs.items():
            fix = v[0]
            if fix.params:
                if hasattr(fix, "cached_result"):
                    param_id = fix.params[fix.param_index]
                    if fix.ids:
                        # assume iterable
                        try:
                            param_id = fix.ids[fix.param_index]
                        except TypeError:
                            # assume callable
                            param_id = fix.ids(param_id)
                else:
                    param_id = None
            else:
                param_id = None
            autouse = getattr(
                getattr(fix.func, "_pytestfixturefunction", True),
                "autouse",
                True,
            )
            param_fixtures[k] = {
                "id": param_id,
                "scopenum": fix.scopenum,
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

        simple_chain = get_simplified_chain(item.nodeid)

        SESSION_SCOPE = 0
        MODULE_SCOPE = 1
        CLASS_SCOPE = 2
        FUNCTION_SCOPE = 3

        for pf in param_fixtures:
            if not pf["parameterized"]:
                continue
            chain = get_simplified_chain(pf["baseid"])
            if pf["scopenum"] == FUNCTION_SCOPE or pf["autouse"] is False:
                # if a parameterized fixture isn't set for autouse, or the
                # parameterized fixture is of function scope, then no matter
                # where the fixture is defined, it will only branch on the
                # function.
                simple_chain[-1]["params"].append(pf)
            elif pf["scopenum"] == SESSION_SCOPE:
                # parameterized session scope fixtures will branch on whatever
                # scope they are defined in, e.g. one defined in a class will
                # branch on that class and won't impact anything else.
                index = len(chain) - 1
                simple_chain[index]["params"].append(pf)
            elif pf["scopenum"] == MODULE_SCOPE:
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
                simple_chain[index]["params"].append(pf)
            elif pf["scopenum"] == CLASS_SCOPE:
                # parameterized class scope fixtures will branch on classes
                # whatever scope they are defined in, e.g. one defined in a
                # class will branch on that class and won't impact anything
                # else. But if it's defined in the conftest.py, it will branch
                # on each module within the package.
                simple_chain[-2]["params"].append(pf)
            continue

        node_chain = []
        prev_node = None
        test_duration = getattr(report, 'duration', 0.0)
        for i, link in enumerate(simple_chain):
            params = [ParameterizedFixtureStateInfo(p["fixturedef"], getattr(p["fixturedef"], "param_index", None)) for p in link["params"]]
            if link is simple_chain[-1]:
                # is test
                log = get_log_from_report(report)
                n = SimplifiedTestResult(link["name"], nodeid=link["nodeid"], location=item.location, outcome=outcome, duration=test_duration, log=log, params=params)
                prev_node.test_results.append(n)
                node_chain.append(n)
                continue
            if prev_node is None:
                namespace = link["name"]
            else:
                namespace = prev_node.namespace + "." + link["name"]
            node = Node(name=link["name"], namespace=namespace, parent=prev_node, params=params)
            node_chain.append(node)
            if prev_node is None and node not in self.results_tree["results"]:
                self.results_tree["results"].append(node)
            elif prev_node is not None and node not in prev_node.children:
                prev_node.children.append(node)
            prev_node = node
            node.summary[outcome.lower()] = node.summary.get(outcome.lower(), 0) + 1
            node.duration += test_duration
        self.results_tree["summary"][outcome.lower()] = self.results_tree["summary"].get(outcome.lower(), 0) + 1

        self.config.hook.pytest_html_results_node_chain_extra(
            node_chain=node_chain,
            extra=getattr(report, 'extra', []),
        )

        result = self.TestResult(outcome, report, self.logfile, self.config)
        if result.row_table is not None:
            index = bisect.bisect_right(self.results, result)
            self.results.insert(index, result)
            tbody = html.tbody(
                result.row_table,
                class_='{0} results-table-row'.format(result.outcome.lower()))
            if result.row_extra is not None:
                tbody.append(result.row_extra)
            self.test_logs.insert(index, tbody)

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

    def __old_generate_report(self, session):
        suite_stop_time = time.time()
        suite_time_delta = suite_stop_time - self.suite_start_time
        numtests = self.passed + self.failed + self.xpassed + self.xfailed
        generated = datetime.datetime.now()

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

        head = html.head(
            html.meta(charset='utf-8'),
            html.title('Test Report'),
            html_css)

        class Outcome:

            def __init__(self, outcome, total=0, label=None,
                         test_result=None, class_html=None):
                self.outcome = outcome
                self.label = label or outcome
                self.class_html = class_html or outcome
                self.total = total
                self.test_result = test_result or outcome

                self.generate_checkbox()
                self.generate_summary_item()

            def generate_checkbox(self):
                checkbox_kwargs = {'data-test-result':
                                   self.test_result.lower()}
                if self.total == 0:
                    checkbox_kwargs['disabled'] = 'true'

                self.checkbox = html.input(type='checkbox',
                                           checked='true',
                                           onChange='filter_table(this)',
                                           name='filter_checkbox',
                                           class_='filter',
                                           hidden='true',
                                           **checkbox_kwargs)

            def generate_summary_item(self):
                self.summary_item = html.span('{0} {1}'.
                                              format(self.total, self.label),
                                              class_=self.class_html)

        outcomes = [Outcome('passed', self.passed),
                    Outcome('skipped', self.skipped),
                    Outcome('failed', self.failed),
                    Outcome('error', self.errors, label='errors'),
                    Outcome('xfailed', self.xfailed,
                            label='expected failures'),
                    Outcome('xpassed', self.xpassed,
                            label='unexpected passes')]

        if self.rerun is not None:
            outcomes.append(Outcome('rerun', self.rerun))

        summary = [html.p(
            '{0} tests ran in {1:.2f} seconds. '.format(
                numtests, suite_time_delta)),
            html.p('(Un)check the boxes to filter the results.',
                   class_='filter',
                   hidden='true')]

        for i, outcome in enumerate(outcomes, start=1):
            summary.append(outcome.checkbox)
            summary.append(outcome.summary_item)
            if i < len(outcomes):
                summary.append(', ')

        cells = [
            html.th('Result',
                    class_='sortable result initial-sort',
                    col='result'),
            html.th('Test', class_='sortable', col='name'),
            html.th('Duration', class_='sortable numeric', col='duration'),
            html.th('Links')]
        session.config.hook.pytest_html_results_table_header(cells=cells)

        results = [html.h2('Results'), html.table([html.thead(
            html.tr(cells),
            html.tr([
                html.th('No results found. Try to check the filters',
                        colspan=len(cells))],
                    id='not-found-message', hidden='true'),
            id='results-table-head'),
            self.test_logs], id='results-table')]

        main_js = pkg_resources.resource_string(
            __name__, os.path.join('resources', 'main.js'))
        if PY3:
            main_js = main_js.decode('utf-8')

        body = html.body(
            html.script(raw(main_js)),
            html.h1(os.path.basename(session.config.option.htmlpath)),
            html.p('Report generated on {0} at {1} by'.format(
                generated.strftime('%d-%b-%Y'),
                generated.strftime('%H:%M:%S')),
                html.a(' pytest-html', href=__pypi_url__),
                ' v{0}'.format(__version__)),
            onLoad='init()')

        body.extend(self._generate_environment(session.config))

        summary_prefix, summary_postfix = [], []
        session.config.hook.pytest_html_results_summary(
            prefix=summary_prefix, summary=summary, postfix=summary_postfix)
        body.extend([html.h2('Summary')] + summary_prefix
                    + summary + summary_postfix)

        body.extend(results)

        doc = html.html(head, body)

        unicode_doc = u'<!DOCTYPE html>\n{0}'.format(doc.unicode(indent=2))
        if PY3:
            # Fix encoding issues, e.g. with surrogates
            unicode_doc = unicode_doc.encode('utf-8',
                                             errors='xmlcharrefreplace')
            unicode_doc = unicode_doc.decode('utf-8')
        return unicode_doc

    def _generate_report(self, session):
        suite_stop_time = time.time()
        suite_time_delta = suite_stop_time - self.suite_start_time
        numtests = self.passed + self.failed + self.xpassed + self.xfailed
        generated = datetime.datetime.now()
        environment = []
        if hasattr(session.config, '_metadata') and session.config._metadata is not None:
            metadata = session.config._metadata
            environment = metadata

        self.results_tree["suite_info"] = {
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

        results_tree_dict = self.results_tree_to_dict()
        self.config.hook.pytest_html_results_page_css(
            results_tree=results_tree_dict, css=html_css)

        results_tree_json = json.dumps(results_tree_dict, indent=2)
        main_js = pkg_resources.resource_string(
            __name__, os.path.join('resources', 'main_new.js'))
        if PY3:
            main_js = main_js.decode('utf-8')
        my_js = main_js.replace("{results_tree}", results_tree_json)
        my_js = my_js.replace("{project_name}", results_tree_dict["results"][0]["name"])
        html_script = html.script(raw(my_js))
        self.config.hook.pytest_html_results_page_script(
            results_tree=results_tree_dict, script=html_script)

        html_head = html.head(
            html.meta(charset='utf-8'),
            html.title('Test Report'),
            html_css,
            html_script,
        )

        html_body = self._generate_body(results_tree_dict)
        self.config.hook.pytest_html_results_page_body(
            results_tree=results_tree_dict, body=html_body)

        doc = html.html()

        doc.extend(html_head)
        doc.extend(
            html_body,
        )
        self.config.hook.pytest_html_results_page_html(
            results_tree=results_tree_dict, doc=doc)

        unicode_doc = u'<!DOCTYPE html>\n{0}'.format(doc.unicode(indent=2))
        if PY3:
            # Fix encoding issues, e.g. with surrogates
            unicode_doc = unicode_doc.encode('utf-8',
                                             errors='xmlcharrefreplace')
            unicode_doc = unicode_doc.decode('utf-8')
        return unicode_doc

    def _generate_environment(self, config):
        if not hasattr(config, '_metadata') or config._metadata is None:
            return []

        metadata = config._metadata
        environment = [html.h2('Environment')]
        rows = []

        keys = [k for k in metadata.keys() if metadata[k]]
        if not isinstance(metadata, OrderedDict):
            keys.sort()

        for key in keys:
            value = metadata[key]
            if isinstance(value, basestring) and value.startswith('http'):
                value = html.a(value, href=value, target='_blank')
            elif isinstance(value, (list, tuple, set)):
                value = ', '.join((str(i) for i in value))
            rows.append(html.tr(html.td(key), html.td(value)))

        environment.append(html.table(rows, id='environment'))
        return environment

    def _generate_body(self, results_tree):
        body = html.body(html.body(onload="init()"))

        generated_time = datetime.datetime.strptime(results_tree["suite_info"]["generated"].split(".")[0], "%Y-%I-%dT%X")
        summary_div = [html.div(
            html.div(results_tree["results"][0]["name"], class_="project-title"),
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
            _generate_environment(results_tree["suite_info"]["environment"]),
            _generate_summary_count(
                results_tree["suite_info"]["numtests"],
                results_tree["summary"],
                results_tree["suite_info"]["run_time"],
            ),
            class_="project-test-results-summary",
        )]
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


def get_simplified_chain(nodeid):
    try:
        param_start_index = nodeid.index("[")
        package_chain = nodeid[:param_start_index]
    except ValueError:
        package_chain = nodeid
    package_chain = package_chain.split("/")
    local_chain = package_chain.pop()
    local_chain = local_chain.replace("::()", "")
    local_chain = local_chain.split("::")
    simple_chain = [{"name": n, "params": []} for n in package_chain + local_chain]
    simple_chain[-1]["nodeid"] = nodeid
    return simple_chain


def get_fixture_dependancies(name, fixturedefs):
    if name not in fixturedefs.keys():
        return set()
    fix = fixturedefs[name][0]
    dependancies = set()
    for arg in fix.argnames:
        dependancies.add(arg)
        dependancies.update(get_fixture_dependancies(arg, fixturedefs))
    return dependancies


def pytest_html_results_page_html(results_tree, doc):
    # results_tree_json = json.dumps(results_tree, indent=2)
    # main_js = pkg_resources.resource_string(
    #     __name__, os.path.join('resources', 'main_new.js'))
    # if PY3:
    #     main_js = main_js.decode('utf-8')
    # my_js = main_js.replace("{results_tree}", results_tree_json)
    # my_js = my_js.replace("{project_name}", results_tree["results"][0]["name"])
    # doc.extend(html.head(
    #     html.script(raw(my_js)),
    # ))
    # # body = html.body(html.body(html.div("heading", class_="insideheader"), class_="header"))
    # body = html.body(html.body(onload="init()"))
    #
    # generated_time = datetime.datetime.strptime(results_tree["suite_info"]["generated"].split(".")[0], "%Y-%I-%dT%X")
    # summary_div = [html.div(
    #     html.div(results_tree["results"][0]["name"], class_="project-title"),
    #     html.div(
    #         html.p(
    #             'Report generated on {0} at {1} by'.format(
    #                 generated_time.strftime('%d-%b-%Y'),
    #                 generated_time.strftime('%H:%M:%S')
    #             ),
    #             html.a(' pytest-html', href=__pypi_url__),
    #             ' v{0}'.format(__version__),
    #             class_="generated-time"
    #         ),
    #         class_="generated-info",
    #     ),
    #     _generate_environment(results_tree["suite_info"]["environment"]),
    #     _generate_summary_count(
    #         results_tree["suite_info"]["numtests"],
    #         results_tree["summary"],
    #         results_tree["suite_info"]["run_time"],
    #     ),
    #     class_="project-test-results-summary",
    # )]
    # results_div = [html.div(
    #     html.h2("Results"),
    #     html.div(
    #         html.button("expand all", id="expand-all-button"),
    #         html.button("collapse all", id="collapse-all-button"),
    #         class_="show-hide-buttons",
    #     ),
    #     html.div(class_="results-info"),
    #     class_="results-details",
    # )]
    # body.extend([
    #     summary_div,
    #     results_div,
    # ])
    # doc.extend(
    #     body,
    # )
    pass


def _generate_environment(environment_details):
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


def _generate_summary_count(numtests, summary, run_time):
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
                html.div(
                    html.div("Passes", class_="button-text"),
                    html.div(summary["passed"], class_="summary-result-count passed"),
                    class_="count-toggle-button passed",
                    title="Passes",
                ),
                html.div(
                    html.div("Skips", class_="button-text"),
                    html.div(summary["skipped"], class_="summary-result-count skipped"),
                    class_="count-toggle-button skipped",
                    title="Skips",
                ),
                html.div(
                    html.div("Failures", class_="button-text"),
                    html.div(summary["failed"], class_="summary-result-count failed"),
                    class_="count-toggle-button failed",
                    title="Failures",
                ),
                html.div(
                    html.div("Errors", class_="button-text"),
                    html.div(summary["error"], class_="summary-result-count error"),
                    class_="count-toggle-button error",
                    title="Errors",
                ),
                html.div(
                    html.div("Expected failures", class_="button-text"),
                    html.div(summary["xfailed"], class_="summary-result-count xfailed"),
                    class_="count-toggle-button xfailed",
                    title="Expected failures",
                ),
                html.div(
                    html.div("Unexpected passes", class_="button-text"),
                    html.div(summary["xpassed"], class_="summary-result-count xpassed"),
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


def pytest_runtest_makereport(item, call):
    item.user_properties.append(("item", item))


def pytest_fixture_setup(fixturedef, request):
    fixturedef.param_index = request.param_index


def pytest_html_results_node_chain_extra(node_chain, extra):
    node_chain[-1].extra = extra
