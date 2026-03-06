from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import Config

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_FOLDER_MIME = "application/vnd.google-apps.folder"
_AUDIO_MIME = "audio/mpeg"
_ASSETS_FOLDER = "AudioAssets"


class DriveUploader:
    def __init__(self, config: Config):
        sa_path = Path(config.google_service_account_json)
        creds = Credentials.from_service_account_file(str(sa_path), scopes=_SCOPES)
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._root_folder_id = config.google_drive_folder_id
        # Cache (name, parent_id) → folder_id to avoid redundant API calls per run
        self._folder_cache: dict[tuple[str, str], str] = {}

    def upload(self, local_path: Path, key: str) -> str:
        """Upload audio to AudioAssets/{key}/ and return a shareable Drive URL.

        Replaces the file if one with the same name already exists, preserving
        the file ID (and therefore the Drive link).
        """
        assets_id = self._get_or_create_folder(_ASSETS_FOLDER, self._root_folder_id)
        key_folder_id = self._get_or_create_folder(key, assets_id)
        file_id = self._upsert_file(local_path, key_folder_id)
        self._set_public(file_id)
        return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

    def _get_or_create_folder(self, name: str, parent_id: str) -> str:
        cache_key = (name, parent_id)
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        q = (
            f"name='{name}' and '{parent_id}' in parents "
            f"and mimeType='{_FOLDER_MIME}' and trashed=false"
        )
        results = (
            self._service.files()
            .list(q=q, fields="files(id)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
        else:
            metadata = {
                "name": name,
                "mimeType": _FOLDER_MIME,
                "parents": [parent_id],
            }
            folder = (
                self._service.files()
                .create(body=metadata, fields="id")
                .execute()
            )
            folder_id = folder["id"]

        self._folder_cache[cache_key] = folder_id
        return folder_id

    def _upsert_file(self, local_path: Path, parent_id: str) -> str:
        """Upload or replace the file. Returns the file ID (stable across replacements)."""
        filename = local_path.name
        q = f"name='{filename}' and '{parent_id}' in parents and trashed=false"
        results = (
            self._service.files()
            .list(q=q, fields="files(id)", pageSize=1)
            .execute()
        )
        existing = results.get("files", [])
        media = MediaFileUpload(str(local_path), mimetype=_AUDIO_MIME, resumable=False)

        if existing:
            # Replace content, keeping the same file ID so the Drive link is preserved
            file_id = existing[0]["id"]
            self._service.files().update(
                fileId=file_id,
                media_body=media,
                fields="id",
            ).execute()
        else:
            metadata = {"name": filename, "parents": [parent_id]}
            result = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id")
                .execute()
            )
            file_id = result["id"]

        return file_id

    def _set_public(self, file_id: str) -> None:
        """Set 'Anyone with link can view' permission on the file."""
        self._service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
