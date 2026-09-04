"""Publish web/ as a public Hugging Face Space."""
from pathlib import Path

from huggingface_hub import HfApi, whoami

SPACE = f"{whoami()['name']}/ky-podcast-soz-kuchu"
FOLDER = Path(__file__).resolve().parent / "web"


def main() -> None:
    api = HfApi()
    api.create_repo(
        SPACE,
        repo_type="space",
        space_sdk="static",
        exist_ok=True,
        private=False,
    )
    api.upload_folder(
        folder_path=str(FOLDER),
        repo_id=SPACE,
        repo_type="space",
        ignore_patterns=[".git", ".DS_Store"],
    )
    print(f"https://huggingface.co/spaces/{SPACE}")


if __name__ == "__main__":
    main()
