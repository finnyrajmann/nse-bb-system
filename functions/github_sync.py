"""
GitHub Sync
============
Commits updated data files back to GitHub after each run.
Used by DO Functions to persist positions and trade log.

Files synced:
    - data/positions_bb.csv
    - data/bb_trade_log.csv
"""

import os
from github import Github
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env_nse_bb"))

GITHUB_PAT  = os.getenv("GITHUB_PAT")
GITHUB_REPO = os.getenv("GITHUB_REPO")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES_TO_SYNC = [
    "data/positions_bb.csv",
    "data/bb_trade_log.csv",
]


def sync(commit_message=None):
    if not GITHUB_PAT:
        print("  GitHub sync skipped — no PAT configured")
        return False

    if commit_message is None:
        from datetime import datetime
        commit_message = f"Auto-update data — {datetime.now().strftime('%Y-%m-%d %H:%M IST')}"

    try:
        from github import Auth
        g    = Github(auth=Auth.Token(GITHUB_PAT))
        repo = g.get_repo(GITHUB_REPO)

        for relative_path in FILES_TO_SYNC:
            local_path = os.path.join(BASE_DIR, relative_path)

            if not os.path.exists(local_path):
                print(f"  Skipping {relative_path} — file not found locally")
                continue

            with open(local_path, 'r') as f:
                new_content = f.read()

            try:
                # File exists on GitHub — update it
                gh_file = repo.get_contents(relative_path)
                if gh_file.decoded_content.decode('utf-8') == new_content:
                    print(f"  {relative_path} — no changes, skipping")
                    continue
                repo.update_file(
                    path=relative_path,
                    message=commit_message,
                    content=new_content,
                    sha=gh_file.sha
                )
                print(f"  Updated {relative_path} on GitHub")

            except Exception:
                # File doesn't exist on GitHub yet — create it
                repo.create_file(
                    path=relative_path,
                    message=commit_message,
                    content=new_content
                )
                print(f"  Created {relative_path} on GitHub")

        return True

    except Exception as e:
        print(f"  GitHub sync failed: {str(e)}")
        return False


if __name__ == "__main__":
    print("\nGitHub Sync — testing connection...")
    result = sync("Test sync from local")
    print(f"  Result: {'Success' if result else 'Failed'}\n")
