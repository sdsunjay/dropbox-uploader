"""
Backs up and restores a settings file to Dropbox.
This is an example app for API v2.

Copied and modified from https://github.com/dropbox/dropbox-sdk-python/blob/main/example/back-up-and-restore/backup-and-restore-example.py
"""

import os
import json
import sys
from datetime import datetime
import dropbox
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError
import click

from constants import BACKUP_DIR
from auth import auth

MAX_FILE_SIZE = 150
CONFIG_FILE = "config.ini"


def load_file_paths(config_path, home_path):
    with open(config_path, "r") as f:
        config = json.load(f)

    # Create a dictionary where the filename is the key and the value is the full path
    file_paths = {
        key: (os.path.join(home_path, value) if not value.startswith("/") else value)
        for key, value in config.items()
    }
    return file_paths


def get_dropbox_path(local_file, backup_filename, verbose=True):
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    if verbose:
        click.echo(f"Uploading {local_file} to Dropbox as {backup_path}...")
    return backup_path


def backup(dbx, local_file, backup_filename):
    file_size = os.path.getsize(local_file)  # Get the file size
    file_size_mb = file_size / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE:
        print(
            f"INFO: File exceeds max size of {MAX_FILE_SIZE} MB: {local_file} (Size: {file_size_mb:.2f} MB)"
        )
        upload_large_files(dbx, local_file, backup_filename, file_size)
        return

    with open(local_file, "rb") as f:
        backup_path = get_dropbox_path(local_file, backup_filename)

        try:
            # We use WriteMode=overwrite to make sure that the settings in the file
            # are changed on upload
            dbx.files_upload(f.read(), backup_path, mode=WriteMode("overwrite"))
        except ApiError as err:
            if (
                err.error.is_path()
                and err.error.get_path().reason.is_insufficient_space()
            ):
                sys.exit("ERROR: Cannot back up; insufficient space.")
            elif err.user_message_text:
                print(err.user_message_text)
                sys.exit()
            else:
                print(err)
                sys.exit()


def upload_large_files(dbx, local_file, backup_filename, file_size):
    CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB chunk size

    # Get the backup path for the file
    backup_path = get_dropbox_path(local_file, backup_filename)

    with open(local_file, "rb") as f:
        try:
            # Start upload session
            upload_sesh_start = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
            cursor = dropbox.files.UploadSessionCursor(
                session_id=upload_sesh_start.session_id, offset=f.tell()
            )
            commit = dropbox.files.CommitInfo(path=backup_path)

            # Upload chunks
            while f.tell() < file_size:
                if (file_size - f.tell()) <= CHUNK_SIZE:
                    dbx.files_upload_session_finish(f.read(CHUNK_SIZE), cursor, commit)
                    break
                else:
                    dbx.files_upload_session_append_v2(f.read(CHUNK_SIZE), cursor)
                    cursor.offset = f.tell()

        except ApiError as err:
            if (
                err.error.is_path()
                and err.error.get_path().reason.is_insufficient_space()
            ):
                sys.exit("ERROR: Cannot back up; insufficient space.")
            elif err.user_message_text:
                print(err.user_message_text)
            else:
                print(f"API error: {err}")


def restore(dbx, local_file, backup_path, rev=None, verbose=True):
    if verbose:
        click.echo(f"Restoring {backup_path} to revision {rev} on Dropbox...")

    # Restore the file to the specified revision
    dbx.files_restore(backup_path, rev)

    # Check if the local file exists and ask the user for confirmation
    if os.path.exists(local_file):
        overwrite = (
            click.prompt(
                f"{local_file} already exists. Do you want to overwrite it? (y/n): ",
                type=str,
                default="n",
            )
            .strip()
            .lower()
        )
        if overwrite != "y":
            # Rename the file using its revision
            local_file = f"{local_file}_rev_{rev}"

    # Download the current version of the file from Dropbox
    click.echo(
        f"Downloading current version of {backup_path} from Dropbox, saving as {local_file}..."
    )
    with open(local_file, "wb") as f:
        metadata, res = dbx.files_download(path=backup_path)
        f.write(res.content)

    if verbose:
        click.secho(f"Restored {local_file}", fg="green")


def check_files_exist(files):
    for file in files:
        if not os.path.exists(file):
            raise FileNotFoundError(f"File not found: {file}")


def format_datetime(dt):
    current_year = datetime.now().year
    if dt.year == current_year:
        return dt.strftime("%b %d %H:%M")
    else:
        return dt.strftime("%b %d %H:%M %Y")


@click.group()
@click.pass_context
def cli(ctx):
    ctx.ensure_object(dict)
    ctx.obj["dbx"] = auth()


@click.command()
@click.pass_context
def backup_files(ctx):
    """Backup the predefined files."""

    # Get the home path
    home_path = os.path.expanduser("~")

    file_paths = load_file_paths("file_paths.json", home_path)

    check_files_exist(file_paths.values())
    dbx = ctx.obj["dbx"]
    for filename, full_path in file_paths.items():
        backup(dbx, full_path, filename)

    click.secho("All files backed up successfully.", fg="green")


