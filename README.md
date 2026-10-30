# jenkins-mcp-bos

[mcp-jenkins](https://github.com/lanbaoshen/mcp-jenkins) 3.6.0 with an additional tool `job_check_list`:
checks a whole list of job names against all items of all folders in one call (`bos_list.py`).

The image is derived from the upstream image (pinned by digest, see `Dockerfile`); `bos_list.py` is copied
next to the tool modules of the package and imported at the end of `server/__init__.py`.

```bash
docker build -t jenkins-mcp-bos .
```
