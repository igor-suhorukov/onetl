from dataclasses import dataclass, field
from datetime import datetime, date

from onetl.connection.db_connection.jdbc_connection import JDBCConnection


@dataclass(frozen=True)
class MySQL(JDBCConnection):
    """Class for MySQL jdbc connection.

    Parameters
    ----------
    host : str
        Host of MySQL database. For example: ``mysql0012.dmz.msk.mts.ru``
    port : int, optional, default: ``3306``
        Port of MySQL database
    user : str, default: ``None``
        User, which have access to the database and table. For example: ``big_data_tech_user``
    password : str, default: ``None``
        Password for database connection
    database : str, default: ``default``
        Database in rdbms. To provide schema, use DBReader class
    extra : Dict, optional, default: ``None``
        Specifies one or more extra parameters by which clients can connect to the instance.

        For example: ``{"some_extra": "..."}``.
    spark : pyspark.sql.SparkSession, default: ``None``
        Spark session that required for jdbc connection to database.

        You can use ``mtspark`` for spark session initialization.

    Examples
    --------

    MySQL jdbc connection initialization

    .. code::

        from onetl.connection.db_connection import MySQL
        from mtspark import get_spark

        extra = {"some_extra": "..."}

        spark = get_spark({
            "appName": "spark-app-name",
            "spark.jars.packages": MySQL.package,
        })

        mysql = MySQL(
            host="mysql0012.dmz.msk.mts.ru",
            user="big_data_tech_user",
            password="*****",
            extra=extra,
            spark=spark,
        )

    """

    driver: str = field(init=False, default="com.mysql.jdbc.Driver")
    package: str = field(init=False, default="mysql:mysql-connector-java:8.0.26")
    port: int = 3306

    @property
    def url(self):
        prop = self.extra.copy()
        prop["useUnicode"] = "yes"
        prop["characterEncoding"] = "UTF-8"
        params = "&".join(f"{k}={v}" for k, v in prop.items())

        return f"jdbc:mysql://{self.host}:{self.port}/{self.database}?{params}"

    def _get_datetime_value_sql(self, value: datetime) -> str:
        result = value.strftime("%Y-%m-%d %H:%M:%S.%f")
        return f"STR_TO_DATE('{result}', '%Y-%m-%d %H:%i:%s.%f')"  # noqa: WPS323

    def _get_date_value_sql(self, value: date) -> str:
        result = value.strftime("%Y-%m-%d")
        return f"STR_TO_DATE('{result}', '%Y-%m-%d')"  # noqa: WPS323
