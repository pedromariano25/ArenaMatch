#!/usr/bin/env bash
# Build do Render (e de qualquer servidor Linux): dependências, CSS, estáticos e banco.
set -o errexit

pip install -r requirements.txt

# Recompila o CSS com o Tailwind (executável oficial, conferido por SHA-256).
# Se o download falhar, segue com o arquivo versionado em arena/static.
python manage.py compilar_css || echo "Aviso: Tailwind indisponível; usando o CSS versionado."

python manage.py collectstatic --no-input
python manage.py migrate

# Demonstração: popula o banco só se ele estiver vazio (nunca apaga dados existentes).
if [ "${ARENAMATCH_POPULAR_DEMO:-False}" = "True" ]; then
  python manage.py populate_db --se-vazio
fi
