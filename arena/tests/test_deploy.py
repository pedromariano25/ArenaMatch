"""Preparação para produção: CSS compilado, download do Tailwind e páginas de erro."""

import hashlib
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from arena.management.commands import compilar_css


class CssCompiladoTest(SimpleTestCase):
    def test_css_versionado_tem_os_componentes(self):
        """O deploy usa o CSS versionado se o Tailwind não puder ser baixado."""
        css = compilar_css.SAIDA.read_text(encoding="utf-8")
        for seletor in (".botao", ".botao-secundario", ".campo", ".cartao", ".titulo", ".selo", ".chip-ativo"):
            self.assertIn(seletor, css)
        self.assertNotIn("@apply", css)


class ExecutavelTailwindTest(SimpleTestCase):
    def test_plataformas_do_render_e_dos_computadores_da_equipe(self):
        casos = {("linux", "x86_64"): ("linux", "x64"), ("win32", "AMD64"): ("windows", "x64"), ("darwin", "arm64"): ("macos", "arm64")}
        for (sistema, maquina), esperado in casos.items():
            with mock.patch.object(compilar_css.sys, "platform", sistema), mock.patch.object(
                compilar_css.platform, "machine", return_value=maquina
            ):
                self.assertEqual(compilar_css.plataforma_atual(), esperado)
                self.assertIn(esperado, compilar_css.EXECUTAVEIS)

    def test_download_com_hash_errado_e_descartado(self):
        def baixar_adulterado(url, destino):
            Path(destino).write_bytes(b"executavel adulterado")

        with tempfile.TemporaryDirectory() as pasta, mock.patch.dict(
            "os.environ", {"ARENAMATCH_CACHE_DIR": pasta}
        ), mock.patch.object(compilar_css.urllib.request, "urlretrieve", side_effect=baixar_adulterado):
            with self.assertRaisesMessage(CommandError, "SHA-256"):
                compilar_css.obter_executavel()
            self.assertEqual([p for p in Path(pasta).rglob("*") if p.is_file()], [])

    def test_executavel_em_cache_com_hash_certo_nao_baixa_de_novo(self):
        conteudo = b"tailwind de mentira"
        nome, _ = compilar_css.EXECUTAVEIS[compilar_css.plataforma_atual()]
        with tempfile.TemporaryDirectory() as pasta, mock.patch.dict(
            "os.environ", {"ARENAMATCH_CACHE_DIR": pasta}
        ), mock.patch.dict(
            compilar_css.EXECUTAVEIS, {compilar_css.plataforma_atual(): (nome, hashlib.sha256(conteudo).hexdigest())}
        ), mock.patch.object(compilar_css.urllib.request, "urlretrieve") as baixar:
            destino = Path(pasta) / f"tailwind-{compilar_css.VERSAO_TAILWIND}" / nome
            destino.parent.mkdir(parents=True)
            destino.write_bytes(conteudo)
            self.assertEqual(compilar_css.obter_executavel(), destino)
            baixar.assert_not_called()


class PaginasDeErroTest(TestCase):
    def test_404_no_visual_do_app(self):
        resposta = self.client.get("/nao-existe/")
        self.assertContains(resposta, "Bola fora", status_code=404)
        self.assertContains(resposta, "arena/css/arena.css", status_code=404)
