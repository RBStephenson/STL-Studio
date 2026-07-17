from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _job_block(workflow: str, job_name: str) -> str:
    lines = workflow.splitlines()
    job_header = f"  {job_name}:"
    start = lines.index(job_header)
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  ")
            and not lines[index].startswith("    ")
            and lines[index].endswith(":")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_main_build_release_job_grants_attestation_permissions() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/main-build.yml").read_text(
        encoding="utf-8"
    )

    build_job = _job_block(workflow, "build")

    assert "release: true" in build_job
    assert "contents: write" in build_job
    assert "id-token: write" in build_job
    assert "attestations: write" in build_job
