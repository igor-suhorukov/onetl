import logging
import re
from unittest.mock import Mock

import pytest
from pyspark.sql import SparkSession

from onetl.connection import Greenplum, Hive, Oracle, Postgres

spark = Mock(spec=SparkSession)


def test_secure_str_and_repr():
    conn = Oracle(host="some_host", user="user", password="passwd", sid="sid", spark=spark)

    assert "password='passwd'" not in str(conn)
    assert "password='passwd'" not in repr(conn)


@pytest.mark.parametrize(
    "options_class",
    [
        Postgres.ReadOptions,
        Postgres.WriteOptions,
        Postgres.JDBCOptions,
        Postgres.Options,
        Greenplum.ReadOptions,
        Greenplum.WriteOptions,
    ],
)
@pytest.mark.parametrize(
    "arg, value",
    [
        ("url", "jdbc:ora:thin/abc"),
        ("driver", "com.oracle.jdbc.Driver"),
        ("user", "me"),
        ("password", "abc"),
    ],
)
def test_db_options_connection_parameters_cannot_be_passed(options_class, arg, value):
    with pytest.raises(ValueError, match=f"Option '{arg}' is not allowed to use in a {options_class.__name__}"):
        options_class(**{arg: value})


@pytest.mark.parametrize(
    "options_class, options_class_name, known_options",
    [
        (Hive.WriteOptions, "WriteOptions", {"mode": "overwrite_partitions"}),
        (Hive.Options, "Options", {"mode": "overwrite_partitions"}),
        (Postgres.ReadOptions, "ReadOptions", {"fetchsize": 10, "keytab": "a/b/c"}),
        (Postgres.WriteOptions, "WriteOptions", {"mode": "overwrite", "keytab": "a/b/c"}),
        (Postgres.Options, "Options", {"mode": "overwrite", "keytab": "a/b/c"}),
        (Greenplum.ReadOptions, "ReadOptions", {"partitions": 10}),
        (Greenplum.WriteOptions, "WriteOptions", {"mode": "overwrite"}),
    ],
)
def test_db_options_warn_for_unknown(options_class, options_class_name, known_options, caplog):
    with caplog.at_level(logging.WARNING):
        options_class(some_unknown_option="value", **known_options)

        assert (
            f"Option 'some_unknown_option' is not known by {options_class_name}, are you sure it is valid?"
        ) in caplog.text

        options_class(option1="value1", option2=None, **known_options)

        assert (
            f"Options 'option1', 'option2' are not known by {options_class_name}, are you sure they are valid?"
        ) in caplog.text

        for known_option in known_options:
            assert known_option not in caplog.text


@pytest.mark.parametrize(
    "options_class,options",
    [
        (
            Oracle.ReadOptions,
            Oracle.WriteOptions(mode="append"),
        ),
        (
            Oracle.WriteOptions,
            Oracle.ReadOptions(fetchsize=1000),
        ),
    ],
    ids=[
        "Write options object passed to ReadOptions",
        "Read options object passed to WriteOptions",
    ],
)
def test_db_options_parse_mismatch_class(options_class, options):
    with pytest.raises(TypeError):
        options_class.parse(options)


@pytest.mark.parametrize(
    "connection,options",
    [
        (
            Oracle,
            Hive.WriteOptions(format="orc"),
        ),
        (
            Hive,
            Oracle.WriteOptions(truncate=True),
        ),
    ],
    ids=["JDBC connection with Hive options.", "Hive connection with JDBC options."],
)
def test_db_options_parse_mismatch_connection_and_options_types(connection, options):
    with pytest.raises(TypeError):
        connection.WriteOptions.parse(options)


@pytest.mark.parametrize(
    "options_class",
    [
        Postgres.ReadOptions,
        Postgres.WriteOptions,
        Postgres.JDBCOptions,
        Greenplum.ReadOptions,
        Greenplum.WriteOptions,
        Hive.WriteOptions,
        Postgres.Options,
        Hive.Options,
    ],
)
@pytest.mark.parametrize(
    "options",
    [
        {"some", "option"},
        "Some_options",
        123,
        ["Option_1", "Option_2"],
        ("Option_1", "Option_2"),
    ],
    ids=[
        "set",
        "str",
        "int",
        "list",
        "tuple",
    ],
)
def test_db_options_cannot_be_parsed(options_class, options):
    with pytest.raises(
        TypeError,
        match=re.escape(f"{type(options).__name__} is not a {options_class.__name__} instance"),
    ):
        options_class.parse(options)
