# mcp-jenkins 3.6.0 mit dem Abgleichwerkzeug job_check_list (bos_list.py), list_builds (bos_builds.py, Builds
# eines Zeitraums ueber alle Jobs), get_builds (bos_batch.py, mehrere Builds in einem Aufruf) und list_config_changes
# (bos_config.py, Konfigurationsaenderungen eines Zeitraums). Die Module liegen neben den Werkzeugmodulen des Pakets
# und werden wie diese am Ende von server/__init__.py importiert.
FROM ghcr.io/lanbaoshen/mcp-jenkins@sha256:ad7a601ed591d34869219861ac3e6ee7cf8646995be2ac75b5687812e9316a74
COPY --chown=appuser:appuser bos_list.py bos_builds.py bos_batch.py bos_config.py /app/src/mcp_jenkins/server/
RUN printf '%s\n' 'from mcp_jenkins.server import bos_list  # noqa: F401, E402' \
    'from mcp_jenkins.server import bos_builds  # noqa: F401, E402' \
    'from mcp_jenkins.server import bos_batch  # noqa: F401, E402' \
    'from mcp_jenkins.server import bos_config  # noqa: F401, E402' >> /app/src/mcp_jenkins/server/__init__.py
