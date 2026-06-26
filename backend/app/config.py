import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:////data/stl_inventory.db"
    # Native (host) paths for the two drive mounts — used to translate
    # Docker container paths back to Windows/Mac paths for display.
    # Set these to match LIBRARY_DIR / IMPORT_DIR in your .env file.
    stl_drive_1: str = ""
    stl_drive_2: str = ""

    # Scraper API keys (reserved for future use)
    # MMF switched to OAuth-only — scraping is used instead
    mmf_api_key: str = ""

    # Library reorganize apply (#324, Phase 2a) — the ONLY feature that moves
    # user files on disk. Default OFF: a deployment must opt in explicitly, and
    # even then apply re-probes each destination directory for writability at run
    # time. The read-only Docker mount is the intended default safety posture, so
    # this stays off unless a writable standalone deployment sets it.
    reorganize_write_enabled: bool = False

    def to_native_path(self, docker_path: str) -> str:
        """Translate a Docker container path to the native host path, if mappings are configured."""
        if self.stl_drive_1 and docker_path.startswith("/mnt/drive1"):
            suffix = docker_path[len("/mnt/drive1"):].replace("/", os.sep)
            return self.stl_drive_1.rstrip("/\\") + suffix
        if self.stl_drive_2 and docker_path.startswith("/mnt/drive2"):
            suffix = docker_path[len("/mnt/drive2"):].replace("/", os.sep)
            return self.stl_drive_2.rstrip("/\\") + suffix
        return docker_path

    def reload(self) -> None:
        """Re-read configuration from the environment / .env file in place (#140).

        Modules import the shared ``settings`` object by reference, so we mutate
        the existing instance rather than rebinding it: a fresh ``Settings()``
        re-reads the sources, then its field values are copied over. Only values
        read dynamically (e.g. drive mappings on the next file-serve) take
        effect live; ``database_url`` is bound once at engine creation and still
        needs a restart — see RESTART_REQUIRED_KEYS.
        """
        fresh = Settings()
        for name in type(self).model_fields:
            setattr(self, name, getattr(fresh, name))

    class Config:
        env_file = ".env"


# Env-level settings that are consumed once at startup and can't be applied by a
# live reload — surfaced to the user so they know a restart is still required.
RESTART_REQUIRED_KEYS = ["database_url"]

settings = Settings()
