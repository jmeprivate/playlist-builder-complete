# Playlist Builder

Utilidad interactiva para escanear una discoteca organizada por carpetas, filtrar por artista de
pista, artista de álbum, género y año, y generar una playlist M3U equilibrada. Funciona con
Python 3.12 o posterior en macOS, Windows 11 y Linux.

## Decisiones y compatibilidad

- `mutagen` lee los metadatos sin programas externos. Algunos contenedores o variantes poco
  habituales pueden no exponer todas las etiquetas; se registran como ausentes y el escaneo sigue.
- `prompt_toolkit` gestiona teclas especiales, autocompletado, colores y terminales multiplataforma.
- La identidad de un álbum es la carpeta relativa que lo contiene, no el texto de la etiqueta.
- `Artist` representa al artista de la pista. `AlbumArtist` no se mezcla con él (algo esencial en
  recopilatorios cuyo artista de álbum es `Various Artists`). Para ASF/WMA, `Author` se usa solo como
  fallback cuando no existe `Artist`.
- Por ejemplo, una pista de un recopilatorio con `Artist = The Hoffpauir Family` y
  `AlbumArtist = Various Artists` aparece bajo The Hoffpauir Family en «Artistas de pista» y bajo
  Various Artists únicamente en «Artistas de álbum». Ambos filtros se pueden combinar.
- Los valores múltiples de `Genre` separados por comas, punto y coma o valores nativos independientes
  se convierten en géneros separados; por ejemplo, `Jazz, Contemporary Jazz` permite buscar cualquiera.
- La caché versionada `.playlist_catalog.json` se guarda en la raíz musical, nunca guarda rutas
  absolutas y compara cada archivo por ruta, tamaño y `mtime_ns`. Incluye la firma de configuración
  y un digest SHA-256; una versión incompatible, JSON truncado, manipulado o con rutas inseguras se
  invalida por completo: la caché nunca impide escanear.
- Cada escritura se hace mediante un temporal, `fsync` y reemplazo atómico cuando el sistema lo
  permite. Se registra inicio, fin, lectura, estado completo y errores por ruta. Una interrupción
  queda marcada como incompleta y conserva las entradas anteriores; solo un recorrido completo poda
  archivos desaparecidos. Si no hay permisos de escritura, el catálogo en memoria sigue disponible
  y `--verbose` explica el fallo.
- No se usa el `mtime` de directorios como fuente de verdad ni se añade una base de datos: ambos
  complicarían el diseño sin conservar la garantía por archivo en discos externos y sistemas de
  archivos diversos.
- Los M3U usan UTF-8, separadores `/` y saltos de línea LF. Es una combinación entendida por los
  reproductores actuales de los tres sistemas y mantiene portabilidad entre ellos. Los controles que
  podrían inyectar líneas en `#EXTINF` se sustituyen sin eliminar marcas Unicode de formato legítimas.

No existe una incompatibilidad técnica general con los formatos pedidos, aunque la disponibilidad
real de etiquetas depende de que cada archivo las contenga y de que `mutagen` reconozca esa variante.

## Instalación

### macOS o Linux

```bash
cd playlist_builder
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Windows 11 (PowerShell)

```powershell
cd playlist_builder
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Configurar la discoteca

Edite el `config.ini` del proyecto (o el indicado mediante `--config`). Además de la raíz musical y
los valores predeterminados, `retry_error_after_days` controla cuándo se vuelven a leer los archivos
cuyos metadatos fallaron. Un cambio de tamaño/fecha o `--rescan` siempre fuerza el reintento:

```ini
[playlist_builder]
music_root = /Users/usuario/Música/MiDiscoteca
retry_error_after_days = 7
```

## Ejecución

Desde la raíz del proyecto:

```bash
python crear_playlist.py
python crear_playlist.py --size 4000
python crear_playlist.py --size 4000 --max-album 1
python crear_playlist.py --audit simple
python crear_playlist.py --audit full --audit-only
python crear_playlist.py --copy "D:\Musica para el coche"
python crear_playlist.py --size 8000 --seed 12345
python crear_playlist.py --surprise --copy "/media/USB"
```

