"""Integration tests for FileWriter., common for all FileDF connections.

Test only that options generated by both FileWriter and FileWriter.Options are passed to Spark,
and behavior is the same as described in documentation.

Do not test all possible options and combinations, we are not testing Spark here.
"""

import pytest
from pytest_lazyfixture import lazy_fixture

from onetl.file import FileReader, FileWriter
from onetl.file.format import CSV

try:
    from tests.util.assert_df import assert_equal_df
except ImportError:
    # pandas and spark can be missing if someone runs tests for file connections only
    pass


@pytest.mark.parametrize(
    "if_exists",
    [
        "error",
        "skip_entire_directory",
        "append",
        "replace_overlapping_partitions",
        "replace_entire_directory",
    ],
)
def test_file_writer_run_target_does_not_exist(
    file_df_connection_with_path,
    file_df_dataframe,
    if_exists,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    csv_root = target_path / "csv"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(if_exists=if_exists),
    )
    writer.run(df)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )
    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == df.schema
    assert_equal_df(df, read_df)


def test_file_writer_run_if_exists_error(
    file_df_connection_with_path_and_files,
    file_df_dataframe,
):
    file_df_connection, target_path, _ = file_df_connection_with_path_and_files
    df = file_df_dataframe

    csv_root = target_path / "csv/with_header"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
    )

    with pytest.raises(Exception, match="already exists"):
        writer.run(df)


def test_file_writer_run_if_exists_skip_entire_directory(
    file_df_connection_with_path,
    file_df_dataframe,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    df1 = df.filter(df.id <= 5)
    df2 = df.filter(df.id > 5)

    csv_root = target_path / "csv"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(if_exists="skip_entire_directory"),
    )

    writer.run(df1)
    writer.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == df.schema
    assert_equal_df(read_df, df1, order_by="id")


def test_file_writer_run_if_exists_replace_overlapping_partitions_target_not_partitioned_df_is(
    file_df_connection_with_path_and_files,
    file_df_dataframe,
    file_df_schema_str_value_last,
):
    file_df_connection, target_path, _ = file_df_connection_with_path_and_files
    df = file_df_dataframe
    df1 = df.filter(df.id <= 5)

    csv_root = target_path / "csv/without_header"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="replace_overlapping_partitions"),
    )

    writer.run(df1)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == file_df_schema_str_value_last
    assert_equal_df(read_df, df1, order_by="id")


def test_file_writer_run_if_exists_replace_overlapping_partitions_target_partitioned_df_is_not(
    file_df_connection_with_path_and_files,
    file_df_dataframe,
):
    file_df_connection, target_path, _ = file_df_connection_with_path_and_files
    df = file_df_dataframe
    df1 = df.filter(df.id <= 5)

    csv_root = target_path / "csv/partitioned"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(if_exists="replace_overlapping_partitions"),
    )

    writer.run(df1)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == df.schema
    assert_equal_df(read_df, df1, order_by="id")


def test_file_writer_run_if_exists_replace_overlapping_partitions_to_different_partitioning_schema(
    file_df_connection_with_path,
    file_df_dataframe,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe
    df1 = df.filter(df.id <= 5)

    csv_root = target_path / "csv"
    writer1 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="id"),
    )

    writer1.run(df)

    writer2 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="replace_overlapping_partitions"),
    )

    # this can create conflicting partitioning schemas, which then cannot be read by Spark
    writer2.run(df1)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    with pytest.raises(Exception, match="Conflicting partition column names detected"):
        reader.run()


def test_file_writer_run_if_exists_replace_overlapping_partitions_to_overlapping_partitions(
    file_df_connection_with_path,
    file_df_dataframe,
    file_df_schema_str_value_last,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    # df1 contains all rows with str_value == "val1" and one row with str_value == "val2"
    # df2 contains all rows with str_value == "val3" and one row with str_value == "val2", different from df2
    df1 = df.filter(df.id <= 3)
    df2 = df.filter(df.id > 3)

    csv_root = target_path / "csv"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="replace_overlapping_partitions"),
    )

    writer.run(df1)
    writer.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()
    assert read_df.count()
    assert read_df.schema == file_df_schema_str_value_last

    # rows from df1 with str_value == "val2" are overwritten by rows from df2, but others left intact
    expected_df = df1.filter(df1.str_value == "val1").union(df2)
    assert_equal_df(read_df, expected_df, order_by="id")


