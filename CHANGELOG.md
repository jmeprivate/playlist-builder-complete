# Changelog

Todos los cambios relevantes de este proyecto se documentarán en este archivo.

El formato se inspira en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el proyecto sigue versionado semántico.

## [1.0.0] - 2026-08-04

Primera versión estable de Playlist Builder.

### Añadido

- Generación interactiva de playlists M3U UTF-8 para colecciones musicales locales.
- Filtros independientes por artista de pista, artista de álbum, género y año.
- Intervalo simétrico `Y ± default_year_margin` cuando se introduce un único año.
- Selección equilibrada por álbum, límite de tamaño, cuota opcional por artista y semillas reproducibles.
- Perfiles de filtros reutilizables en JSON con escritura atómica y precedencia `CLI > perfil > INI`.
- Inclusión y exclusión de candidatas mediante playlists M3U/M3U8 existentes.
- Alias manuales de género configurables sin modificar las etiquetas originales.
- Deduplicación opcional por contenido mediante SHA-256, limitada a colisiones de tamaño y cacheada durante la ejecución.
- Vista previa completa o abreviada, rehacer selección y modo sorpresa.
- Copia autocontenida en estructura plana numerada o conservando el árbol original.
- Marcador persistente para evitar reescanear exportaciones creadas por la aplicación.
- Auditoría simple y completa de metadatos, archivos ilegibles y directorios inaccesibles.
- Progreso de escaneo en terminal y configuración multiplataforma mediante `config.ini`.

### Seguridad y fiabilidad

- Caché versionada, validada mediante SHA-256 y firma de configuración.
- Escaneo tolerante a errores por archivo y directorio, con reintentos configurables.
- Escrituras atómicas y rollback de copias ante errores o interrupciones.
- Validación estricta de configuración, perfiles, nombres, rutas y tamaños.
- Ninguna operación de deduplicación modifica, elimina, enlaza o renombra los archivos originales.

### Compatibilidad

- Python 3.12 o posterior.
- Windows 11, macOS y Linux.
- MP3, FLAC, M4A/MP4, OGG Vorbis, Opus y APE.
