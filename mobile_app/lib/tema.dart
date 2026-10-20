// Design system do ArenaMatch: claro, ultra-minimalista, uma cor forte só nos CTAs.
//
// Mesmos tokens do site (arena/estilos/entrada.css): fundo gray-50, cartões
// brancos com borda gray-200, texto gray-900 e o verde bandeira nos botões.
import 'package:flutter/material.dart';

abstract final class Cores {
  static const bandeira = Color(0xFF00873A); // bandeira-600: CTA (contraste AA com branco)
  static const bandeiraEscuro = Color(0xFF006F30); // bandeira-700: pressionado e textos verdes
  static const bandeiraClaro = Color(0xFFEAF6EE); // bandeira-50: fundos de confirmação
  static const fundo = Color(0xFFF9FAFB); // gray-50
  static const cartao = Colors.white;
  static const borda = Color(0xFFE5E7EB); // gray-200
  static const bordaForte = Color(0xFFD1D5DB); // gray-300
  static const texto = Color(0xFF111827); // gray-900
  static const textoSecundario = Color(0xFF6B7280); // gray-500
  static const textoApagado = Color(0xFF9CA3AF); // gray-400
  static const erro = Color(0xFFDC2626); // red-600
}

abstract final class Espacos {
  static const tela = 16.0;
  static const raioBotao = 16.0;
  static const raioCartao = 16.0;
  static const raioCampo = 12.0;
}

/// Botões grandes (py-4 px-6, texto 18 em negrito) e cantos de 16.
ThemeData temaArenaMatch() {
  const fonteBotao = TextStyle(fontSize: 18, fontWeight: FontWeight.w700);
  const formaBotao = RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(Espacos.raioBotao)));
  const paddingBotao = EdgeInsets.symmetric(vertical: 16, horizontal: 24);

  final esquema = ColorScheme.fromSeed(
    seedColor: Cores.bandeira,
    primary: Cores.bandeira,
    onPrimary: Colors.white,
    surface: Cores.cartao,
    onSurface: Cores.texto,
    error: Cores.erro,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: esquema);

  return base.copyWith(
    scaffoldBackgroundColor: Cores.fundo,
    textTheme: base.textTheme
        .apply(bodyColor: Cores.texto, displayColor: Cores.texto)
        .copyWith(
          headlineMedium: const TextStyle(
            fontSize: 30,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.75,
            color: Cores.texto,
          ),
          headlineSmall: const TextStyle(
            fontSize: 24,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.6,
            color: Cores.texto,
          ),
          titleLarge: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: Cores.texto),
          bodyLarge: const TextStyle(fontSize: 17, color: Cores.texto),
          bodyMedium: const TextStyle(fontSize: 15, color: Cores.texto),
        ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Cores.cartao,
      foregroundColor: Cores.texto,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Cores.texto),
      shape: Border(bottom: BorderSide(color: Cores.borda)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: Cores.bandeira,
        foregroundColor: Colors.white,
        disabledBackgroundColor: Cores.bandeira.withValues(alpha: 0.4),
        disabledForegroundColor: Colors.white,
        textStyle: fonteBotao,
        padding: paddingBotao,
        minimumSize: const Size(64, 56),
        shape: formaBotao,
        elevation: 0,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: Cores.texto,
        backgroundColor: Cores.cartao,
        side: const BorderSide(color: Cores.bordaForte),
        textStyle: fonteBotao,
        padding: paddingBotao,
        minimumSize: const Size(64, 56),
        shape: formaBotao,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: Cores.textoSecundario,
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Cores.cartao,
      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      hintStyle: TextStyle(color: Cores.textoApagado),
      labelStyle: TextStyle(color: Cores.textoSecundario),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(Espacos.raioCampo)),
        borderSide: BorderSide(color: Cores.bordaForte),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(Espacos.raioCampo)),
        borderSide: BorderSide(color: Cores.bordaForte),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(Espacos.raioCampo)),
        borderSide: BorderSide(color: Cores.texto, width: 1.5),
      ),
    ),
    cardTheme: const CardThemeData(
      color: Cores.cartao,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Espacos.raioCartao)),
        side: BorderSide(color: Cores.borda),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: Cores.cartao,
      selectedColor: Cores.texto,
      side: const BorderSide(color: Cores.borda),
      labelStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Cores.texto),
      secondaryLabelStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white),
      shape: const StadiumBorder(),
      showCheckmark: false,
    ),
    bottomNavigationBarTheme: const BottomNavigationBarThemeData(
      backgroundColor: Cores.cartao,
      selectedItemColor: Cores.texto,
      unselectedItemColor: Cores.textoApagado,
      selectedLabelStyle: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
      unselectedLabelStyle: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
      type: BottomNavigationBarType.fixed,
      elevation: 0,
    ),
    dividerTheme: const DividerThemeData(color: Cores.borda, space: 1, thickness: 1),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: Cores.texto,
      behavior: SnackBarBehavior.floating,
      contentTextStyle: TextStyle(fontSize: 15, color: Colors.white),
    ),
  );
}
