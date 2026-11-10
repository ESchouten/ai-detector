# Translations

`en.po` is extracted from the source by Wuchale; `nl.po`, `de.po`, `fr.po`, `es.po`, `pt.po`, `pl.po`, `tr.po` and `zh.po` hold the translations. `pnpm i18n` updates all nine after text changes, and leaves new entries with an empty `msgstr` to fill in. `pnpm quality` fails while an entry is empty or a placeholder differs. The other files here load the catalogs; [ARCHITECTURE.md](../../ARCHITECTURE.md#languages) explains them and how to write translatable text.

## How to translate

The reader is a dairy farmer, not a technician. Write what a local farm-software company would: short, plain, calm. Do not translate word for word.

- Keep `{0}`, `#`, `<0>…</0>` and `<0/>` exactly; they may move within the sentence. Keep leading and trailing spaces, `…` and `·`.
- A plural entry needs every form of the language: one for Chinese, two for Dutch, German and Turkish (Turkish gives both the same text: “3 kamera”), three for French, Spanish and Portuguese (`one`, `many`, `other`; give `many` the text of `other`), four for Polish (`one`, `few`, `many`, `other`: “1 kamera”, “3 kamery”, “5 kamer”, “1,5 kamery”).
- Use the name a button or page has here whenever a sentence refers to it: "Settings → Storage" is "Instellingen → Opslag".
- Buttons inside Telegram keep Telegram's own names (**Start**).
- Leave product and technical names alone: AI Detector, Telegram, BotFather, Google Gemini, NVIDIA, TensorRT, RTSP, JSON, ZIP, Heartbeat, Webhook and file names.
- Dutch addresses the reader as **je**, German as **Sie**, French as **vous**, Turkish as **siz** ("Tekrar deneyin"). Buttons use the infinitive ("Camera toevoegen", "Kamera hinzufügen", "Ajouter une caméra"); Turkish buttons use the short imperative ("Kamera ekle"). French puts a non-breaking space before `: ; ? !` and inside « ». Turkish adds a suffix to a name after an apostrophe (AI Detector’a, Telegram’ı); never put a suffix on a placeholder, rephrase instead.
- Spanish is European Spanish with **usted** (ordenador, «»); Portuguese is Brazilian Portuguese with **você** (celular, “”). Both use the infinitive on buttons ("Añadir cámara", "Adicionar câmera"). Polish addresses the reader informally, buttons and sentences alike ("Dodaj kamerę", "Spróbuj ponownie"), and avoids gendered past forms; quote a button name and never put a case ending on a placeholder or on AI Detector. Chinese is Simplified Chinese with 你, full-width punctuation and a space between Chinese and Latin text or a placeholder (“连接 Telegram”, “检测器 {0}”).

## Terms

| English                      | Nederlands             | Deutsch                 | Français                  | Türkçe                   |
| ---------------------------- | ---------------------- | ----------------------- | ------------------------- | ------------------------ |
| Recording                    | Opname                 | Aufnahme                | Enregistrement            | Kayıt                    |
| Camera                       | Camera (camera’s)      | Kamera                  | Caméra                    | Kamera                   |
| Detector                     | Detector               | Detektor                | Détecteur                 | Dedektör                 |
| Detection                    | Detectie               | Erkennung               | Détection                 | Algılama                 |
| Preset                       | Voorinstelling         | Voreinstellung          | Préréglage                | Hazır ayar               |
| Monitoring (page, activity)  | Bewaking               | Überwachung             | Surveillance              | İzleme                   |
| Monitoring (state)           | Bewaking actief        | Überwachung aktiv       | Surveillance active       | İzleme etkin             |
| Alert                        | Melding                | Benachrichtigung        | Alerte                    | Bildirim                 |
| Recipient                    | Ontvanger              | Empfänger               | Destinataire              | Alıcı                    |
| AI check                     | AI-controle            | KI-Prüfung              | Vérification par IA       | Yapay zekâ kontrolü      |
| AI connection                | AI-verbinding          | KI-Verbindung           | Connexion IA              | Yapay zekâ bağlantısı    |
| Confirmed / False alarm      | Bevestigd / Vals alarm | Bestätigt / Fehlalarm   | Confirmé / Fausse alerte  | Onaylandı / Yanlış alarm |
| Review                       | Beoordeling            | Bewertung               | Évaluation                | Değerlendirme            |
| Settings                     | Instellingen           | Einstellungen           | Paramètres                | Ayarlar                  |
| Devices                      | Apparaten              | Geräte                  | Appareils                 | Cihazlar                 |
| Storage                      | Opslag                 | Speicher                | Stockage                  | Depolama                 |
| Advanced                     | Geavanceerd            | Erweitert               | Avancé                    | Gelişmiş                 |
| Logs                         | Logboek                | Protokolle              | Journaux                  | Günlükler                |
| Diagnostics                  | Diagnosegegevens       | Diagnosedaten           | Diagnostic                | Tanılama verileri        |
| Set up                       | Instellen              | Einrichten, Einrichtung | Configurer, configuration | Kur, kurulum             |
| Live picture                 | Livebeeld              | Livebild                | Image en direct           | Canlı görüntü            |
| Stream URL                   | Stream-URL             | Stream-URL              | URL du flux               | Yayın URL’si             |
| Login (of a camera)          | Inloggegevens          | Zugangsdaten            | Identifiants              | Giriş bilgileri          |
| Connect (camera)             | Verbinden              | Verbinden               | Connecter                 | Bağla                    |
| Connect (Telegram, a device) | Koppelen               | Verbinden               | Connecter                 | Bağla                    |
| Back up                      | Back-up maken          | Sichern                 | Sauvegarder               | Yedekle                  |
| Confidence                   | Zekerheid              | Sicherheit              | Confiance                 | Güven                    |

| English                     | Español                   | Português                 | Polski                        | 简体中文      |
| --------------------------- | ------------------------- | ------------------------- | ----------------------------- | ------------- |
| Recording                   | Grabación                 | Gravação                  | Nagranie                      | 录像          |
| Camera                      | Cámara                    | Câmera                    | Kamera                        | 摄像头        |
| Detector                    | Detector                  | Detector                  | Detektor                      | 检测器        |
| Detection                   | Detección                 | Detecção                  | Wykrywanie, wykrycie          | 检测          |
| Preset                      | Preajuste                 | Predefinição              | Szablon                       | 预设          |
| Monitoring (page, activity) | Vigilancia                | Monitoramento             | Monitorowanie                 | 监控          |
| Monitoring (state)          | Vigilancia activa         | Monitoramento ativo       | Monitorowanie aktywne         | 监控中        |
| Alert                       | Aviso                     | Alerta                    | Powiadomienie                 | 通知          |
| Recipient                   | Destinatario              | Destinatário              | Odbiorca                      | 接收者        |
| AI check                    | Comprobación con IA       | Verificação por IA        | Weryfikacja AI                | AI 复核       |
| AI connection               | Conexión de IA            | Conexão de IA             | Połączenie AI                 | AI 连接       |
| Confirmed / False alarm     | Confirmado / Falsa alarma | Confirmado / Alarme falso | Potwierdzone / Fałszywy alarm | 已确认 / 误报 |
| Review                      | Revisión                  | Revisão                   | Ocena                         | 审核          |
| Settings                    | Ajustes                   | Configurações             | Ustawienia                    | 设置          |
| Devices                     | Dispositivos              | Dispositivos              | Urządzenia                    | 设备          |
| Storage                     | Almacenamiento            | Armazenamento             | Pamięć                        | 存储          |
| Advanced                    | Avanzado                  | Avançado                  | Zaawansowane                  | 高级          |
| Logs                        | Registros                 | Registros                 | Dzienniki                     | 日志          |
| Diagnostics                 | Datos de diagnóstico      | Dados de diagnóstico      | Dane diagnostyczne            | 诊断信息      |
| Set up                      | Configurar, configuración | Configurar, configuração  | Skonfiguruj, konfiguracja     | 设置          |
| Live picture                | Imagen en directo         | Imagem ao vivo            | Obraz na żywo                 | 实时画面      |
| Stream URL                  | URL de transmisión        | URL da transmissão        | Adres URL strumienia          | 流地址        |
| Login (of a camera)         | Datos de acceso           | Login                     | Dane logowania                | 登录信息      |
| Connect (camera, Telegram)  | Conectar                  | Conectar                  | Połącz                        | 连接          |
| Back up                     | Copia de seguridad        | Fazer backup              | Kopia zapasowa                | 备份          |
| Confidence                  | Confianza                 | Confiança                 | Pewność                       | 置信度        |
