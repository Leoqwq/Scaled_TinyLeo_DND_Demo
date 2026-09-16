# Sharing this project on GitHub

## Repository and branch

A fork is a repository under your own account or organization; a branch is a
line of development within a repository. This project retains TinyLEO's Git
history and attribution while sharing the demo extensions in a team repository.

- [Team repository](https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo)
- [Upstream TinyLEO](https://github.com/TinyLEO-toolkit/TinyLEO)

Locally, `origin` points to the team repository and `upstream` points to TinyLEO.
The team's `main` contains the merged extensions. The retired development branch
was deleted; its commits remain in `main` history.

## Download and view

```sh
git clone --branch main https://github.com/Leoqwq/Scaled_TinyLeo_DND_Demo.git
cd Scaled_TinyLeo_DND_Demo
```

Open [replay.html](../replay.html) in a desktop browser for both Replay and
Compare. Recordings and archives are included in [data/](../data/README.md).
No fork or Google Cloud VM access is needed to view them. Live is currently unavailable.

## Future contributions

Start new work from the team's `main`, commit to a feature branch, and open a
pull request against `Leoqwq/Scaled_TinyLeo_DND_Demo`. Check the target repository
so the request is not accidentally sent upstream. Review `git diff` and
`git diff --cached` before committing. Uncommitted work is not uploaded by push.

Preserve the upstream LICENSE, author attribution, and paper citation. Keep
synthetic fixtures distinct from real experiment results. Ignore rules do not
remove files already stored in Git history; revoke any accidentally committed
credential before addressing its history separately.

Reference: [GitHub's fork remote configuration guide](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/configuring-a-remote-repository-for-a-fork).