@click.command()
@click.argument(
    "file_path",
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True
    ),
)
@click.pass_context
def backup_file(ctx, file_path):
    """Backup a user-specified file."""

    dbx = ctx.obj["dbx"]
    filename = os.path.basename(file_path)
    backup(dbx, file_path, filename)
    click.secho(f"File {file_path} backed up successfully.", fg="green")


def human_readable_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"  # In case the size is extremely large


def list_files_in_dropbox(dbx):
    """List files in Dropbox."""
    backups = dbx.files_list_folder(BACKUP_DIR)

    if not backups.entries:
        print("No files found in Dropbox.")
        return []

    file_list = []
    print("Files in Dropbox:")
    for i, entry in enumerate(backups.entries):
        human_size = human_readable_size(entry.size)
        file_info = f"{i + 1}: {human_size} {format_datetime(entry.server_modified)} {entry.name}"
        print(file_info)
        file_list.append(entry)

    return file_list


@click.command()
@click.pass_context
def list_files(ctx):
    """List files in Dropbox."""
    dbx = ctx.obj["dbx"]
    list_files_in_dropbox(dbx)


def help_select_revision(dbx, backup_path):
    """List the revisions for a specific file (and sort by the datetime object, "server_modified") and select one."""
    revisions = dbx.files_list_revisions(backup_path, limit=30).entries
    if not revisions:
        print(f"No revisions found for {backup_path}.")
        return None

    sorted_revisions = sorted(revisions, key=lambda revision: revision.server_modified)

    print(f"Revisions for {backup_path}:")
    for i, rev in enumerate(sorted_revisions):
        human_size = human_readable_size(rev.size)
        file_revision_info = (
            f"{i + 1}: {human_size} {format_datetime(rev.server_modified)} {rev.rev}"
        )
        print(file_revision_info)

    while True:
        selected_index = click.prompt(
            "Enter the number of the revision to restore (Enter 0 to quit)", type=int
        )

        if 1 <= selected_index <= len(revisions):
            return sorted_revisions[selected_index - 1].rev
        else:
            if selected_index == 0:
                return None
            click.secho("Invalid selection. Please try again.", fg="red")


@click.command()
@click.pass_context
def select_revision(ctx):
    """List files in Dropbox and select a file to see revisions."""
    dbx = ctx.obj["dbx"]
    file_list = list_files_in_dropbox(dbx)

    if not file_list:
        return

    selected_index = click.prompt(
        "Enter the number of the file to see revisions", type=int
    )

    if 1 <= selected_index <= len(file_list):
        selected_file = file_list[selected_index - 1]
        print(f"Selected file: {selected_file.name}")

        revision = help_select_revision(dbx, selected_file.path_lower)
        if revision:
            print(f"Selected revision: {revision}")
    else:
        click.secho("Invalid selection.", fg="red")


@click.command()
@click.argument(
    "file_path",
    type=click.Path(
        exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True
    ),
)
@click.option(
    "--revision",
    "-r",
    help="The revision to restore. If not provided, will prompt interactively.",
)
@click.option(
    "--dropbox-path",
    "-p",
    help="The path of the file in Dropbox to be restored.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enables verbose mode.")
@click.pass_context
def restore_file(ctx, file_path, revision, dropbox_path, verbose):
    """Restore a user-selected file and revision from Dropbox."""
    dbx = ctx.obj["dbx"]
    filename = os.path.basename(file_path)
    dropbox_path = get_dropbox_path(file_path, filename, verbose)

    if not revision:
        revision = help_select_revision(dbx, dropbox_path)

        if not revision:
            click.secho("Unexpected error with file revision", fg="red")
            return

        if verbose:
            # Ask the user to confirm the selected revision if verbose mode is enabled
            confirm = (
                click.prompt(
                    f"Selected revision: {revision}. Do you want to continue with restoring this revision? (y/n)",
                    type=str,
                    default="n",
                )
                .strip()
                .lower()
            )
            if confirm != "y":
                return

    try:
        restore(dbx, file_path, dropbox_path, revision, verbose)
        click.secho(
            f"File {file_path} restored to revision {revision} successfully.",
            fg="green",
        )
    except ApiError as err:
        if err.error.is_path() and err.error.get_path().reason.is_insufficient_space():
            click.secho("ERROR: Cannot restore; insufficient space.", fg="red")
        elif err.user_message_text:
            click.secho(err.user_message_text, fg="red")
        else:
            click.secho(f"Error restoring file: {err}", fg="red")


cli.add_command(list_files)
cli.add_command(backup_files)
cli.add_command(backup_file)
cli.add_command(select_revision)
cli.add_command(restore_file)

if __name__ == "__main__":
    cli(obj={})
