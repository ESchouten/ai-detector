# Translations

`en.po` is extracted from the source by Wuchale; `nl.po`, `de.po`, `fr.po` and `tr.po` hold the translations. `pnpm i18n` updates all five after text changes, and leaves new entries with an empty `msgstr` to fill in. `pnpm quality` fails while an entry is empty or a placeholder differs. The other files here load the catalogs; [ARCHITECTURE.md](../../ARCHITECTURE.md#languages) explains them and how to write translatable text.

## How to translate

The reader is a dairy farmer, not a technician. Write what a local farm-software company would: short, plain, calm. Do not translate word for word.

- Keep `{0}`, `#`, `<0>…</0>` and `<0/>` exactly; they may move within the sentence. Keep leading and trailing spaces, `…` and `·`.
- A plural entry needs every form of the language: two for Dutch, German and Turkish (Turkish gives both the same text: “3 kamera”), three for French (`one`, `many`, `other`; give `many` the text of `other`).
- Use the name a button or page has here whenever a sentence refers to it: "Settings → Storage" is "Instellingen → Opslag".
- Buttons inside Telegram keep Telegram's own names (**Start**).
- Leave product and technical names alone: AI Detector, Telegram, BotFather, Google Gemini, NVIDIA, TensorRT, RTSP, JSON, ZIP, Heartbeat, Webhook and file names.
- Dutch addresses the reader as **je**, German as **Sie**, French as **vous**, Turkish as **siz** ("Tekrar deneyin"). Buttons use the infinitive ("Camera toevoegen", "Kamera hinzufügen", "Ajouter une caméra"); Turkish buttons use the short imperative ("Kamera ekle"). French puts a non-breaking space before `: ; ? !` and inside « ». Turkish adds a suffix to a name after an apostrophe (AI Detector’a, Telegram’ı); never put a suffix on a placeholder, rephrase instead.

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
