Fixtures for `scripts/validate-server-json.sh`, exercised by
`tests/test_validate_server_json.py`. Each test copies one file here to
`server.json` in a throwaway git repository whose latest `v[0-9]*` tag is
`v1.2.3` and whose HEAD also carries an `agent-v9.9.9` tag.

`valid.json` is the positive control: the real `server.json` at version 1.2.3.
Every other file applies exactly one forbidden change to it, named by its file
name, and the validator must exit non-zero for it.