Después de instalar el proyecto en el entorno virtual, también puede usarse:

```bash
crear-playlist --size 4000
```

En Windows está disponible `crear-playlist.cmd`; en macOS/Linux puede hacerse ejecutable el launcher
opcional con `chmod +x crear-playlist.sh`.

### Parámetros

- `--size N`: máximo en MB decimales (`1 MB = 1_000_000 bytes`); acepta decimales y vale 8000 por
  defecto. El resultado nunca supera el límite.
- `--max-album N`: máximo de canciones por carpeta de álbum; vale 2 por defecto.
- `--copy RUTA`: copia las canciones a `RUTA/Music/` y crea allí el M3U. Por defecto usa nombres
  planos `índice - título (artista).ext`; `copy_structure = tree` conserva el árbol original.
- `--audit simple|full`: muestra el resumen o también el detalle por archivo y continúa hacia la UI.
  `full` se rechaza en modo sorpresa porque revela rutas; use `simple` o `--no-surprise`.
- `--audit-only`: muestra la auditoría (simple si no se especificó otra) y termina.
- `--seed N`: hace reproducible la selección si catálogo y filtros no cambian.
- `--surprise` / `--no-surprise`: activa o desactiva explícitamente el modo sorpresa. La opción CLI
  prevalece sobre `surprise_mode` de `config.ini`.
- `--config RUTA`: usa expresamente ese archivo INI.
- `--rescan`: descarta la caché y relee todos los metadatos.
- `--verbose`: informa sobre caché, lectura y operaciones. Puede revelar rutas y detalles; no se debe
  usar cuando se necesita una sorpresa estricta.
- `--debug`: añade detalles de depuración y deja visibles los tracebacks inesperados.

## Interfaz

En artistas de pista, artistas de álbum y géneros:

- `+` seguido de texto incluye una opción; `-` la excluye.
- La búsqueda encuentra texto en cualquier posición e ignora mayúsculas, acentos, Unicode
  equivalente y espacios repetidos.
- `Tab` y `Shift+Tab` recorren coincidencias. `Enter` acepta la coincidencia exacta o la primera
  sugerida. No admite nombres que no existan en el catálogo.
- `Enter` sobre una línea vacía avanza.
- `Esc` borra la búsqueda parcial; estando vacío, vuelve a la pantalla anterior.
- `Backspace` borra texto y, estando completamente vacío, deshace la última selección confirmada.
- Las inclusiones se muestran en verde y las exclusiones en rojo. Si una opción pasa de un conjunto
  al otro, prevalece la última operación.

Las inclusiones de una misma categoría usan OR: una canción puede coincidir con cualquiera. Artista
de pista, artista de álbum, género y año se combinan con AND. Cualquier exclusión coincidente gana
siempre. Una canción sin tag
puede participar si no hay inclusión positiva para ese tag; sin año queda fuera solo cuando existe
un filtro temporal.

Los años son opcionales e inclusivos. Si se rellena solo un extremo, el otro se calcula con
`DEFAULT_YEAR_MARGIN` y se limita al rango disponible.

Después de fijar los filtros, la aplicación calcula una única selección y muestra su preview antes de
pedir el nombre. La preview abreviada enseña las primeras y últimas cinco entradas (configurables), y
ofrece `[a]ceptar`, `[r]ehacer`, `[v]er completa` y `[c]ancelar`. Rehacer conserva filtros y límites.
Con `--seed`, la selección es reproducible y la interfaz no finge que puede rehacerla al azar: ofrece
volver a filtros o cancelar. La selección aceptada es exactamente la confirmada y escrita.

Las preferencias de preview y copia viven en el mismo `config.ini` que el resto de la configuración:

```ini
[playlist_builder]
surprise_mode = false
preview_entries = 5
copy_structure = flat
retry_error_after_days = 7
```

En un checkout se usa el `config.ini` de la raíz del proyecto. Tras instalar, la plantilla incluida
en el paquete se copia una sola vez a la ubicación de configuración del usuario de Windows, macOS o
Linux. `--config RUTA` permite seleccionar otro archivo de forma explícita.

