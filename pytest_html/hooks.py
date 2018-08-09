# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


def pytest_html_results_summary(summary):
    """ Called before adding the summary section to the report """


def pytest_html_add_node_chain_extra(item, outcome, extra, node_chain):
    """ Called after each test is run, but before generating any HTML. """
