/// Endereço da API Django. Troque na hora de rodar, sem mexer no código:
///
///     flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/   (emulador Android)
///     flutter run --dart-define=API_URL=http://127.0.0.1:8000/api/  (simulador iOS)
const apiUrl = String.fromEnvironment('API_URL', defaultValue: 'https://arenamatch-production.up.railway.app/api/');

/// Pelada de grupo: taxa da plataforma sobre o valor do organizador (TAXA_C2C_* no Django).
/// Usada só na prévia do preço; o valor cobrado vem sempre da API.
const taxaPeladaPercentual = 20;
const taxaPeladaMinima = 5.0;
