Modify the files under `fixtures` so the workspace has exactly these outcomes:

1. Discover the existing `.txt` fixtures and locate the file containing
   `ROSETTA_EDIT_TARGET`.
2. Inspect the relevant files before editing them.
3. In `fixtures/alpha.txt`, replace the complete line `status=original` with
   `status=edited`.
4. In `fixtures/beta.txt`, replace the complete line `status=unchanged` with
   `status=patched`.
5. Create `fixtures/created.txt` with exact content `CREATED_BY_WRITE` followed
   by one newline.

Choose the available file discovery, search, read, and edit tools appropriate
to the active protocol. Do not use shell commands or Python to inspect or
modify the files. Do not change any other file.

If every required workspace outcome is satisfied, reply with only
`RESULT:FILE_EDIT_OK`. Otherwise reply with only `RESULT:FILE_EDIT_FAILED`.
