# Translations

`en.po` is extracted from the source by Wuchale; `nl.po`, `de.po` and `fr.po` hold the translations. `pnpm i18n` updates all four after text changes, and leaves new entries with an empty `msgstr` to fill in. `pnpm quality` fails while an entry is empty or a placeholder differs. The other files here load the catalogs; [ARCHITECTURE.md](../../ARCHITECTURE.md#languages) explains them and how to write translatable text.

## How to translate

The reader is a dairy farmer, not a technician. Write what a local farm-software company would: short, plain, calm. Do not translate word for word.

- Keep `{0}`, `#`, `<0>…</0>` and `<0/>` exactly; they may move within the sentence. Keep leading and trailing spaces, `…` and `·`.
- A plural entry needs every form of the language: two for Dutch and German, three for French (`one`, `many`, `other`; give `many` the text of `other`).
- Use the name a button or page has here whenever a sentence refers to it: "Settings → Storage" is "Instellingen → Opslag".
- Buttons inside Telegram keep Telegram's own names (**Start**).
- Leave product and technical names alone: AI Detector, Telegram, BotFather, Google Gemini, Docker, NVIDIA, TensorRT, RTSP, JSON, ZIP, file names, and the presets Cow Catcher and Calving Catcher.
- Dutch addresses the reader as **je**, German as **Sie**, French as **vous**. Buttons use the infinitive ("Camera toevoegen", "Kamera hinzufügen", "Ajouter une caméra"). French puts a non-breaking space before `: ; ? !` and inside « ».

## Terms

| English                      | Nederlands             | Deutsch                 | Français                  |
| ---------------------------- | ---------------------- | ----------------------- | ------------------------- |
| Recording                    | Opname                 | Aufnahme                | Enregistrement            |
| Camera                       | Camera (camera’s)      | Kamera                  | Caméra                    |
| Detector                     | Detector               | Detektor                | Détecteur                 |
| Detection                    | Detectie               | Erkennung               | Détection                 |
| Preset                       | Voorinstelling         | Voreinstellung          | Préréglage                |
| Monitoring (page, activity)  | Bewaking               | Überwachung             | Surveillance              |
| Monitoring (state)           | Bewaking actief        | Überwachung aktiv       | Surveillance active       |
| Alert                        | Melding                | Benachrichtigung        | Alerte                    |
| Recipient                    | Ontvanger              | Empfänger               | Destinataire              |
| Validator                    | AI-controle            | KI-Prüfung              | Vérification par IA       |
| AI connection                | AI-verbinding          | KI-Verbindung           | Connexion IA              |
| Confirmed / False alarm      | Bevestigd / Vals alarm | Bestätigt / Fehlalarm   | Confirmé / Fausse alerte  |
| Review                       | Beoordeling            | Bewertung               | Évaluation                |
| Settings                     | Instellingen           | Einstellungen           | Paramètres                |
| Devices                      | Apparaten              | Geräte                  | Appareils                 |
| Storage                      | Opslag                 | Speicher                | Stockage                  |
| Advanced                     | Geavanceerd            | Erweitert               | Avancé                    |
| Logs                         | Logboek                | Protokolle              | Journaux                  |
| Diagnostics                  | Diagnosegegevens       | Diagnosedaten           | Diagnostic                |
| Set up                       | Instellen              | Einrichten, Einrichtung | Configurer, configuration |
| Live picture                 | Livebeeld              | Livebild                | Image en direct           |
| Stream URL                   | Stream-URL             | Stream-URL              | URL du flux               |
| Login (of a camera)          | Inloggegevens          | Zugangsdaten            | Identifiants              |
| Connect (camera)             | Verbinden              | Verbinden               | Connecter                 |
| Connect (Telegram, a device) | Koppelen               | Verbinden               | Connecter                 |
| Back up                      | Back-up maken          | Sichern                 | Sauvegarder               |
| Confidence                   | Zekerheid              | Sicherheit              | Confiance                 |
