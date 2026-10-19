"""Comando ``compilar_css``: gera o CSS do site, do app e do portal com o Tailwind.

Usa o executável oficial do Tailwind CSS (sem Node.js). Na primeira vez, baixa a
versão fixada abaixo do GitHub, confere o SHA-256 publicado no release e guarda
o executável no cache do usuário, fora do projeto.

    python manage.py compilar_css            # gera arena/static/arena/css/arena.css
    python manage.py compilar_css --watch    # recompila a cada mudança nos templates
"""

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

VERSAO_TAILWIND = "4.3.3"
URL_RELEASE = f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{VERSAO_TAILWIND}/"
# Executável e SHA-256 de cada plataforma (do release oficial da versão acima).
EXECUTAVEIS = {
    ("windows", "x64"): (
        "tailwindcss-windows-x64.exe",
        "e0e260ce048014e9268f6237ff18f8ccf02cef521cbd0ae04e82c2cdf7aa3955",
    ),
    ("linux", "x64"): (
        "tailwindcss-linux-x64",
        "dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a",
    ),
    ("linux", "arm64"): (
        "tailwindcss-linux-arm64",
        "55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195",
    ),
    ("macos", "x64"): (
        "tailwindcss-macos-x64",
        "7922e0953f2110c05976e3bf58f14e643d90427575e766b7d433f5f80cbee7e1",
    ),
    ("macos", "arm64"): (
        "tailwindcss-macos-arm64",
        "cdf646702987a743464dff4d9c60fd4480d1c1e73dd819a9a67f1078815dce9d",
    ),
}
ENTRADA = Path(settings.BASE_DIR) / "arena" / "estilos" / "entrada.css"
SAIDA = Path(settings.BASE_DIR) / "arena" / "static" / "arena" / "css" / "arena.css"


def plataforma_atual() -> tuple[str, str]:
    """Sistema e arquitetura no formato dos nomes dos executáveis do Tailwind."""
    sistema = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    maquina = platform.machine().lower()
    arquitetura = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(maquina, maquina)
    return sistema, arquitetura


def pasta_de_cache() -> Path:
    """Cache do usuário (o executável tem ~110 MB e não deve ir para o projeto)."""
    if base := os.environ.get("ARENAMATCH_CACHE_DIR"):
        return Path(base)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "arenamatch"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "arenamatch"


def sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def obter_executavel() -> Path:
    """Caminho do executável do Tailwind, baixando e conferindo o hash se preciso.

    Raises:
        CommandError: plataforma sem executável oficial ou download adulterado.
    """
    plataforma = plataforma_atual()
    if plataforma not in EXECUTAVEIS:
        raise CommandError(f"Sem executável do Tailwind para {plataforma[0]}/{plataforma[1]}.")
    nome, hash_esperado = EXECUTAVEIS[plataforma]
    destino = pasta_de_cache() / f"tailwind-{VERSAO_TAILWIND}" / nome
    if destino.exists() and sha256(destino) == hash_esperado:
        return destino

    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destino.parent, delete=False) as temporario:
        caminho_temporario = Path(temporario.name)
    try:
        urllib.request.urlretrieve(URL_RELEASE + nome, caminho_temporario)
        if sha256(caminho_temporario) != hash_esperado:
            raise CommandError(f"O SHA-256 de {nome} não confere com o release oficial. Download descartado.")
        caminho_temporario.chmod(caminho_temporario.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        caminho_temporario.replace(destino)
    finally:
        caminho_temporario.unlink(missing_ok=True)
    return destino


class Command(BaseCommand):
    help = "Gera o CSS do ArenaMatch com o Tailwind (arena/static/arena/css/arena.css)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--watch", action="store_true", help="Recompila a cada mudança.")

    def handle(self, *args: Any, **options: Any) -> None:
        executavel = obter_executavel()
        self.stdout.write(f"Tailwind {VERSAO_TAILWIND}: {ENTRADA.name} → {SAIDA.relative_to(settings.BASE_DIR)}")
        if options["watch"]:
            self._rodar(executavel, SAIDA, "--watch")
            return
        # O executável do Tailwind às vezes falha ao gravar em pastas sincronizadas (ex.:
        # OneDrive): compila num arquivo temporário e o Python copia para o lugar.
        with tempfile.TemporaryDirectory() as pasta:
            temporario = Path(pasta) / SAIDA.name
            self._rodar(executavel, temporario, "--minify")
            SAIDA.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(temporario, SAIDA)
        self.stdout.write(self.style.SUCCESS(f"CSS gerado ({SAIDA.stat().st_size / 1024:.0f} KB)."))

    @staticmethod
    def _rodar(executavel: Path, saida: Path, modo: str) -> None:
        comando = [str(executavel), "--input", str(ENTRADA), "--output", str(saida), modo]
        # O Tailwind resolve os @source a partir da pasta do arquivo de entrada.
        resultado = subprocess.run(comando, cwd=ENTRADA.parent, check=False)
        if resultado.returncode != 0:
            raise CommandError(f"O Tailwind terminou com erro (código {resultado.returncode}).")
