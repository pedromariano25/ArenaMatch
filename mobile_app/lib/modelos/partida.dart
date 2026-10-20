import 'leitura.dart';

/// Partida do feed: de uma arena parceira ou pelada de grupo (C2C).
class Partida {
  const Partida({
    required this.id,
    required this.origem,
    required this.titulo,
    required this.organizador,
    required this.arena,
    required this.endereco,
    required this.quadra,
    required this.piso,
    required this.data,
    required this.horaInicio,
    required this.horaFim,
    required this.nivel,
    required this.nivelDisplay,
    required this.vagasTotais,
    required this.vagasGoleiro,
    required this.vagasDisponiveis,
    required this.precoPix,
    required this.precoCartao,
    required this.precoGoleiro,
    required this.confirmados,
    required this.status,
    required this.aceitaInscricoes,
  });

  final String id;

  /// "arena" (arena parceira) ou "pelada" (pelada de grupo).
  final String origem;
  final String titulo;

  /// Nome público de quem organiza (só na pelada de grupo).
  final String? organizador;
  final String arena;
  final String endereco;
  final String quadra;
  final String piso;
  final DateTime data;

  /// "19:00"
  final String horaInicio;
  final String horaFim;
  final String nivel;
  final String nivelDisplay;
  final int vagasTotais;
  final int vagasGoleiro;
  final int vagasDisponiveis;
  final double precoPix;
  final double precoCartao;
  final double precoGoleiro;
  final int confirmados;

  /// "aberta", "lotada", "encerrada" ou "cancelada".
  final String status;
  final bool aceitaInscricoes;

  bool get peladaDeGrupo => origem == 'pelada';
  bool get lotada => status == 'lotada' || vagasDisponiveis == 0;

  /// Nome mostrado no cartão: o título da pelada ou o nome da arena.
  String get nome => peladaDeGrupo && titulo.isNotEmpty ? titulo : arena;

  factory Partida.fromJson(Json json) {
    final arena = objeto(json['arena']);
    final quadra = objeto(json['quadra']);
    final precos = objeto(json['precos']);
    return Partida(
      id: texto(json['id']),
      origem: texto(json['origem']).isEmpty ? 'arena' : texto(json['origem']),
      titulo: texto(json['titulo']),
      organizador: json['organizador'] as String?,
      arena: texto(arena['nome']),
      endereco: texto(arena['endereco_completo']),
      quadra: texto(quadra['nome_ou_numero']),
      piso: texto(quadra['tipo_piso_display']),
      data: DateTime.parse(texto(json['data'])),
      horaInicio: texto(json['hora_inicio']),
      horaFim: texto(json['hora_fim']),
      nivel: texto(json['nivel_competitividade']),
      nivelDisplay: texto(json['nivel_display']),
      vagasTotais: inteiro(json['vagas_totais']),
      vagasGoleiro: inteiro(json['vagas_goleiro']),
      vagasDisponiveis: inteiro(json['vagas_disponiveis']),
      precoPix: dinheiro(precos['linha_pix']),
      precoCartao: dinheiro(precos['linha_cartao']),
      precoGoleiro: dinheiro(precos['goleiro']),
      confirmados: inteiro(json['jogadores_confirmados']),
      status: texto(json['status']),
      aceitaInscricoes: json['aceita_inscricoes'] == true,
    );
  }
}

/// Pelada de grupo vista por quem organiza: o que já entrou e se ainda dá para cancelar.
class PeladaDoOrganizador {
  const PeladaDoOrganizador({
    required this.partida,
    required this.recebePorVaga,
    required this.arrecadado,
    required this.emPagamento,
    required this.podeCancelar,
  });

  final Partida partida;
  final double recebePorVaga;
  final double arrecadado;
  final int emPagamento;
  final bool podeCancelar;

  factory PeladaDoOrganizador.fromJson(Json json) => PeladaDoOrganizador(
    partida: Partida.fromJson(json),
    recebePorVaga: dinheiro(json['recebe_por_vaga']),
    arrecadado: dinheiro(json['arrecadado']),
    emPagamento: inteiro(json['em_pagamento']),
    podeCancelar: json['pode_cancelar'] == true,
  );
}
