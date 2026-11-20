# jenkins-mcp-bos

[mcp-jenkins](https://github.com/lanbaoshen/mcp-jenkins) 3.6.0 with additional tools:

- `job_check_list` (`bos_list.py`): checks a whole list of job names against all items of all folders in one call.
- `list_builds` (`bos_builds.py`): the builds of all jobs that started in a period, with result and who or what
  started them; `started_by: "me"` filters on the account the request runs as.

The image is derived from the upstream image (pinned by digest, see `Dockerfile`); the `bos_*.py` modules are
copied next to the tool modules of the package and imported at the end of `server/__init__.py`.

```bash
docker build -t jenkins-mcp-bos .
```
