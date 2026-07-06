import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:////data/stl_inventory.db"

    # Comma-separated list of container paths to auto-seed as scan roots on
    # first boot.  Set via STL_ROOTS in .env / docker-compose environment.
    # Each entry must correspond to a volume mounted into the container.
    stl_roots: str = "/mnt/drive1,/mnt/drive2"

    # Native (host) paths for the drive mounts — used to translate Docker
    # container paths back to Windows/Mac paths for display.
    # Set STL_DRIVE_1 / STL_DRIVE_2 in your .env to match the host paths
    # mounted at /mnt/drive1 and /mnt/drive2 respectively.
    stl_drive_1: str = ""
    stl_drive_2: str = ""

    # Hostnames trusted by the write-request guard in addition to localhost, for
    # running behind a reverse proxy on a custom domain (e.g. stl.pagden.us).
    # Comma-separated; set via TRUSTED_HOSTS. Writes (POST/PUT/PATCH/DELETE) are
    # allowed when the request's Origin/Host hostname is localhost or one of
    # these. Empty (the default) = localhost-only.
    trusted_hosts: str = ""

    # MyMiniFactory REST API key (simple ?key= query auth). When set, the MMF
    # adapter uses the API for object detail + search and falls back to scraping
    # on miss. Register an app at MMF Settings -> Developer to obtain a key.
    mmf_api_key: str = ""

    # Library reorganize apply (#324, Phase 2a) — the ONLY feature that moves
    # user files on disk. Default OFF: a deployment must opt in explicitly, and
    # even then apply re-probes each destination directory for writability at run
    # time. The read-only Docker mount is the intended default safety posture, so
    # this stays off unless a writable standalone deployment sets it.
    reorganize_write_enabled: bool = False

    @property
    def stl_root_list(self) -> list[str]:
        return [r.strip() for r in self.stl_roots.split(",") if r.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.trusted_hosts.split(",") if h.strip()]

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
