from __future__ import annotations

from datetime import date, datetime
from typing import ClassVar

from onetl.connection.db_connection.jdbc_connection import JDBCConnection


class MSSQL(JDBCConnection):
    """Class for MSSQL JDBC connection.

    Based on Maven package ``com.microsoft.sqlserver:mssql-jdbc:10.2.1.jre8``
    (`official MSSQL JDBC driver
    <https://docs.microsoft.com/en-us/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server>`_)

    .. note::

        Supported SQL Server versions: >= 2012

    Parameters
    ----------
    host : str
        Host of MSSQL database. For example: ``test.mssql.domain.com`` or ``192.168.1.14``

    port : int, default: ``1433``
        Port of MSSQL database

    user : str
        User, which have proper access to the database. For example: ``some_user``

    password : str
        Password for database connection

    database : str
        Database in RDBMS, NOT schema.

        See `this page <https://www.educba.com/postgresql-database-vs-schema/>`_ for more details

    spark : :obj:`pyspark.sql.SparkSession`
        Spark session.

        You can use ``mtspark`` for spark session initialization

    extra : dict, default: ``None``
        Specifies one or more extra parameters by which clients can connect to the instance.

        For example: ``{"connectRetryCount": 3, "connectRetryInterval": 10}``

        See `MSSQL JDBC driver properties documentation
        <https://docs.microsoft.com/en-us/sql/connect/jdbc/setting-the-connection-properties?view=sql-server-ver16#properties>`_
        for more details

    Examples
    --------

    MSSQL connection with plain auth:

    .. code::

        from onetl.connection import MSSQL
        from mtspark import get_spark

        extra = {
            "trustServerCertificate": "true",  # add this to avoid SSL certificate issues
        }

        spark = get_spark({
            "appName": "spark-app-name",
            "spark.jars.packages": [
                "default:skip",
                MSSQL.package,
            ],
        })

        mssql = MSSQL(
            host="database.host.or.ip",
            user="user",
            password="*****",
            extra=extra,
            spark=spark,
        )

    MSSQL connection with domain auth:

    .. code::

        from onetl.connection import MSSQL
        from mtspark import get_spark

        extra = {
            "Domain": "some.domain.com",  # add here your domain
            "IntegratedSecurity": "true",
            "authenticationScheme": "NTLM",
            "trustServerCertificate": "true",  # add this to avoid SSL certificate issues
        }

        spark = get_spark({
            "appName": "spark-app-name",
            "spark.jars.packages": [
                "default:skip",
                MSSQL.package,
            ],
        })

        mssql = MSSQL(
            host="database.host.or.ip",
            user="user",
            password="*****",
            extra=extra,
            spark=spark,
        )

    MSSQL read-only connection:

    .. code::

        from onetl.connection import MSSQL
        from mtspark import get_spark

        extra = {
            "ApplicationIntent": "ReadOnly",  # driver will open read-only connection, to avoid writing to the database
            "trustServerCertificate": "true",  # add this to avoid SSL certificate issues
        }

        spark = get_spark({
            "appName": "spark-app-name",
            "spark.jars.packages": [
                "default:skip",
                MSSQL.package,
            ],
        })

        mssql = MSSQL(
            host="database.host.or.ip",
            user="user",
            password="*****",
            extra=extra,
            spark=spark,
        )

    """

    class Extra(JDBCConnection.Extra):
        class Config:
            prohibited_options = frozenset(("databaseName",))

    database: str
    port: int = 1433
    extra: Extra = Extra()

    driver: ClassVar[str] = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
    package: ClassVar[str] = "com.microsoft.sqlserver:mssql-jdbc:10.2.1.jre8"
    _check_query: ClassVar[str] = "SELECT 1 AS field"

    class ReadOptions(JDBCConnection.ReadOptions):
        # https://docs.microsoft.com/ru-ru/sql/t-sql/functions/hashbytes-transact-sql?view=sql-server-ver16
        @classmethod
        def _get_partition_column_hash(cls, partition_column: str, num_partitions: int) -> str:
            return f"CONVERT(BIGINT, HASHBYTES ( 'SHA' , {partition_column} )) % {num_partitions}"

        @classmethod
        def _get_partition_column_mod(cls, partition_column: str, num_partitions: int) -> str:
            return f"{partition_column} % {num_partitions}"

    @property
    def jdbc_url(self) -> str:
        prop = self.extra.dict(by_alias=True)
        prop["databaseName"] = self.database
        parameters = ";".join(f"{k}={v}" for k, v in sorted(prop.items()))

        return f"jdbc:sqlserver://{self.host}:{self.port};{parameters}"

    @property
    def instance_url(self) -> str:
        return f"{super().instance_url}/{self.database}"

    def _get_datetime_value_sql(self, value: datetime) -> str:
        result = value.isoformat()
        return f"CAST('{result}' AS datetime2)"

    def _get_date_value_sql(self, value: date) -> str:
        result = value.isoformat()
        return f"CAST('{result}' AS date)"
