# Imagem de produção do ArenaMatch (usada pelo Railway; serve para qualquer host com Docker).
# O Render não usa este arquivo: ele segue o render.yaml (runtime Python nativo).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Arquivos estáticos com hash e comprimidos (o CSS do Tailwind já vem compilado no
# repositório). As duas variáveis só existem para o settings carregar: o
# collectstatic não conecta no banco.
RUN DJANGO_SECRET_KEY=somente-build DATABASE_URL=postgres://build@localhost/build \
    python manage.py collectstatic --no-input

# Roda sem privilégios de root.
RUN useradd --create-home arenamatch && chown -R arenamatch /app
USER arenamatch

# O build não acessa o banco: as migrações rodam ao iniciar (start.sh).
ENV ARENAMATCH_MIGRAR_AO_INICIAR=True
CMD ["bash", "start.sh"]
