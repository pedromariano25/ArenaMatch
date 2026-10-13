"""Filtros e tags de apresentação da vitrine web (Tailwind CSS)."""

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote, urlencode

from django import template
from django.conf import settings
from django.forms import BoundField
from django.utils import timezone
from django.utils.dateformat import format as formatar_data
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe
from django.utils.text import capfirst

from ..formatacao import apenas_digitos, formatar_brl, formatar_cnpj
from ..models import OpenMatch

register = template.Library()

_CLASSES_CAMPO = (
    "block w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-900 shadow-sm "
    "placeholder:text-slate-400 focus:border-emerald-600 focus:outline-none "
    "focus:ring-2 focus:ring-emerald-600/20"
)

_CLASSES_NIVEL = {
    "iniciante": "bg-sky-50 text-sky-700 ring-sky-200",
    "misto": "bg-violet-50 text-violet-700 ring-violet-200",
    "avancado": "bg-rose-50 text-rose-700 ring-rose-200",
}

_CLASSES_PAGAMENTO = {
    "pago": "bg-emerald-50 text-emerald-700 ring-emerald-200",
    "pendente": "bg-amber-50 text-amber-700 ring-amber-200",
    "reembolsado": "bg-slate-100 text-slate-600 ring-slate-200",
}

# Marca (ponto) que identifica o tipo de piso ao lado do rótulo.
_COR_PISO = {
    "sintetico": "bg-emerald-600",
    "salao": "bg-sky-600",
    "areia": "bg-amber-500",
    "campo": "bg-lime-700",
}

# Ícones no estilo Heroicons (outline, 24x24).
_ICONES = {
    "bola": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="m12 7.6 3.1 2.3-1.2 3.7h-3.8L8.9 9.9 12 7.6Z" fill="currentColor"/>'
        '<path d="M12 3v4.6m3.1 2.3 4.4-1.5M13.9 13.6l2.8 3.8m-6.6-3.8-2.8 3.8M8.9 9.9 4.5 8.4"/>'
    ),
    "pin": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/>'
        '<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 '
        '11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z"/>'
    ),
    "calendario": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 '
        "18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 "
        "0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 "
        '0 1 21 11.25v7.5"/>'
    ),
    "relogio": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 '
        '9 9 0 0 1 18 0Z"/>'
    ),
    "jogadores": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 0 0 '
        "2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113"
        "-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374"
        "-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 "
        '3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z"/>'
    ),
    "check": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 '
        '9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>'
    ),
    "voltar": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18"/>'
    ),
    "seta": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3"/>'
    ),
    "filtro": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 '
        "1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 "
        "0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75\"/>"
    ),
    "conversa": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 '
        ".375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 "
        "0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 "
        "9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 "
        "0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 "
        '9-8.25s9 3.694 9 8.25Z"/>'
    ),
    "ticket": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M16.5 6v.75m0 3v.75m0 3v.75m0 3V18m-9'
        "-5.25h5.25M7.5 15h3M3.375 5.25c-.621 0-1.125.504-1.125 1.125v3.026a2.999 2.999 0 0 1 0 "
        "5.198v3.026c0 .621.504 1.125 1.125 1.125h17.25c.621 0 1.125-.504 1.125-1.125v-3.026a2.999 "
        '2.999 0 0 1 0-5.198V6.375c0-.621-.504-1.125-1.125-1.125H3.375Z"/>'
    ),
    "raio": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 '
        '21.75 12 13.5H3.75Z"/>'
    ),
    "escudo": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 '
        "11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 "
        '9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z"/>'
    ),
    "info": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 '
        "1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9"
        '-3.75h.008v.008H12V8.25Z"/>'
    ),
    "alerta": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 '
        "3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 "
        '0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/>'
    ),
    "x": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="m9.75 9.75 4.5 4.5m0-4.5-4.5 4.5M21 '
        '12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>'
    ),
    "painel": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 '
        "2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 "
        "2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 "
        "3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 "
        "18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 "
        '1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z"/>'
    ),
    "dinheiro": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 '
        "2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621"
        ".504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 "
        "1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 "
        "0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 "
        '1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z"/>'
    ),
    "engrenagem": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c'
        ".55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 "
        "1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c"
        "-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534"
        ".955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 "
        "6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019"
        "-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257"
        "-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004"
        "-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 "
        "1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072"
        "-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z\"/>"
        '<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/>'
    ),
    "sair": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 '
        "2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 "
        '3H9"/>'
    ),
    "menu": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"/>'
    ),
    "anterior": '<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5"/>',
    "proximo": '<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"/>',
    "mais": '<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15"/>',
    "externo": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 '
        "2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25\"/>"
    ),
    "tendencia": (
        '<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18 9 11.25l4.306 4.306a11.95 11.95 0 0 '
        '1 5.814-5.518l2.74-1.22m0 0-5.94-2.281m5.94 2.28-2.28 5.941"/>'
    ),
}

