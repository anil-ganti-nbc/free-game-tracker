# Container source packaging and entrypoint gate

## COPS-000069 incident

The candidate image for merge commit `5b26bf6a15c66e92ef3fa2551452c56822e6fcc1`
failed before `newsroom` started: `/app/scripts/entrypoint.sh: 5: set: Illegal
option -\r`. The committed `scripts/entrypoint.sh` Git blob was LF, but the
Windows checkout had CRLF. Git for Windows, configured with
`core.autocrlf=true`, then produced a `git archive` whose shell members were
CRLF. The retained archive is reproduced byte for byte by running that archive
command on the merge commit; the transferred and extracted source and failed
image have the same shell-script SHA-256 hashes. Transfer and Docker COPY did
not introduce the conversion.

The prior outbox smoke used `--entrypoint python`, so it never executed the
declared shell entrypoint. Container CI built from GitHub's Linux checkout,
which had LF bytes. Its passing result did not validate the Windows-produced
production archive.

No production activation was completed. COPS-000069 restored the old image,
the verified e102 database backup, and the original FGT cron entry. That
deployment and rollback evidence remains in the COPS-000069 mission.

## Packaging law

Use an immutable, reviewed commit as the source. Do not package a mutable
working tree. Before sending or building a source archive, record the accepted
SHA and verify all production shell bytes against that commit's Git blobs:

```powershell
$acceptedSha = '<reviewed-full-commit-sha>'
git -c core.autocrlf=false archive --format=tar.gz -o source.tar.gz $acceptedSha
python scripts/check_shell_bytes.py --archive source.tar.gz --revision $acceptedSha
```

The `*.sh text eol=lf` attribute pins Unix shell bytes in Windows checkouts
and Git archives. The explicit `core.autocrlf=false` archive command provides
a second safeguard. `check_shell_bytes.py` rejects CRLF and bare CR, and its
revision check compares each shell member to its canonical blob. Verify the
transferred archive's SHA-256 on both ends, then re-run the byte check on the
extracted source before building.

Build with `GIT_REVISION` set to the exact accepted SHA. Check the OCI
`org.opencontainers.image.revision` label and runtime `identity` revision.
Those labels identify the intended commit; they cannot prove that a checkout
or archive preserved executable bytes. The Dockerfile runs the shell-byte
check immediately after `COPY scripts ./scripts` and fails a corrupted build
context instead of repairing it. Run the built image's default `version`,
`identity`, and isolated `init-db` paths without overriding `ENTRYPOINT`.

The container CI first proves on Windows that both the checkout and a Git
archive with `core.autocrlf=true` preserve shell bytes under the new attribute.
It then creates the production archive with `core.autocrlf=false`, verifies
its shell members against the commit, extracts it on Linux, builds from that
extracted tree, and exercises the declared entrypoint. It also proves a
deliberately CRLF-corrupted context is rejected by the Docker build.
