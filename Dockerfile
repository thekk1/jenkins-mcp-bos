# mcp-jenkins 3.6.0 mit dem Abgleichwerkzeug job_check_list (bos_list.py). Das Modul liegt neben den
# Werkzeugmodulen des Pakets und wird wie diese am Ende von server/__init__.py importiert.
FROM ghcr.io/lanbaoshen/mcp-jenkins@sha256:ad7a601ed591d34869219861ac3e6ee7cf8646995be2ac75b5687812e9316a74
COPY --chown=appuser:appuser bos_list.py /app/src/mcp_jenkins/server/bos_list.py
RUN echo 'from mcp_jenkins.server import bos_list  # noqa: F401, E402' >> /app/src/mcp_jenkins/server/__init__.py
