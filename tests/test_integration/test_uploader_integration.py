import logging
import os
import secrets
import tempfile
from pathlib import Path, PurePosixPath

import pytest

from onetl.connection import FileConnection, FileWriteMode
from onetl.core import FileUploader
from onetl.exception import DirectoryNotFoundError


class TestUploader:
    @pytest.mark.parametrize("path_type", [str, PurePosixPath], ids=["path_type str", "path_type PurePosixPath"])
    @pytest.mark.parametrize(
        "run_path_type",
        [str, Path],
        ids=["run_path_type str", "run_path_type Path"],
    )
    def test_run_with_files(self, file_connection, test_files, run_path_type, path_type):
        target_path = path_type(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # upload files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
        )

        upload_result = uploader.run(run_path_type(file) for file in test_files)

        assert not upload_result.failed
        assert not upload_result.missing
        assert not upload_result.skipped
        assert upload_result.success

        assert sorted(upload_result.success) == sorted(PurePosixPath(target_path) / file.name for file in test_files)

        for remote_file in upload_result.success:
            assert remote_file.exists()
            assert remote_file.is_file()
            assert not remote_file.is_dir()

            # directory structure is being flattened during upload, restoring it
            local_file = next(file for file in test_files if file.name == remote_file.name)

            # file size is same as expected
            assert file_connection.get_stat(remote_file).st_size == local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content is same as expected
            assert file_connection.read_bytes(remote_file) == local_file.read_bytes()

    def test_view_files(self, file_connection, resource_path):
        target_path = f"/tmp/test_upload_{secrets.token_hex(5)}"

        # upload files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            local_path=resource_path,
        )

        local_files = uploader.view_files()

        local_files_list = []

        for root, _dirs, files in os.walk(resource_path):
            for file in files:
                local_files_list.append(Path(root) / file)

        assert local_files
        assert sorted(local_files) == sorted(local_files_list)

    @pytest.mark.parametrize("path_type", [str, PurePosixPath], ids=["path_type str", "path_type Path"])
    def test_run_with_local_path(self, file_connection, resource_path, path_type):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # upload files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            local_path=path_type(resource_path),
        )

        upload_result = uploader.run()

        assert not upload_result.failed
        assert not upload_result.missing
        assert not upload_result.skipped
        assert upload_result.success

        local_files_list = []

        for root, _, files in os.walk(resource_path):
            for file_name in files:
                local_files_list.append(Path(root) / file_name)

        assert sorted(path for path in upload_result.success) == sorted(
            Path(target_path) / file.relative_to(resource_path) for file in local_files_list
        )

        for remote_file in upload_result.success:
            assert remote_file.exists()
            assert remote_file.is_file()
            assert not remote_file.is_dir()

            # directory structure is being flattened during upload, restoring it
            local_file = next(file for file in local_files_list if file.name == remote_file.name)

            # file size is same as expected
            assert file_connection.get_stat(remote_file).st_size == local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content is same as expected
            assert file_connection.read_bytes(remote_file) == local_file.read_bytes()

    def test_run_missing_file(self, file_connection, test_files, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # upload files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
        )

        missing_file = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(test_files + [missing_file])

            assert f"Missing file '{missing_file}', skipping" in caplog.text

        assert not upload_result.failed
        assert not upload_result.skipped

        assert upload_result.success
        assert len(upload_result.success) == len(test_files)

        assert upload_result.missing
        assert len(upload_result.missing) == 1
        assert upload_result.missing == {missing_file}

        for missing_file in upload_result.missing:
            assert not missing_file.exists()

    def test_run_delete_source(self, resource_path, test_files, file_connection, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            options=file_connection.Options(delete_source=True),
        )

        local_files_list = []
        local_files_stat = {}
        local_files_bytes = {}

        for root, _, files in os.walk(resource_path):
            for file_name in files:
                local_file = Path(root) / file_name
                local_files_list.append(local_file)
                local_files_stat[local_file] = local_file.stat()
                local_files_bytes[local_file] = local_file.read_bytes()

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(test_files)

            assert "LOCAL FILES WILL BE PERMANENTLY DELETED AFTER UPLOADING !!!" in caplog.text

        assert not upload_result.failed
        assert not upload_result.skipped
        assert not upload_result.missing
        assert upload_result.success

        assert sorted(upload_result.success) == sorted(target_path / file.name for file in test_files)

        existing_files = []
        for root, _dirs, files in os.walk(resource_path):
            for file_name in files:
                existing_files.append(Path(root) / file_name)

        for remote_file in upload_result.success:
            assert remote_file.exists()
            assert remote_file.is_file()
            assert not remote_file.is_dir()

            # directory structure is being flattened during upload, restoring it
            local_file = next(file for file in test_files if file.name == remote_file.name)

            # file size is same as expected
            assert file_connection.get_stat(remote_file).st_size == local_files_stat[local_file].st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content is same as expected
            assert file_connection.read_bytes(remote_file) == local_files_bytes[local_file]

            # uploaded file is removed
            assert local_file not in existing_files
            assert not local_file.exists()

        # skipped files are left intact
        assert existing_files

    @pytest.mark.parametrize(
        "options",
        [{"mode": "error"}, FileConnection.Options(mode="error"), FileConnection.Options(mode=FileWriteMode.ERROR)],
    )
    def test_run_mode_error(self, request, file_connection, test_files, options):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # make copy of files to upload in the target_path
        remote_files = []
        for test_file in test_files:
            remote_file = target_path / test_file.name
            remote_files.append(file_connection.write_text(remote_file, "unchanged"))

        def finalizer():
            file_connection.rmdir(target_path, recursive=True)

        request.addfinalizer(finalizer)

        # upload changed files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            options=options,
        )

        upload_result = uploader.run(test_files)

        assert not upload_result.success
        assert not upload_result.missing
        assert not upload_result.skipped
        assert upload_result.failed

        assert sorted(upload_result.failed) == sorted(test_files)

        for local_file in upload_result.failed:
            assert local_file.exists()
            assert local_file.is_file()
            assert not local_file.is_dir()

            assert isinstance(local_file.exception, FileExistsError)

            remote_file = remote_files[remote_files.index(target_path / local_file.name)]
            assert f"Target directory already contains file '{remote_file}'" in str(local_file.exception)

            # file size wasn't changed
            assert file_connection.get_stat(remote_file).st_size != local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content wasn't changed
            assert file_connection.read_text(remote_file) == "unchanged"

    def test_run_mode_ignore(self, request, file_connection, test_files, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # make copy of files to upload in the target_path
        remote_files = []
        for test_file in test_files:
            remote_file = target_path / test_file.name
            remote_files.append(file_connection.write_text(remote_file, "unchanged"))

        def finalizer():
            file_connection.rmdir(target_path, recursive=True)

        request.addfinalizer(finalizer)

        # upload changed files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            options=FileConnection.Options(mode=FileWriteMode.IGNORE),
        )

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(test_files)

            for file in remote_files:
                assert f"Target directory already contains file '{file}', skipping" in caplog.text

        assert not upload_result.success
        assert not upload_result.missing
        assert not upload_result.failed
        assert upload_result.skipped

        assert sorted(upload_result.skipped) == sorted(test_files)

        for local_file in upload_result.skipped:
            assert local_file.exists()
            assert local_file.is_file()
            assert not local_file.is_dir()

            remote_file = remote_files[remote_files.index(target_path / local_file.name)]

            # file size wasn't changed
            assert file_connection.get_stat(remote_file).st_size != local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content wasn't changed
            assert file_connection.read_text(remote_file) == "unchanged"

    def test_run_mode_overwrite(self, request, file_connection, test_files, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # make copy of files to upload in the target_path
        remote_files = []
        for test_file in test_files:
            remote_file = target_path / test_file.name
            remote_files.append(file_connection.write_text(remote_file, "unchanged"))

        def finalizer():
            file_connection.rmdir(target_path, recursive=True)

        request.addfinalizer(finalizer)

        # upload changed files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            options=FileConnection.Options(mode=FileWriteMode.OVERWRITE),
        )

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(test_files)

            for target_file in remote_files:
                assert f"Target directory already contains file '{target_file}', overwriting" in caplog.text

        assert not upload_result.failed
        assert not upload_result.skipped
        assert not upload_result.missing
        assert upload_result.success

        assert sorted(upload_result.success) == sorted(PurePosixPath(file) for file in remote_files)

        for remote_file in upload_result.success:
            assert remote_file.exists()
            assert remote_file.is_file()
            assert not remote_file.is_dir()

            old_remote_file = remote_files[remote_files.index(target_path / remote_file.name)]

            # directory structure is being flattened during upload, restoring it
            local_file = next(file for file in test_files if file.name == remote_file.name)

            # file size was changed
            assert file_connection.get_stat(remote_file).st_size != old_remote_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content was changed
            assert file_connection.read_text(remote_file) != "unchanged"
            assert file_connection.read_bytes(remote_file) == local_file.read_bytes()

    def test_run_mode_delete_all(self, request, resource_path, file_connection, test_files, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # make copy of files to upload in the target_path
        new_remote_file = target_path / secrets.token_hex(5)
        file_connection.write_text(new_remote_file, "abc")

        def finalizer():
            file_connection.rmdir(target_path, recursive=True)

        request.addfinalizer(finalizer)

        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            options=FileConnection.Options(mode=FileWriteMode.DELETE_ALL),
        )

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(test_files)
            assert "TARGET DIRECTORY WILL BE CLEANED UP BEFORE UPLOADING FILES !!!" in caplog.text

        assert not upload_result.failed
        assert not upload_result.skipped
        assert not upload_result.missing
        assert upload_result.success

        assert sorted(upload_result.success) == sorted(target_path / test_file.name for test_file in test_files)

        assert not file_connection.path_exists(new_remote_file)

    def test_run_local_path_does_not_exist(self, file_connection, tmp_path_factory):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        local_path_parent = tmp_path_factory.mktemp("local_path")
        local_path = local_path_parent / "abc"

        uploader = FileUploader(connection=file_connection, target_path=target_path, local_path=local_path)

        with pytest.raises(DirectoryNotFoundError, match=f"'{local_path}' does not exist"):
            uploader.run()

    def test_run_local_path_not_a_directory(self, file_connection):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        with tempfile.NamedTemporaryFile() as file:
            uploader = FileUploader(connection=file_connection, target_path=target_path, local_path=file.name)

            with pytest.raises(NotADirectoryError, match=f"'{file.name}' is not a directory"):
                uploader.run()

    def test_run_target_path_not_a_directory(self, request, file_connection, resource_path):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")
        file_connection.write_text(target_path, "abc")

        def finalizer():
            file_connection.remove_file(target_path)

        request.addfinalizer(finalizer)

        uploader = FileUploader(connection=file_connection, target_path=target_path, local_path=resource_path)

        with pytest.raises(NotADirectoryError, match=f"'{target_path}' is not a directory"):
            uploader.run()

    @pytest.mark.parametrize(
        "pass_local_path",
        [False, True],
        ids=["Without local_path", "With local_path"],
    )
    def test_run_with_empty_files(self, file_connection, pass_local_path, tmp_path_factory):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")
        local_path = tmp_path_factory.mktemp("local_path")

        downloader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            local_path=local_path if pass_local_path else None,
        )

        download_result = downloader.run([])

        assert not download_result.failed
        assert not download_result.skipped
        assert not download_result.missing
        assert not download_result.success

    def test_run_with_empty_local_path(self, file_connection, tmp_path_factory):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")
        local_path = tmp_path_factory.mktemp("local_path")

        downloader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            local_path=local_path,
        )

        download_result = downloader.run()

        assert not download_result.failed
        assert not download_result.skipped
        assert not download_result.missing
        assert not download_result.success

    def test_without_files_and_without_local_path(self, file_connection):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        uploader = FileUploader(connection=file_connection, target_path=target_path)

        with pytest.raises(ValueError, match="Neither file collection nor ``local_path`` are passed"):
            uploader.run()

    def test_run_with_relative_files_and_local_path(self, file_connection, resource_path, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # upload files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            local_path=resource_path,
        )

        local_files_list = []
        for root, _, files in os.walk(resource_path):
            for file_name in files:
                abs_path_file = Path(root) / file_name
                local_files_list.append(abs_path_file.relative_to(resource_path))

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(local_files_list)
            assert (
                "Passed both ``local_path`` and file collection at the same time. File collection will be used"
            ) in caplog.text

        assert not upload_result.failed
        assert not upload_result.missing
        assert upload_result.success
        assert sorted(path for path in upload_result.success) == sorted(
            PurePosixPath(target_path) / file for file in local_files_list
        )

        for remote_file in upload_result.success:
            assert remote_file.exists()
            assert remote_file.is_file()
            assert not remote_file.is_dir()

            local_file = resource_path / remote_file.relative_to(target_path)

            # file size is same as expected
            assert file_connection.get_stat(remote_file).st_size == local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content is same as expected
            assert file_connection.read_bytes(remote_file) == local_file.read_bytes()

    def test_run_with_absolute_files_and_local_path(self, file_connection, resource_path, caplog):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        # upload files
        uploader = FileUploader(
            connection=file_connection,
            target_path=target_path,
            local_path=resource_path,
        )

        local_files_list = []
        for root, _, files in os.walk(resource_path):
            for file_name in files:
                local_files_list.append(Path(root) / file_name)

        with caplog.at_level(logging.WARNING):
            upload_result = uploader.run(local_files_list)
            assert (
                "Passed both ``local_path`` and file collection at the same time. File collection will be used"
            ) in caplog.text

        assert not upload_result.failed
        assert not upload_result.missing
        assert upload_result.success
        assert sorted(path for path in upload_result.success) == sorted(
            PurePosixPath(target_path) / file.relative_to(resource_path) for file in local_files_list
        )

        for remote_file in upload_result.success:
            assert remote_file.exists()
            assert remote_file.is_file()
            assert not remote_file.is_dir()

            local_file = resource_path / remote_file.relative_to(target_path)

            # file size is same as expected
            assert file_connection.get_stat(remote_file).st_size == local_file.stat().st_size
            assert file_connection.get_stat(remote_file).st_size == remote_file.stat().st_size

            # file content is same as expected
            assert file_connection.read_bytes(remote_file) == local_file.read_bytes()

    def test_run_absolute_path_not_match_local_path(self, file_connection, resource_path):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        uploader = FileUploader(connection=file_connection, target_path=target_path, local_path=resource_path)

        with pytest.raises(ValueError, match=f"File path '/some/path/1' does not match source_path '{resource_path}'"):
            uploader.run(["/some/path/1", "/some/path/2"])

    def test_run_relative_paths_without_local_path(self, file_connection):
        target_path = PurePosixPath(f"/tmp/test_upload_{secrets.token_hex(5)}")

        uploader = FileUploader(connection=file_connection, target_path=target_path)

        with pytest.raises(ValueError, match="Cannot pass relative file path with empty ``local_path``"):
            uploader.run(["some/path/1", "some/path/2"])

    def test_source_check(self, file_connection, caplog):
        with caplog.at_level(logging.INFO):
            file_connection.check()

        assert "Connection is available" in caplog.text
