# plugin/plugin_base.py
# Copyright (C) 2005-2014 the SQLAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

"""Testing extensions.

this module is designed to work as a testing-framework-agnostic library,
so that we can continue to support nose and also begin adding new functionality
via py.test.

"""

from __future__ import absolute_import
try:
    # unitttest has a SkipTest also but pytest doesn't
    # honor it unless nose is imported too...
    from nose import SkipTest
except ImportError:
    from _pytest.runner import Skipped as SkipTest

import sys
import re

py3k = sys.version_info >= (3, 0)

if py3k:
    import configparser
else:
    import ConfigParser as configparser


# late imports
fixtures = None
engines = None
exclusions = None
warnings = None
profiling = None
assertions = None
requirements = None
config = None
testing = None
util = None
file_config = None


logging = None
db_opts = {}
options = None

def setup_options(make_option):
    make_option("--log-info", action="callback", type="string", callback=_log,
        help="turn on info logging for <LOG> (multiple OK)")
    make_option("--log-debug", action="callback", type="string", callback=_log,
        help="turn on debug logging for <LOG> (multiple OK)")
    make_option("--db", action="append", type="string", dest="db",
                help="Use prefab database uri. Multiple OK, "
                        "first one is run by default.")
    make_option('--dbs', action='callback', callback=_list_dbs,
        help="List available prefab dbs")
    make_option("--dburi", action="append", type="string", dest="dburi",
        help="Database uri.  Multiple OK, first one is run by default.")
    make_option("--dropfirst", action="store_true", dest="dropfirst",
        help="Drop all tables in the target database first")
    make_option("--backend-only", action="store_true", dest="backend_only",
        help="Run only tests marked with __backend__")
    make_option("--mockpool", action="store_true", dest="mockpool",
        help="Use mock pool (asserts only one connection used)")
    make_option("--low-connections", action="store_true", dest="low_connections",
        help="Use a low number of distinct connections - i.e. for Oracle TNS"
    )
    make_option("--reversetop", action="store_true", dest="reversetop", default=False,
        help="Use a random-ordering set implementation in the ORM (helps "
              "reveal dependency issues)")
    make_option("--requirements", action="callback", type="string",
        callback=_requirements_opt,
        help="requirements class for testing, overrides setup.cfg")
    make_option("--with-cdecimal", action="store_true", dest="cdecimal", default=False,
        help="Monkeypatch the cdecimal library into Python 'decimal' for all tests")
    make_option("--serverside", action="callback", callback=_server_side_cursors,
        help="Turn on server side cursors for PG")
    make_option("--mysql-engine", action="store", dest="mysql_engine", default=None,
        help="Use the specified MySQL storage engine for all tables, default is "
             "a db-default/InnoDB combo.")
    make_option("--tableopts", action="append", dest="tableopts", default=[],
        help="Add a dialect-specific table option, key=value")
    make_option("--write-profiles", action="store_true", dest="write_profiles", default=False,
            help="Write/update profiling data.")

def read_config():
    global file_config
    file_config = configparser.ConfigParser()
    file_config.read(['setup.cfg', 'test.cfg'])

def pre_begin(opt):
    """things to set up early, before coverage might be setup."""
    global options
    options = opt
    for fn in pre_configure:
        fn(options, file_config)

def set_coverage_flag(value):
    options.has_coverage = value

def post_begin():
    """things to set up later, once we know coverage is running."""
    # Lazy setup of other options (post coverage)
    for fn in post_configure:
        fn(options, file_config)

    # late imports, has to happen after config as well
    # as nose plugins like coverage
    global util, fixtures, engines, exclusions, \
                    assertions, warnings, profiling,\
                    config, testing
    from sqlalchemy import testing
    from sqlalchemy.testing import fixtures, engines, exclusions, \
                    assertions, warnings, profiling, config
    from sqlalchemy import util


def _log(opt_str, value, parser):
    global logging
    if not logging:
        import logging
        logging.basicConfig()

    if opt_str.endswith('-info'):
        logging.getLogger(value).setLevel(logging.INFO)
    elif opt_str.endswith('-debug'):
        logging.getLogger(value).setLevel(logging.DEBUG)


def _list_dbs(*args):
    print("Available --db options (use --dburi to override)")
    for macro in sorted(file_config.options('db')):
        print("%20s\t%s" % (macro, file_config.get('db', macro)))
    sys.exit(0)


