#!/usr/bin/env bash
# Início do serviço web no Render: agendador das rotinas + servidor gunicorn.
#
# No plano gratuito não há "background worker", então o agendador roda no mesmo
# contêiner, em segundo plano. Ele precisa ser único: mantenha 1 instância do
# serviço web. Com plano pago, mova-o para um worker (veja render.yaml).
set -o errexit

if [ "${ARENAMATCH_AGENDADOR_NO_WEB:-True}" = "True" ]; then
  python -u manage.py agendador &
fi

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --access-logfile - \
  --timeout 60
