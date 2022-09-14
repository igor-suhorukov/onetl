from __future__ import annotations

import os
import shutil
from enum import Enum
from logging import getLogger
from typing import Iterable, Optional, Tuple, Type

from etl_entities import HWM, FileHWM, RemoteFolder
from ordered_set import OrderedSet
from pydantic import validator

from onetl._internal import generate_temp_path  # noqa: WPS436
from onetl.base import BaseFileConnection, BaseFileFilter, BaseFileLimit
from onetl.base.path_protocol import PathProtocol
from onetl.core.file_downloader.download_result import DownloadResult
from onetl.core.file_filter import FileHWMFilter
from onetl.core.file_limit import FileLimit
from onetl.core.file_result import FileSet
from onetl.impl import (
    FailedRemoteFile,
    FileWriteMode,
    FrozenModel,
    GenericOptions,
    LocalPath,
    RemoteFile,
    RemotePath,
    path_repr,
)
from onetl.log import entity_boundary_log, log_with_indent
from onetl.strategy import BaseStrategy, StrategyManager
from onetl.strategy.batch_hwm_strategy import BatchHWMStrategy
from onetl.strategy.hwm_store import BaseHWMStore, HWMClassRegistry, HWMStoreManager
from onetl.strategy.hwm_strategy import HWMStrategy

log = getLogger(__name__)

# source, target, temp
DOWNLOAD_ITEMS_TYPE = OrderedSet[Tuple[RemotePath, LocalPath, Optional[LocalPath]]]