En modo sorpresa se omiten preview, composición y conteos de selección: se pide directamente el
nombre y solo se presenta un resumen de filtros, límites, destino y el aviso de privacidad. No hay
acción de rehacer. Con `--copy`, incluso si `copy_structure = tree`, la protección tiene prioridad y
se usan rutas planas `Music/1 - Nombre playlist.ext`, conservando Unicode, espacios y la extensión.
Las colisiones reciben el sufijo incremental habitual. El M3U mantiene `#EXTINF` por compatibilidad:
**abrir el archivo M3U sí revela títulos y artistas**.

## Selección equilibrada

Las candidatas se agrupan por carpeta de álbum. Las canciones y álbumes se barajan y la selección
avanza por rondas, como máximo una canción por álbum y ronda. Se respeta `--max-album`; si una pista
no cabe se siguen probando pistas más pequeñas. Esto evita depender del orden del sistema de archivos
y no favorece sistemáticamente los primeros artistas.

## Copia segura

Con `--copy`, primero se copian todas las pistas a una zona temporal mediante `shutil.copy2`. Solo
después se publican en `Music/`, y el M3U se publica el último. Ante un fallo o `Ctrl+C` se retiran
exclusivamente los archivos y directorios creados por esa operación; nunca se borran elementos
preexistentes. Una copia idéntica se reutiliza y una colisión distinta recibe un sufijo incremental.

Si el destino se encuentra dentro de la discoteca, se excluye por completo del escaneo de esa
ejecución. Los archivos originales nunca se modifican.

## Auditoría

La auditoría se recopila durante el escaneo normal. `simple` cuenta archivos, tags ausentes y errores.
`full` añade cada ruta, sus tags ausentes y el error concreto. Un archivo corrupto, un error inesperado
del lector o un directorio inaccesible se registra sin detener el resto; los fallos de directorio no se
contabilizan falsamente como canciones ilegibles.

## Pruebas y calidad

```bash
pytest
ruff check .
ruff format --check .
mypy playlist_builder
```

Los tests usan directorios temporales y lectores simulados: no acceden a la colección real. Cubren
normalización, años, filtros, tags ausentes, selección por rondas, límites, semillas, M3U, integridad
de caché, auditoría, colisiones, fallos de copia y rollback ante interrupciones. Incluyen además
regresiones obtenidas de ejemplos MP3 y FLAC
reales con `Artist`/`AlbumArtist`, géneros separados por comas y nombres Unicode descompuestos.

## Solución de problemas

- **La terminal muestra mal colores o teclas:** use Windows Terminal, iTerm2 o una terminal moderna;
  evite ejecutar dentro de una consola sin soporte interactivo. `Ctrl+C` cancela limpiamente.
- **Faltan tags:** ejecute `--audit full --audit-only` y corrija los archivos con un editor de tags.
- **Un formato figura como ilegible:** compruebe que el archivo se reproduce y pruebe `--rescan`.
  Mutagen puede reconocer el contenedor pero no una variante o etiqueta propietaria concreta.
- **Cambió música pero sigue la información anterior:** `--rescan` reconstruye la caché. La detección
  normal ya invalida entradas si cambia tamaño o fecha de modificación.
- **No puede escribir el M3U o copiar:** compruebe permisos sobre `MUSIC_ROOT` o el destino. La
  aplicación muestra la ruta problemática y no publica un M3U incompleto.
- **La reproducción desde otra máquina no encuentra archivos:** una playlist sin `--copy` contiene
  rutas relativas a la discoteca original. Use `--copy` para crear un árbol autocontenido.

## Estructura

```text
playlist_builder/
├── crear_playlist.py
├── pyproject.toml
├── playlist_builder/
│   ├── audit.py, cache.py, cli.py, config.py, copier.py
│   ├── filters.py, m3u.py, metadata.py, models.py
│   ├── normalization.py, scanner.py, selector.py, ui.py
└── tests/
```