@pytest.mark.parametrize(
    "original_options, new_options, real_df_schema",
    [
        pytest.param(
            {},
            {"partitionBy": "str_value"},
            lazy_fixture("file_df_schema_str_value_last"),
            id="directory_not_partitioned_dataframe_is",
        ),
        pytest.param(
            {"partitionBy": "id"},
            {},
            lazy_fixture("file_df_schema"),
            id="directory_partitioned_dataframe_is_not",
        ),
        pytest.param(
            {"partitionBy": "id"},
            {"partitionBy": "str_value"},
            lazy_fixture("file_df_schema_str_value_last"),
            id="different_partitioning_schema",
        ),
        pytest.param(
            {"partitionBy": "str_value"},
            {"partitionBy": "str_value"},
            lazy_fixture("file_df_schema_str_value_last"),
            id="same_partitioning_schema",
        ),
    ],
)
def test_file_writer_run_if_exists_replace_entire_directory(
    file_df_connection_with_path,
    file_df_dataframe,
    original_options,
    new_options,
    real_df_schema,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    df1 = df.filter(df.id <= 5)
    df2 = df.filter(df.id > 5)

    csv_root = target_path / "csv"
    csv = CSV()

    writer1 = FileWriter(
        connection=file_df_connection,
        format=csv,
        target_path=csv_root,
        options=original_options,
    )
    # create and fill directory with some data
    writer1.run(df1)

    writer2 = FileWriter(
        connection=file_df_connection,
        format=csv,
        target_path=csv_root,
        options=FileWriter.Options(if_exists="replace_entire_directory", **new_options),
    )
    # recreate directory
    writer2.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=csv,
        source_path=csv_root,
        df_schema=df.schema,
    )
    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == real_df_schema
    # directory content is replaced with new data
    assert_equal_df(read_df, df2, order_by="id")


def test_file_writer_run_if_exists_append_target_not_partitioned_df_is(
    file_df_connection_with_path,
    file_df_dataframe,
    file_df_schema_str_value_last,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe
    df1 = df.filter(df.id <= 5)
    df2 = df.filter(df.id > 5)

    csv_root = target_path / "csv"
    writer1 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(if_exists="append"),
    )
    writer1.run(df1)

    writer2 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="append"),
    )
    writer2.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == file_df_schema_str_value_last
    # data from df1 is still there, but Spark ignores it because it is not in any partition subpath
    assert_equal_df(read_df, df2, order_by="id")


def test_file_writer_run_if_exists_append_target_partitioned_df_is_not(
    file_df_connection_with_path,
    file_df_dataframe,
    file_df_schema_str_value_last,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    df1 = df.filter(df.id <= 5)
    df2 = df.filter(df.id > 5)

    csv_root = target_path / "csv/partitioned"
    writer1 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="append"),
    )

    writer1.run(df1)

    writer2 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(if_exists="append"),
    )

    writer2.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == file_df_schema_str_value_last
    # data from df2 is there, but Spark ignores it because it is not in any partition subpath
    assert_equal_df(read_df, df1, order_by="id")


def test_file_writer_run_if_exists_append_to_different_partitioning_schema(
    file_df_connection_with_path,
    file_df_dataframe,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    df1 = df.filter(df.id <= 5)
    df2 = df.filter(df.id > 5)

    csv_root = target_path / "csv"
    writer1 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="id"),
    )

    writer1.run(df1)

    writer2 = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="append"),
    )

    # this can create conflicting partitioning schemas, which then cannot be read by Spark
    writer2.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    with pytest.raises(Exception, match="Conflicting partition column names detected"):
        reader.run()


def test_file_writer_run_if_exists_append_to_overlapping_partitions(
    file_df_connection_with_path,
    file_df_dataframe,
    file_df_schema_str_value_last,
):
    file_df_connection, target_path = file_df_connection_with_path
    df = file_df_dataframe

    # df1 contains all rows with str_value == "val1" and one row with str_value == "val2"
    # df2 contains all rows with str_value == "val3" and one row with str_value == "val2", different from df2
    df1 = df.filter(df.id <= 3)
    df2 = df.filter(df.id > 3)

    csv_root = target_path / "csv"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
        options=FileWriter.Options(partition_by="str_value", if_exists="append"),
    )

    writer.run(df1)
    writer.run(df2)

    reader = FileReader(
        connection=file_df_connection,
        format=CSV(),
        source_path=csv_root,
        df_schema=df.schema,
    )

    read_df = reader.run()

    assert read_df.count()
    assert read_df.schema == file_df_schema_str_value_last
    # existing partitions are appended, not replaced
    assert_equal_df(read_df, df, order_by="id")


def test_file_writer_with_streaming_df(
    spark,
    file_df_connection_with_path,
):
    file_df_connection, target_path = file_df_connection_with_path
    csv_root = target_path / "csv"
    writer = FileWriter(
        connection=file_df_connection,
        format=CSV(),
        target_path=csv_root,
    )

    streaming_df = spark.readStream.format("rate").load()
    assert streaming_df.isStreaming
    with pytest.raises(ValueError, match="DataFrame is streaming. FileWriter supports only batch DataFrames."):
        writer.run(streaming_df)