def _server_side_cursors(opt_str, value, parser):
    db_opts['server_side_cursors'] = True

def _requirements_opt(opt_str, value, parser):
    _setup_requirements(value)


pre_configure = []
post_configure = []


def pre(fn):
    pre_configure.append(fn)
    return fn


def post(fn):
    post_configure.append(fn)
    return fn


@pre
def _setup_options(opt, file_config):
    global options
    options = opt


@pre
def _monkeypatch_cdecimal(options, file_config):
    if options.cdecimal:
        import cdecimal
        sys.modules['decimal'] = cdecimal


@post
def _engine_uri(options, file_config):
    from sqlalchemy.testing import engines, config
    from sqlalchemy import testing

    if options.dburi:
        db_urls = list(options.dburi)
    else:
        db_urls = []

    if options.db:
        for db_token in options.db:
            for db in re.split(r'[,\s]+', db_token):
                if db not in file_config.options('db'):
                    raise RuntimeError(
                        "Unknown URI specifier '%s'.  Specify --dbs for known uris."
                                % db)
                else:
                    db_urls.append(file_config.get('db', db))

    if not db_urls:
        db_urls.append(file_config.get('db', 'default'))

    for db_url in db_urls:
        eng = engines.testing_engine(db_url, db_opts)
        eng.connect().close()
        config.Config.register(eng, db_opts, options, file_config, testing)

    config.db_opts = db_opts


@post
def _engine_pool(options, file_config):
    if options.mockpool:
        from sqlalchemy import pool
        db_opts['poolclass'] = pool.AssertionPool

@post
def _requirements(options, file_config):

    requirement_cls = file_config.get('sqla_testing', "requirement_cls")
    _setup_requirements(requirement_cls)

def _setup_requirements(argument):
    from sqlalchemy.testing import config
    from sqlalchemy import testing

    if config.requirements is not None:
        return

    modname, clsname = argument.split(":")

    # importlib.import_module() only introduced in 2.7, a little
    # late
    mod = __import__(modname)
    for component in modname.split(".")[1:]:
        mod = getattr(mod, component)
    req_cls = getattr(mod, clsname)

    config.requirements = testing.requires = req_cls()

@post
def _prep_testing_database(options, file_config):
    from sqlalchemy.testing import config
    from sqlalchemy import schema, inspect

    if options.dropfirst:
        for cfg in config.Config.all_configs():
            e = cfg.db
            inspector = inspect(e)
            try:
                view_names = inspector.get_view_names()
            except NotImplementedError:
                pass
            else:
                for vname in view_names:
                    e.execute(schema._DropView(schema.Table(vname, schema.MetaData())))

            if config.requirements.schemas.enabled_for_config(cfg):
                try:
                    view_names = inspector.get_view_names(schema="test_schema")
                except NotImplementedError:
                    pass
                else:
                    for vname in view_names:
                        e.execute(schema._DropView(
                                    schema.Table(vname,
                                                schema.MetaData(), schema="test_schema")))

            for tname in reversed(inspector.get_table_names(order_by="foreign_key")):
                e.execute(schema.DropTable(schema.Table(tname, schema.MetaData())))

            if config.requirements.schemas.enabled_for_config(cfg):
                for tname in reversed(inspector.get_table_names(
                                        order_by="foreign_key", schema="test_schema")):
                    e.execute(schema.DropTable(
                        schema.Table(tname, schema.MetaData(), schema="test_schema")))


@post
def _set_table_options(options, file_config):
    from sqlalchemy.testing import schema

    table_options = schema.table_options
    for spec in options.tableopts:
        key, value = spec.split('=')
        table_options[key] = value

    if options.mysql_engine:
        table_options['mysql_engine'] = options.mysql_engine


@post
def _reverse_topological(options, file_config):
    if options.reversetop:
        from sqlalchemy.orm.util import randomize_unitofwork
        randomize_unitofwork()


@post
def _post_setup_options(opt, file_config):
    from sqlalchemy.testing import config
    config.options = options
    config.file_config = file_config


@post
def _setup_profiling(options, file_config):
    from sqlalchemy.testing import profiling
    profiling._profile_stats = profiling.ProfileStatsFile(
                file_config.get('sqla_testing', 'profile_file'))


def want_class(cls):
    if not issubclass(cls, fixtures.TestBase):
        return False
    elif cls.__name__.startswith('_'):
        return False
    elif config.options.backend_only and not getattr(cls, '__backend__', False):
        return False
    else:
        return True

