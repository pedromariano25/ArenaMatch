#!/usr/bin/env bash
# Início do serviço web em produção (Render, Railway ou Docker): migrações (quando
# pedidas), agendador das rotinas e servidor gunicorn.
#
# No Render, as migrações rodam no build.sh. Com o Dockerfile (Railway), o build não
# acessa o banco, então elas rodam aqui (ARENAMATCH_MIGRAR_AO_INICIAR=True).
#
# O agendador precisa ser único: mantenha 1 instância do serviço web. Com um worker
# próprio para ele (plano pago), defina ARENAMATCH_AGENDADOR_NO_WEB=False.
set -o errexit

if [ "${ARENAMATCH_MIGRAR_AO_INICIAR:-False}" = "True" ]; then
  python manage.py migrate --no-input
  # Demonstração: popula só um banco vazio (nunca apaga dados). Uma falha aqui não
  # derruba o site.
  if [ "${ARENAMATCH_POPULAR_DEMO:-False}" = "True" ]; then
    python manage.py populate_db --se-vazio || echo "Aviso: a demonstração não foi criada."
  fi
fi

if [ "${ARENAMATCH_AGENDADOR_NO_WEB:-True}" = "True" ]; then
  python -u manage.py agendador &
fi

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --access-logfile - \
  --timeout 60
