# jenkins-mcp-bos

[mcp-jenkins](https://github.com/lanbaoshen/mcp-jenkins) 3.6.0 with additional tools:

- `job_check_list` (`bos_list.py`): checks a whole list of job names against all items of all folders in one call.
- `list_builds` (`bos_builds.py`): the builds of all jobs that started in a period, with result and who or what
  started them; `started_by: "me"` filters on the account the request runs as.
- `get_builds` (`bos_batch.py`): several builds in one call, with result, start, duration, cause, parameters and
  optionally the end of the console output. Builds of one job come from one `allBuilds{a,b}` request; the console
  has no batch request in Jenkins and is read per build.
- `list_config_changes` (`bos_config.py`): who created, changed, renamed or deleted which job, and changes of the
  system configuration, in a period. One request to `/jobConfigHistory/api/json?filter=all` of the Job Config
  History plugin returns every entry, also of deleted jobs; the tool filters period and account.

The image is derived from the upstream image (pinned by digest, see `Dockerfile`); the `bos_*.py` modules are
copied next to the tool modules of the package and imported at the end of `server/__init__.py`.

```bash
docker build -t jenkins-mcp-bos .
```
