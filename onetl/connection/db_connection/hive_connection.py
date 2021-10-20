from dataclasses import dataclass
from typing import Optional, Dict

from onetl.connection.db_connection.db_connection import DBConnection


@dataclass(frozen=True)
class Hive(DBConnection):
    port: int = 10000

    @property
    def url(self) -> str:
        params = "&".join(f"{k}={v}" for k, v in self.extra.items())

        return f"hiveserver2://{self.user}:{self.password}@{self.host}:{self.port}?{params}"

    def save_df(
        self,
        df: "pyspark.sql.DataFrame",
        table: str,
        jdbc_options: Dict,
    ) -> None:
        # TODO:(@dypedchenk) rewrite, take into account all data recording possibilities. Use "mode" param.
        df.write.insertInto(table, overwrite=False)

    # TODO:(@dypedchenk) think about unused params in this method
    def read_table(
        self,
        jdbc_options: Dict,
        table: str,
        columns: Optional[str] = "*",
        sql_hint: Optional[str] = None,
        sql_where: Optional[str] = None,
    ) -> "pyspark.sql.DataFrame":
        if not self.spark:
            raise ValueError("Spark session not provided")
        table = self.get_sql_query(table=table, sql_hint=sql_hint, columns=columns, sql_where=sql_where)
        return self.spark.sql(table)

    def _get_timestamp_value_sql(self, value):
        return value
