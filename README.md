# Playlist Builder

Utilidad interactiva para escanear una discoteca organizada por carpetas, filtrar por artista,
género y año, y generar una playlist M3U equilibrada. Requiere Python 3.12 o posterior y está
diseñada para Windows 11, Linux y macOS.

## Formatos y compatibilidad

Los formatos soportados son:

- MP3
- FLAC
- M4A y MP4
- OGG Vorbis
- Opus
- APE

WAV, WMA, AIFF y AIF no están soportados. Se omiten durante el escaneo y no aparecen como errores
de auditoría. Esta limitación es intencionada: sus modelos de metadatos varían entre contenedores y
aplicaciones y no se garantiza una lectura coherente de `Artist`, `Genre` y `Year`.

`mutagen` lee los metadatos sin herramientas externas. Un archivo individual corrupto, inaccesible
o con metadatos inesperados se registra y se omite sin cancelar el resto del escaneo.

Los archivos M3U se generan como Extended M3U en UTF-8, con saltos LF y separadores `/`. Las etiquetas
de texto se limpian de controles que podrían romper la estructura. Sin `--copy`, las rutas son
relativas a la discoteca original. Con `--copy`, todas las entradas apuntan a las nuevas copias bajo
`Music/<ruta relativa original>`; la playlist no conserva rutas a los originales.

## Instalación

### Windows 11, PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Linux o macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Configuración

Edite `playlist_builder/config.py` y establezca la raíz de la discoteca:

```python
MUSIC_ROOT = Path(r"D:\MiDiscoteca")
```

El margen usado cuando solo se introduce uno de los años se configura con:

```python
DEFAULT_YEAR_MARGIN = 5
```

## Uso

```bash
python crear_playlist.py
python crear_playlist.py --size 4000
python crear_playlist.py --size 4000 --max-album 1
python crear_playlist.py --audit simple
python crear_playlist.py --audit full --audit-only
python crear_playlist.py --copy "D:\Musica para el coche"
python crear_playlist.py --size 8000 --seed 12345
```

Tras instalar el proyecto también puede ejecutarse:

```bash
crear-playlist --size 4000
```

Parámetros principales:

- `--size N`: límite en MB decimales. Vale 8000 por defecto y solo acepta números finitos positivos.
- `--max-album N`: máximo de canciones de una misma carpeta de álbum. Vale 2 por defecto.
- `--copy RUTA`: crea una copia autocontenida y una playlist que apunta exclusivamente a ella.
- `--audit simple|full`: muestra el resumen o el detalle de tags ausentes y errores.
- `--audit-only`: audita y termina sin abrir la interfaz.
- `--seed N`: permite repetir la misma selección si catálogo y filtros no han cambiado.
- `--rescan`: descarta la caché y vuelve a leer todos los metadatos.
- `--verbose` y `--debug`: aumentan el detalle de diagnóstico.

## Interfaz

La interfaz conserva el estado al volver entre pantallas y muestra siempre las acciones disponibles.

En artistas y géneros:

- `+` inicia una inclusión y `-` una exclusión.
- La búsqueda ignora mayúsculas, acentos, equivalencias Unicode y espacios repetidos.
- Puede buscar por cualquier fragmento del nombre.
- La barra inferior muestra la primera coincidencia y el número total de resultados.
- `Tab` y `Shift+Tab` recorren las coincidencias.
- `Enter` confirma la coincidencia actual; vacío pasa a la siguiente pantalla.
- `Esc` borra la búsqueda parcial y, estando vacío, vuelve a la pantalla anterior.
- `Backspace` borra texto y, estando vacío, deshace la última selección.
- Las inclusiones aparecen en verde y las exclusiones en rojo.
- Las entradas inválidas muestran feedback inmediato sin abandonar el campo.

Las inclusiones de una categoría se combinan con OR. Artista, género y año se combinan con AND. Las
exclusiones siempre prevalecen. Una canción sin tag puede participar cuando no exista una inclusión
positiva para ese tag; una canción sin año queda fuera si se aplica un filtro temporal.

## Selección equilibrada

Las canciones candidatas se agrupan por carpeta de álbum. El programa baraja álbumes y canciones y
selecciona por rondas, como máximo una pista por álbum en cada ronda, hasta agotar candidatas o el
límite de tamaño. Nunca supera `--max-album` ni `--size`, y continúa probando canciones pequeñas si
una canción grande no cabe.

## Caché

La caché `.playlist_catalog.json` utiliza rutas relativas, tamaño y `mtime_ns`. Incluye un SHA-256 del
contenido canónico. Si el archivo se modifica manualmente o queda dañado, se descarta entero y se
reconstruye. La caché es una optimización: un fallo al leerla o escribirla no debe impedir crear la
playlist.

## Copia y cancelación seguras

Con `--copy`, las canciones se preparan primero en un directorio temporal y se publican después bajo
`Music/`. El M3U se escribe al final. Un error o `Ctrl+C` retira las canciones publicadas por esa
ejecución y elimina sus temporales. Los archivos preexistentes no se borran. Las copias idénticas se
reutilizan y las colisiones con contenido distinto reciben un sufijo incremental.

## Auditoría

`simple` muestra totales de archivos, tags ausentes y errores. `full` añade la ruta y el error concreto.
Los fallos se aíslan por archivo o directorio: siempre que el sistema operativo permita continuar el
recorrido, un problema no invalida el trabajo ya realizado sobre el resto de la colección.

## Pruebas y calidad

```bash
pytest
ruff check .
ruff format --check .
mypy playlist_builder
```

Los tests cubren normalización, años, filtros, selección equilibrada, tamaño, máximo por álbum,
semillas, M3U, rutas de copia, limpieza de metadatos, integridad de caché, errores aislados,
colisiones y rollback ante fallos o interrupciones.