# Agenda do gestor: bloco (fundo claro + barra de identidade), selo e marca de legenda.
# As cores de identidade (azul, âmbar, verde) foram validadas para daltonismo; o
# rótulo de texto sempre acompanha a cor.
_CLASSES_BLOCO_CELULA = {
    "mensalista": "border-blue-600 bg-blue-50",
    "avulso": "border-amber-500 bg-amber-50",
    "partida": "border-emerald-600 bg-emerald-50",
    "lotada": "border-emerald-600 bg-emerald-50",
    "bloqueado": "border-slate-400 bg-slate-100",
}
_CLASSES_SELO_CELULA = {
    "mensalista": "bg-blue-100 text-blue-800",
    "avulso": "bg-amber-100 text-amber-800",
    "partida": "bg-emerald-100 text-emerald-800",
    "lotada": "bg-emerald-100 text-emerald-800",
    "bloqueado": "bg-slate-200 text-slate-700",
    "vago": "bg-gray-100 text-gray-800",
}
_COR_MARCA_CELULA = {
    "mensalista": "bg-blue-600",
    "avulso": "bg-amber-500",
    "partida": "bg-emerald-600",
    "lotada": "bg-emerald-600",
    "bloqueado": "bg-slate-400",
    "vago": "bg-gray-300",
}


@register.simple_tag
def icone(nome: str, classes: str = "size-5") -> SafeString:
    """Renderiza um ícone SVG inline (os traços vêm de constantes deste módulo)."""
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" '
        'stroke-width="1.8" stroke="currentColor" class="{}" aria-hidden="true">{}</svg>',
        classes,
        mark_safe(_ICONES[nome]),
    )


@register.filter
def brl(valor: Decimal | int | float | None) -> str:
    """Formata como moeda brasileira."""
    return formatar_brl(valor)


@register.filter
def cnpj(valor: str) -> str:
    """Aplica a máscara de CNPJ."""
    return formatar_cnpj(valor)


@register.filter
def rotulo_dia(dia: date) -> str:
    """``Hoje``, ``Amanhã`` ou o dia da semana (ex.: ``Quinta-feira``)."""
    hoje = timezone.localdate()
    if dia == hoje:
        return "Hoje"
    if dia == hoje + timedelta(days=1):
        return "Amanhã"
    return capfirst(formatar_data(dia, "l"))


@register.filter
def local_resumido(endereco: str) -> str:
    """Bairro e cidade de um endereço no formato ``Rua, nº – Bairro, Cidade – UF``."""
    partes = endereco.split(" – ", 1)
    return partes[1] if len(partes) == 2 else endereco


@register.filter
def link_maps(endereco: str) -> str:
    """Link de busca do endereço no Google Maps."""
    return "https://www.google.com/maps/search/?api=1&query=" + quote(endereco)


@register.filter
def link_whatsapp(telefone: str) -> str:
    """Link ``wa.me`` para um telefone brasileiro."""
    digitos = apenas_digitos(telefone)
    return f"https://wa.me/{digitos if digitos.startswith('55') else '55' + digitos}"


@register.filter
def classes_nivel(nivel: str) -> str:
    return _CLASSES_NIVEL.get(nivel, _CLASSES_NIVEL["misto"])


@register.filter
def classes_pagamento(status: str) -> str:
    return _CLASSES_PAGAMENTO.get(status, _CLASSES_PAGAMENTO["reembolsado"])


@register.filter
def cor_piso(piso: str) -> str:
    """Cor do ponto que identifica o tipo de piso."""
    return _COR_PISO.get(piso, _COR_PISO["sintetico"])


@register.filter
def classes_bloco(tipo: str) -> str:
    """Fundo e barra de identidade de uma faixa ocupada da agenda."""
    return _CLASSES_BLOCO_CELULA.get(tipo, _CLASSES_BLOCO_CELULA["bloqueado"])


@register.filter
def classes_selo(tipo: str) -> str:
    """Selo (badge) de uma faixa da agenda."""
    return _CLASSES_SELO_CELULA.get(tipo, _CLASSES_SELO_CELULA["vago"])


@register.filter
def cor_marca(tipo: str) -> str:
    """Cor da marca de identidade usada na legenda da agenda."""
    return _COR_MARCA_CELULA.get(tipo, _COR_MARCA_CELULA["vago"])


@register.filter
def estilizar(campo: BoundField) -> SafeString:
    """Renderiza o widget do formulário no estilo do produto (vitrine e portal)."""
    borda = "border-red-400" if campo.errors else "border-slate-300"
    return campo.as_widget(attrs={"class": f"{_CLASSES_CAMPO} {borda}"})


@register.simple_tag
def link_google_agenda(partida: OpenMatch) -> str:
    """Link que abre o Google Agenda com o evento da partida já preenchido."""
    horario = partida.time_slot
    arena = horario.court.arena
    formato = "%Y%m%dT%H%M%S"
    inicio = timezone.localtime(horario.inicio).strftime(formato)
    fim = timezone.localtime(horario.fim).strftime(formato)
    parametros = {
        "action": "TEMPLATE",
        "text": f"Futebol · {arena.nome}",
        "dates": f"{inicio}/{fim}",
        "location": arena.endereco_completo,
        "details": (
            f"{horario.court.nome_ou_numero} · Nível {partida.get_nivel_competitividade_display()}. "
            "Reserva feita pelo ArenaMatch."
        ),
        "ctz": settings.TIME_ZONE,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(parametros)
