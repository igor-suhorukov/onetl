from __future__ import annotations

import os
from logging import getLogger
from dataclasses import dataclass
from pathlib import Path

from hdfs import InsecureClient, HdfsError
from hdfs.ext.kerberos import KerberosClient

from onetl.connection.file_connection.file_connection import FileConnection
from onetl.connection.kerberos_helpers import KerberosMixin

log = getLogger(__name__)


@dataclass(frozen=True)
class HDFS(FileConnection, KerberosMixin):
    """Class for HDFS file connection.

    Parameters
    ----------
    host : str
        Host of hdfs source. For example: ``rnd-dwh-nn-001.msk.mts.ru``
    port : int, optional, default: ``50070``
        Port of hdfs source
    user : str, default: ``None``
        User, which have access to the file source. For example: ``tech_etl``
    password : str, default: ``None``
        Password for file source connection

        .. warning ::

            To correct work you can provide only one of the parameters: ``password`` or ``kinit``.
            If you provide both, connection will raise Exception.
    kinit : str, default: ``None``
        Path to keytab file.

        .. warning ::

            To correct work you can provide only one of the parameters: ``password`` or ``kinit``.
            If you provide both, connection will raise Exception.
    timeout : int, default: ``10``
        Connection timeouts, forwarded to the request handler.
        How long to wait for the server to send data before giving up.

    Examples
    --------

    HDFS file connection initialization with password

    .. code::

        from onetl.connection.file_connection import HDFS

        hdfs = HDFS(
            host="rnd-dwh-nn-001.msk.mts.ru",
            user="tech_etl",
            password="*****",
        )

    HDFS file connection initialization with keytab

    .. code::

        from onetl.connection.file_connection import HDFS

        hdfs = HDFS(
            host="rnd-dwh-nn-001.msk.mts.ru",
            user="tech_etl",
            keytab="/path/to/keytab",
        )
    """

    port: int = 50070
    user: str = ""
    keytab: str | None = None
    timeout: int | None = None

    def __post_init__(self):
        if self.password and self.keytab:
            raise ValueError("Please provide only `keytab` or only `password` for kinit")

    def get_client(self) -> hdfs.ext.kerberos.KerberosClient | hdfs.client.InsecureClient:
        conn_str = f"http://{self.host}:{self.port}"  # NOSONAR
        if self.keytab or self.password:
            self.kinit(
                self.user,
                keytab=self.keytab,
                password=self.password,
            )
            client = KerberosClient(conn_str, timeout=self.timeout)
        else:
            client = InsecureClient(conn_str, user=self.user)
        client.status("/")
        return client

    def download_file(self, remote_file_path: os.PathLike | str, local_file_path: os.PathLike | str) -> None:
        self.client.download(remote_file_path, local_file_path)
        log.info(f"Successfully download file {remote_file_path} from remote host {self.host} to {local_file_path}")

    def remove_file(self, remote_file_path: os.PathLike | str) -> None:
        if not self.path_exists(remote_file_path):
            raise HdfsError(f"{remote_file_path} doesn`t exists")
        self.client.delete(remote_file_path, recursive=False)
        log.info(f"Successfully removed file {remote_file_path}")

    def is_dir(self, top: os.PathLike | str, item: str) -> bool:
        if self.client.status(Path(top) / self.get_name(item))["type"] == "DIRECTORY":
            return True

    def get_name(self, item: str) -> Path:
        return Path(item)

    def path_exists(self, target_hdfs_path: os.PathLike | str) -> bool:
        return self.client.status(target_hdfs_path, strict=False)

    def mkdir(self, path: os.PathLike | str) -> None:
        self.client.makedirs(path)
        log.info(f"Successfully created directory {path}")

    def upload_file(self, local_file_path: os.PathLike | str, remote_file_path: os.PathLike | str) -> None:
        self.client.upload(remote_file_path, local_file_path)

    def rename(self, source: os.PathLike | str, target: os.PathLike | str) -> None:
        self.client.rename(source, target)
        log.info(f"Successfully renamed file {source} to {target}")

    def rmdir(self, path: os.PathLike | str, recursive: bool = False) -> None:
        self.client.delete(path, recursive=recursive)
        log.info(f"Successfully removed path {path}")

    def _listdir(self, path: os.PathLike | str) -> list:
        return self.client.list(path)
