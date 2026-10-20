import 'leitura.dart';

/// Usuário autenticado (/api/me/) com o perfil esportivo, se já respondeu o questionário.
class Usuario {
  const Usuario({
    required this.id,
    required this.nome,
    required this.telefone,
    required this.jogador,
    required this.nivel,
    required this.nivelDisplay,
    required this.posicao,
  });

  final int id;
  final String nome;
  final String telefone;
  final bool jogador;

  /// Nível de 1 a 5 (nulo enquanto o questionário não for respondido).
  final int? nivel;
  final String nivelDisplay;
  final String posicao;

  bool get temPerfil => nivel != null;

  String get iniciais {
    final partes = nome.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
    if (partes.isEmpty) return '?';
    final primeira = partes.first[0];
    return partes.length > 1 ? '$primeira${partes.last[0]}'.toUpperCase() : primeira.toUpperCase();
  }

  factory Usuario.fromJson(Json json) {
    final perfil = json['perfil'] is Map<String, dynamic> ? objeto(json['perfil']) : null;
    final nome = '${texto(json['first_name'])} ${texto(json['last_name'])}'.trim();
    return Usuario(
      id: inteiro(json['id']),
      nome: nome.isEmpty ? texto(json['username']) : nome,
      telefone: texto(json['telefone']),
      jogador: json['is_player'] == true,
      nivel: perfil == null ? null : inteiro(perfil['nivel']),
      nivelDisplay: perfil == null ? '' : texto(perfil['nivel_display']),
      posicao: perfil == null ? '' : texto(perfil['posicao']),
    );
  }
}

/// Quadra de uma arena parceira, para escolher onde a pelada acontece.
class Quadra {
  const Quadra({required this.id, required this.arena, required this.nome, required this.piso});

  final int id;
  final String arena;
  final String nome;
  final String piso;

  String get rotulo => '$arena · $nome';

  /// Achata a lista de /api/arenas/ (cada arena com as suas quadras).
  static List<Quadra> daListaDeArenas(List<Json> arenas) => [
    for (final arena in arenas)
      for (final quadra in lista(arena['quadras']))
        Quadra(
          id: inteiro(quadra['id']),
          arena: texto(arena['nome']),
          nome: texto(quadra['nome_ou_numero']),
          piso: texto(quadra['tipo_piso_display']),
        ),
  ];
}