class FileDownloader(FrozenModel):
    """Class specifies file source where you can download files. Download files **only** to local directory.

    .. note::

        FileDownloader can return different results depending on :ref:`strategy`

    Parameters
    ----------
    connection : :obj:`onetl.connection.FileConnection`
        Class which contains File system connection properties. See in FileConnection section.

    local_path : os.PathLike or str
        Local path where you download files

    source_path : os.PathLike or str, optional, default: ``None``
        Remote path to download files from.

        Could be ``None``, but only if you pass absolute file paths directly to
        :obj:`onetl.core.file_downloader.file_downloader.FileDownloader.run` method

    temp_path : os.PathLike or str, optional, default: ``None``
        If set, this path will be used for downloading a file, and then renaming it to the target file path.
        If ``None`` is passed, files are downloaded directly to ``target_path``.

        .. warning::

            In case of production ETL pipelines, please set a value for ``temp_path`` (NOT ``None``).
            This allows to properly handle download interruption,
            without creating half-downloaded files in the target,
            because unlike file download, ``rename`` call is atomic.

        .. warning::

            In case of connections like SFTP or FTP, which can have multiple underlying filesystems,
            please pass to ``temp_path`` path on the SAME filesystem as ``target_path``.
            Otherwise instead of ``rename``, remote OS will move file between filesystems,
            which is NOT atomic operation.

    filter : BaseFileFilter
        Options of the file filtering. See :obj:`onetl.core.file_filter.file_filter.FileFilter`

    limit : BaseFileLimit
        Options of the file  limiting. See :obj:`onetl.core.file_limit.file_limit.FileLimit`
        Default file count limit is 100

    options : :obj:`onetl.core.file_downloader.file_downloader.FileDownloader.Options`  | dict | None, default: ``None``
        File downloading options. See :obj:`~FileDownloader.Options`

    hwm_type : str | type[HWM] | None, default: ``None``
        HWM type to detect changes in incremental run.

        .. warning ::
            Used only in :obj:`onetl.strategy.incremental_strategy.IncrementalStrategy`.

    Examples
    --------
    Simple Downloader creation

    .. code::

        from onetl.connection import SFTP
        from onetl.core import FileDownloader

        sftp = SFTP(...)

        # create downloader
        downloader = FileDownloader(
            connection=sftp,
            source_path="/path/to/remote/source",
            local_path="/path/to/local",
        )

        # download files to "/path/to/local"
        downloader.run()

    Downloader with all parameters

    .. code::

        from onetl.connection import SFTP
        from onetl.core import FileDownloader, FileFilter, FileLimit

        sftp = SFTP(...)

        # create downloader with a bunch of options
        downloader = FileDownloader(
            connection=sftp,
            source_path="/path/to/remote/source",
            local_path="/path/to/local",
            temp_path="/tmp",
            filter=FileFilter(glob="*.txt", exclude_dirs=["/path/to/remote/source/exclude_dir"]),
            limit=FileLimit(count_limit=10),
            options=FileDownloader.Options(delete_source=True, mode="overwrite"),
        )

        # download files to "/path/to/local"
        downloader.run()

    Incremental download:

    .. code::

        from onetl.connection import SFTP
        from onetl.core import FileDownloader
        from onetl.strategy import IncrementalStrategy

        sftp = SFTP(...)

        # create downloader
        downloader = FileDownloader(
            connection=sftp,
            source_path="/path/to/remote/source",
            local_path="/path/to/local",
            hwm_type="file_list",  # mandatory for IncrementalStrategy
        )

        # download files to "/path/to/local", but only new ones
        with IncrementalStrategy():
            downloader.run()

    """

    class Options(GenericOptions):
        """File downloader options"""

        mode: FileWriteMode = FileWriteMode.ERROR
        """
        How to handle existing files in the local directory.

        Possible values:
            * ``error`` (default) - do nothing, mark file as failed
            * ``ignore`` - do nothing, mark file as ignored
            * ``overwrite`` - replace existing file with a new one
            * ``delete_all`` - delete local directory content before downloading files
        """

        delete_source: bool = False
        """
        If ``True``, remove source file after successful download.

        If download failed, file will left intact.
        """

    connection: BaseFileConnection

    local_path: LocalPath
    source_path: Optional[RemotePath] = None
    temp_path: Optional[LocalPath] = None

    filter: Optional[BaseFileFilter] = None
    limit: Optional[BaseFileLimit] = FileLimit()

    hwm_type: Optional[Type[FileHWM]] = None

    options: Options = Options()

    @validator("local_path", pre=True, always=True)
    def resolve_local_path(cls, local_path):  # noqa: N805
        return LocalPath(local_path).resolve()

    @validator("source_path", pre=True, always=True)
    def check_source_path(cls, source_path):  # noqa: N805
        return RemotePath(source_path) if source_path else None

    @validator("temp_path", pre=True, always=True)
    def check_temp_path(cls, temp_path):  # noqa: N805
        return LocalPath(temp_path).resolve() if temp_path else None

    @validator("hwm_type", pre=True, always=True)
    def check_hwm_type(cls, hwm_type, values):  # noqa: N805
        source_path = values.get("source_path")

        if hwm_type:
            if not source_path:
                raise ValueError("If `hwm_type` is passed, `source_path` must be specified")

            if isinstance(hwm_type, str):
                hwm_type = HWMClassRegistry.get(hwm_type)

            cls._check_hwm_type(hwm_type)

        return hwm_type

    def run(self, files: Iterable[str | os.PathLike] | None = None) -> DownloadResult:  # noqa: WPS231
        """
        Method for downloading files from source to local directory.

        .. note::

            This method can return different results depending on :ref:`strategy`

        Parameters
        ----------

        files : Iterable[str | os.PathLike] | None, default ``None``
            File collection to download.

            If empty, download files from ``source_path``,
            applying ``filter``, ``limit`` and ``hwm_type`` to each one (if set).

            If not, download **all** input files, **without**
            any filtering, limiting and excluding files covered by FileHWM

        Returns
        -------
        downloaded_files : :obj:`onetl.core.file_downloader.download_result.DownloadResult`

            Download result object

        Raises
        -------
        DirectoryNotFoundError

            ``source_path`` does not found

        NotADirectoryError

            ``source_path`` or ``local_path`` is not a directory

        Examples
        --------

        Download files from ``source_path``

        .. code:: python

            from onetl.impl import RemoteFile, LocalPath
            from onetl.core import FileDownloader

            downloader = FileDownloader(source_path="/remote", local_path="/local", ...)
            downloaded_files = downloader.run()

            assert downloaded_files.successful == {
                LocalPath("/local/path/file1.txt"),
                LocalPath("/local/path/file2.txt"),
                LocalPath("/local/path/nested/file3.txt"),  # directory structure is preserved
            }
            assert downloaded_files.failed == {FailedRemoteFile("/failed/file")}
            assert downloaded_files.skipped == {RemoteFile("/existing/file")}
            assert downloaded_files.missing == {RemotePath("/missing/file")}

        Download only certain files from ``source_path``

        .. code:: python

            from onetl.impl import RemoteFile, LocalPath
            from onetl.core import FileDownloader

            downloader = FileDownloader(source_path="/remote", local_path="/local", ...)

            downloaded_files = downloader.run(
                [
                    "/remote/path/file1.txt",
                    "/remote/path/nested/file3.txt",
                    # excluding "/remote/path/file2.txt"
                ]
            )

            assert downloaded_files.successful == {
                LocalPath("/local/path/file1.txt"),
                LocalPath("/local/path/nested/file3.txt"),  # directory structure is preserved
            }
            assert not downloaded_files.failed
            assert not downloaded_files.skipped
            assert not downloaded_files.missing

        Download certain files from any folder

        .. code:: python

            from onetl.impl import RemoteFile, LocalPath
            from onetl.core import FileDownloader

            downloader = FileDownloader(local_path="/local", ...)  # no source_path set

            downloaded_files = downloader.run(
                [
                    "/remote/path/file1.txt",
                    "/remote/path/nested/file3.txt",
                ]
            )

            assert downloaded_files.successful == {
                LocalPath("/local/path/file1.txt"),
                LocalPath("/local/path/file3.txt"),  # directory structure is not preserved
            }
            assert not downloaded_files.failed
            assert not downloaded_files.skipped
            assert not downloaded_files.missing
        """

        self._check_strategy()

        if files is None and not self.source_path:
            raise ValueError("Neither file collection nor ``source_path`` are passed")

        self._log_options(files)

        # Check everything
        self._check_local_path()
        self.connection.check()
        log_with_indent("")

        if self.source_path:
            self._check_source_path()

        if files is None:
            log.info(f"|{self.__class__.__name__}| File collection is not passed to `run` method")
            files = self.view_files()

        if not files:
            log.info(f"|{self.__class__.__name__}| No files to download!")
            return DownloadResult()

        current_temp_dir: LocalPath | None = None
        if self.temp_path:
            current_temp_dir = generate_temp_path(self.temp_path)

        to_download = self._validate_files(files, current_temp_dir=current_temp_dir)

        # remove folder only after everything is checked
        if self.options.mode == FileWriteMode.DELETE_ALL:
            if self.local_path.exists():
                shutil.rmtree(self.local_path)
            self.local_path.mkdir()

        if self.hwm_type is not None:
            result = self._hwm_processing(to_download)
        else:
            result = self._download_files(to_download)

        if current_temp_dir:
            self._remove_temp_dir(current_temp_dir)

        self._log_result(result)
        return result

    def view_files(self) -> FileSet[RemoteFile]:
        """
        Get file collection in the ``source_path``,
        after ``filter``, ``limit`` and ``hwm`` applied (if any)

        .. note::

            This method can return different results depending on :ref:`strategy`

        Raises
        -------
        DirectoryNotFoundError

            ``source_path`` does not found

        NotADirectoryError

            ``source_path`` is not a directory

        Returns
        -------
        FileSet[RemoteFile]
            Set of files in ``source_path``, which will be downloaded by :obj:`~run` method

        Examples
        --------

        View files

        .. code:: python

            from onetl.impl import RemoteFile
            from onetl.core import FileDownloader

            downloader = FileDownloader(source_path="/remote/path", ...)

            view_files = downloader.view_files()

            assert view_files == {
                RemoteFile("/remote/path/file1.txt"),
                RemoteFile("/remote/path/file3.txt"),
                RemoteFile("/remote/path/nested/file3.txt"),
            }
        """

        log.info(f"|{self.connection.__class__.__name__}| Getting files list from path '{self.source_path}'")

        self._check_source_path()
        result = FileSet()

        filters = []
        if self.filter:
            filters.append(self.filter)
        if self.hwm_type:
            filters.append(FileHWMFilter(hwm=self._get_hwm()))

        limits = []
        if self.limit:
            limits.append(self.limit)

        try:
            for root, _dirs, files in self.connection.walk(self.source_path, filters=filters, limits=limits):
                for file in files:
                    result.append(RemoteFile(path=root / file, stats=file.stats))

        except Exception as e:
            raise RuntimeError(
                f"Couldn't read directory tree from remote dir '{self.source_path}'",
            ) from e

        return result

    def _check_strategy(self):
        strategy: BaseStrategy = StrategyManager.get_current()

        if self.hwm_type:
            if not isinstance(strategy, HWMStrategy):
                raise ValueError(f"|{self.__class__.__name__}| `hwm_type` cannot be used in snapshot strategy.")
            elif getattr(strategy, "offset", None):  # this check should be somewhere in IncrementalStrategy,
                # but the logic is quite messy
                raise ValueError(f"|{self.__class__.__name__}| If `hwm_type` is passed you can't specify an `offset`")

            if isinstance(strategy, BatchHWMStrategy):
                raise ValueError(f"|{self.__class__.__name__}| `hwm_type` cannot be used in batch strategy.")

    def _get_hwm(self) -> FileHWM:
        remote_file_folder = RemoteFolder(name=self.source_path, instance=self.connection.instance_url)
        file_hwm_empty = self.hwm_type(source=remote_file_folder)
        file_hwm_name = file_hwm_empty.qualified_name

        current_hwm_store = HWMStoreManager.get_current()
        file_hwm = current_hwm_store.get(file_hwm_name) or file_hwm_empty

        # to avoid issues when HWM store returned HWM with unexpected type
        self._check_hwm_type(file_hwm.__class__)
        return file_hwm

    def _hwm_processing(self, to_download: DOWNLOAD_ITEMS_TYPE) -> DownloadResult:
        file_hwm = self._get_hwm()

        return self._download_files(
            to_download,
            file_hwm=file_hwm,
        )

    def _log_options(self, files: Iterable[str | os.PathLike] | None = None) -> None:  # noqa: WPS213
        entity_boundary_log(msg="FileDownloader starts")

        log.info(f"|{self.connection.__class__.__name__}| -> |Local FS| Downloading files using parameters:")
        source_path_str = f"'{self.source_path}'" if self.source_path else "None"
        log_with_indent(f"source_path = {source_path_str}")
        log_with_indent(f"local_path = '{self.local_path}'")
        if self.temp_path:
            log_with_indent(f"temp_path = '{self.temp_path}'")
        else:
            log_with_indent("temp_path = None")

        if self.filter is not None:
            log_with_indent("filter:")
            self.filter.log_options(indent=4)
        else:
            log_with_indent("filter = None")

        if self.limit is not None:
            log_with_indent("limit:")
            self.limit.log_options(indent=4)
        else:
            log_with_indent("limit = None")

        log_with_indent("options:")
        for option, value in self.options.dict(by_alias=True).items():
            value_wrapped = f"'{value}'" if isinstance(value, Enum) else repr(value)
            log_with_indent(f"{option} = {value_wrapped}", indent=4)
        log_with_indent("")

        if self.options.delete_source:
            log.warning(f"|{self.__class__.__name__}| SOURCE FILES WILL BE PERMANENTLY DELETED AFTER DOWNLOADING !!!")

        if self.options.mode == FileWriteMode.DELETE_ALL:
            log.warning(f"|{self.__class__.__name__}| LOCAL DIRECTORY WILL BE CLEANED UP BEFORE DOWNLOADING FILES !!!")

        if files and self.source_path:
            log.warning(
                f"|{self.__class__.__name__}| Passed both ``source_path`` and file collection at the same time. "
                "File collection will be used",
            )

    def _validate_files(  # noqa: WPS231
        self,
        remote_files: Iterable[os.PathLike | str],
        current_temp_dir: LocalPath | None,
    ) -> DOWNLOAD_ITEMS_TYPE:
        result = OrderedSet()

        for file in remote_files:
            remote_file_path = file if isinstance(file, PathProtocol) else RemotePath(file)
            remote_file = remote_file_path
            tmp_file: LocalPath | None = None

            if not self.source_path:
                # Download into a flat structure
                if not remote_file_path.is_absolute():
                    raise ValueError("Cannot pass relative file path with empty ``source_path``")

                filename = remote_file_path.name
                local_file = self.local_path / filename
                if current_temp_dir:
                    tmp_file = current_temp_dir / filename  # noqa: WPS220
            else:
                # Download according to source folder structure
                if self.source_path in remote_file_path.parents:
                    # Make relative local path
                    local_file = self.local_path / remote_file_path.relative_to(self.source_path)
                    if current_temp_dir:
                        tmp_file = current_temp_dir / remote_file_path.relative_to(self.source_path)  # noqa: WPS220

                elif not remote_file_path.is_absolute():
                    # Passed path is already relative
                    local_file = self.local_path / remote_file_path
                    remote_file = self.source_path / remote_file_path
                    if current_temp_dir:
                        tmp_file = current_temp_dir / remote_file_path  # noqa: WPS220
                else:
                    # Wrong path (not relative path and source path not in the path to the file)
                    raise ValueError(f"File path '{remote_file}' does not match source_path '{self.source_path}'")

            if self.connection.path_exists(remote_file):
                self.connection.get_file(remote_file)

            result.add((remote_file, local_file, tmp_file))

        return result

    def _check_source_path(self):
        self.connection.get_directory(self.source_path)

    def _check_local_path(self):
        if self.local_path.exists() and not self.local_path.is_dir():
            raise NotADirectoryError(f"|Local FS| {path_repr(self.local_path)} is not a directory")

        self.local_path.mkdir(exist_ok=True, parents=True)

    def _download_files(
        self,
        to_download: DOWNLOAD_ITEMS_TYPE,
        file_hwm: FileHWM | None = None,
    ) -> DownloadResult:
        total_files = len(to_download)
        files = FileSet(item[0] for item in to_download)
        hwm_store = HWMStoreManager.get_current()

        log.info(f"|{self.__class__.__name__}| Files to be downloaded:")
        log_with_indent(str(files))
        log_with_indent("")
        log.info(f"|{self.__class__.__name__}| Starting the download process")

        result = DownloadResult()
        for i, (source_file, local_file, tmp_file) in enumerate(to_download):
            log.info(f"|{self.__class__.__name__}| Downloading file {i+1} of {total_files}")
            log_with_indent(f"from = '{source_file}'")
            if tmp_file:
                log_with_indent(f"temp = '{tmp_file}'")
            log_with_indent(f"to = '{local_file}'")

            self._download_file(
                source_file,
                local_file,
                tmp_file,
                result,
                file_hwm=file_hwm,
                hwm_store=hwm_store,
            )

        return result

    def _download_file(  # noqa: WPS231, WPS213
        self,
        source_file: RemotePath,
        local_file: LocalPath,
        tmp_file: LocalPath | None,
        result: DownloadResult,
        file_hwm: FileHWM | None = None,
        hwm_store: BaseHWMStore | None = None,
    ) -> None:
        if not self.connection.path_exists(source_file):
            log.warning(f"|{self.__class__.__name__}| Missing file '{source_file}', skipping")
            result.missing.add(source_file)
            return

        try:
            remote_file = self.connection.get_file(source_file)

            replace = False
            if local_file.exists():
                error_message = f"|LocalFS| File {path_repr(local_file)} already exists"
                if self.options.mode == FileWriteMode.ERROR:
                    raise FileExistsError(error_message)

                if self.options.mode == FileWriteMode.IGNORE:
                    log.warning(f"{error_message}, skipping")
                    result.skipped.add(remote_file)
                    return

                replace = True

            if tmp_file:
                # Files are loaded to temporary directory before moving them to target dir.
                # This prevents operations with partly downloaded files

                self.connection.download_file(remote_file, tmp_file, replace=replace)

                # remove existing file only after new file is downloaded
                # to avoid issues then there is no free space to download new file, but existing one is already gone
                if replace and local_file.exists():
                    log.warning(f"{error_message}, overwriting")
                    local_file.unlink()

                local_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(tmp_file, local_file)
            else:
                # Direct download
                self.connection.download_file(remote_file, local_file, replace=replace)

            if file_hwm is not None:
                file_hwm.update(remote_file)
                hwm_store.save(file_hwm)

            # Delete Remote
            if self.options.delete_source:
                self.connection.remove_file(remote_file)

            result.successful.add(local_file)

        except Exception as e:
            log.exception(
                f"|{self.__class__.__name__}| Couldn't download file from source dir: {e}",
                exc_info=False,
            )
            result.failed.add(FailedRemoteFile(path=remote_file.path, stats=remote_file.stats, exception=e))

    def _remove_temp_dir(self, temp_dir: LocalPath) -> None:
        log.info(f"|Local FS| Removing temp directory '{temp_dir}'")

        try:
            shutil.rmtree(temp_dir)
        except Exception:
            log.exception("|Local FS| Error while removing temp directory")

    def _log_result(self, result: DownloadResult) -> None:
        log_with_indent("")
        log.info(f"|{self.__class__.__name__}| Download result:")
        log_with_indent(str(result))
        entity_boundary_log(msg=f"{self.__class__.__name__} ends", char="-")

    @staticmethod
    def _check_hwm_type(hwm_type: type[HWM]) -> None:
        if not issubclass(hwm_type, FileHWM):
            raise ValueError(
                f"`hwm_type` class should be a inherited from FileHWM, got {hwm_type.__name__}",
            )
