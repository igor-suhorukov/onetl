from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar

from onetl.connection.db_connection.jdbc_connection import JDBCConnection


@dataclass(frozen=True)
class Postgres(JDBCConnection):
    """Class for PostgreSQL jdbc connection.

    .. note::

        Supported PostgreSQL server versions: >= 8.2

    Parameters
    ----------
    host : str
        Host of postgres database. For example: ``test-db-vip.msk.mts.ru``

    port : int, default: ``5432``
        Port of postgres database

    user : str
        User, which have access to the database and table. For example: ``appmetrica_test``

    password : str
        Password for database connection

    database : str
        Database in rdbms. To provide schema, use DBReader class

        See https://www.educba.com/postgresql-database-vs-schema/ for more details

    spark : pyspark.sql.SparkSession
        Spark session that required for jdbc connection to database.

        You can use ``mtspark`` for spark session initialization.

    Examples
    --------

    Postgres jdbc connection initialization

    .. code::

        from onetl.connection import Postgres
        from mtspark import get_spark

        spark = get_spark({
            "appName": "spark-app-name",
            "spark.jars.packages": [Postgres.package],
        })

        postgres = Postgres(
            host="test-db-vip.msk.mts.ru",
            user="appmetrica_test",
            password="*****",
            database='target_database',
            spark=spark,
        )

    """

    driver: ClassVar[str] = "org.postgresql.Driver"
    package: ClassVar[str] = "org.postgresql:postgresql:42.4.0"
    port: int = 5432

    def __post_init__(self):
        if not self.database:
            raise ValueError(
                f"You should provide database name for {self.__class__.__name__} connection. "
                "Use database parameter: database = 'database_name'",
            )

    @property
    def jdbc_url(self) -> str:
        params_str = "&".join(f"{k}={v}" for k, v in self.extra.items())

        if params_str:
            params_str = f"?{params_str}"

        return f"jdbc:postgresql://{self.host}:{self.port}/{self.database}{params_str}"

    @property
    def instance_url(self) -> str:
        return f"{super().instance_url}/{self.database}"

    def _options_to_connection_properties(self, options: JDBCConnection.Options):
        # See https://github.com/pgjdbc/pgjdbc/pull/1252
        # Since 42.2.9 Postgres JDBC Driver added new option readOnlyMode=transaction
        # Which is not a desired behavior, because `.fetch()` method should always be read-only

        if not getattr(options, "readOnlyMode", None):
            options = options.copy(update={"readOnlyMode": "always"})

        return super()._options_to_connection_properties(options)

    def _get_datetime_value_sql(self, value: datetime) -> str:
        result = value.isoformat()
        return f"'{result}'::timestamp"

    def _get_date_value_sql(self, value: date) -> str:
        result = value.isoformat()
        return f"'{result}'::date"