def generate_sub_tests(cls, module):
    if getattr(cls, '__backend__', False):
        for cfg in _possible_configs_for_cls(cls):
            name = "%s_%s_%s" % (cls.__name__, cfg.db.name, cfg.db.driver)
            subcls = type(
                        name,
                        (cls, ),
                        {
                            "__only_on__": ("%s+%s" % (cfg.db.name, cfg.db.driver)),
                            "__backend__": False}
                        )
            setattr(module, name, subcls)
            yield subcls
    else:
        yield cls


def start_test_class(cls):
    _do_skips(cls)
    _setup_engine(cls)

def stop_test_class(cls):
    engines.testing_reaper._stop_test_ctx()
    if not options.low_connections:
        assertions.global_cleanup_assertions()
    _restore_engine()

def _restore_engine():
    config._current.reset(testing)

def _setup_engine(cls):
    if getattr(cls, '__engine_options__', None):
        eng = engines.testing_engine(options=cls.__engine_options__)
        config._current.push_engine(eng, testing)

def before_test(test, test_module_name, test_class, test_name):

    # like a nose id, e.g.:
    # "test.aaa_profiling.test_compiler.CompileTest.test_update_whereclause"
    name = test_class.__name__

    suffix = "_%s_%s" % (config.db.name, config.db.driver)
    if name.endswith(suffix):
        name = name[0:-(len(suffix))]

    id_ = "%s.%s.%s" % (test_module_name, name, test_name)

    warnings.resetwarnings()
    profiling._current_test = id_

def after_test(test):
    engines.testing_reaper._after_test_ctx()
    warnings.resetwarnings()

def _possible_configs_for_cls(cls):
    all_configs = set(config.Config.all_configs())
    if cls.__unsupported_on__:
        spec = exclusions.db_spec(*cls.__unsupported_on__)
        for config_obj in list(all_configs):
            if spec(config_obj):
                all_configs.remove(config_obj)

    if getattr(cls, '__only_on__', None):
        spec = exclusions.db_spec(*util.to_list(cls.__only_on__))
        for config_obj in list(all_configs):
            if not spec(config_obj):
                all_configs.remove(config_obj)


    return all_configs

def _do_skips(cls):
    all_configs = _possible_configs_for_cls(cls)
    reasons = []

    if hasattr(cls, '__requires__'):
        requirements = config.requirements
        for config_obj in list(all_configs):
            for requirement in cls.__requires__:
                check = getattr(requirements, requirement)

                if check.predicate(config_obj):
                    all_configs.remove(config_obj)
                    if check.reason:
                        reasons.append(check.reason)
                    break

    if hasattr(cls, '__prefer_requires__'):
        non_preferred = set()
        requirements = config.requirements
        for config_obj in list(all_configs):
            for requirement in cls.__prefer_requires__:
                check = getattr(requirements, requirement)

                if check.predicate(config_obj):
                    non_preferred.add(config_obj)
        if all_configs.difference(non_preferred):
            all_configs.difference_update(non_preferred)

    if getattr(cls, '__skip_if__', False):
        for c in getattr(cls, '__skip_if__'):
            if c():
                raise SkipTest("'%s' skipped by %s" % (
                    cls.__name__, c.__name__)
                )

    for db_spec, op, spec in getattr(cls, '__excluded_on__', ()):
        for config_obj in list(all_configs):
            if exclusions.skip_if(
                    exclusions.SpecPredicate(db_spec, op, spec)
                    ).predicate(config_obj):
                all_configs.remove(config_obj)


    if not all_configs:
        raise SkipTest(
            "'%s' unsupported on DB implementation %s%s" % (
                cls.__name__,
                ", ".join("'%s' = %s" % (
                                config_obj.db.name,
                                config_obj.db.dialect.server_version_info)
                    for config_obj in config.Config.all_configs()
                ),
                ", ".join(reasons)
            )
        )
    elif hasattr(cls, '__prefer_backends__'):
        non_preferred = set()
        spec = exclusions.db_spec(*util.to_list(cls.__prefer_backends__))
        for config_obj in all_configs:
            if not spec(config_obj):
                non_preferred.add(config_obj)
        if all_configs.difference(non_preferred):
            all_configs.difference_update(non_preferred)

    if config._current not in all_configs:
        _setup_config(all_configs.pop(), cls)

def _setup_config(config_obj, ctx):
    config._current.push(config_obj, testing)

