# Instalación en iPhone o iPad

Playlist Builder puede ejecutarse localmente en iOS/iPadOS mediante **a-Shell**. No se instala como una app nativa independiente: se ejecuta dentro de la terminal de a-Shell.

## Requisitos

- iOS/iPadOS 14 o posterior.
- La app a-Shell completa, con Python 3.12 o posterior.
- La música debe estar en una carpeta accesible desde la app Archivos. La biblioteca interna de Apple Music no se escanea directamente.

## Instalación

Abra a-Shell y ejecute:

```sh
curl -fsSL https://raw.githubusercontent.com/jmeprivate/playlist-builder-complete/main/install-ios.sh | sh
```

El instalador:

- comprueba que se está ejecutando en a-Shell y que Python es compatible;
- instala la release estable `v1.0.0` y sus dependencias Python puras;
- guarda la instalación en la carpeta de documentos de a-Shell;
- crea los comandos `crear-playlist` y `configurar-playlist`;
- conserva el `config.ini` existente cuando se vuelve a ejecutar para actualizar o reparar la instalación.

## Seleccionar la carpeta musical

En a-Shell:

```sh
pickFolder
pwd
configurar-playlist "RUTA_MOSTRADA_POR_PWD"
crear-playlist
```

`pickFolder` abre el selector de iOS. Elija la carpeta que contiene la discoteca. a-Shell guarda el permiso como un marcador para poder volver a esa ubicación.

También puede pasar la ruta durante la instalación:

```sh
curl -fsSL https://raw.githubusercontent.com/jmeprivate/playlist-builder-complete/main/install-ios.sh -o install-ios.sh
sh install-ios.sh "/ruta/seleccionada"
```

## Actualizar o reparar

Vuelva a ejecutar el mismo instalador. Se reemplaza el código instalado, pero se conserva la configuración y la carpeta musical seleccionada.

Para instalar expresamente otra release compatible:

```sh
PLAYLIST_BUILDER_VERSION=1.0.0 sh install-ios.sh
```

## Ubicaciones

- Programa y configuración: `PlaylistBuilder/` dentro de los documentos de a-Shell.
- Comandos: `bin/crear-playlist` y `bin/configurar-playlist`.
- Música predeterminada, si no se selecciona otra carpeta: `PlaylistBuilder/Music/`.

## Limitaciones de iOS

- Playlist Builder solo puede leer ubicaciones que iOS haya autorizado a a-Shell.
- Los procesos pueden detenerse cuando iOS suspende a-Shell; mantenga la app abierta durante escaneos o copias grandes.
- No se accede directamente a pistas protegidas o gestionadas exclusivamente por Apple Music.
- La interacción está pensada para la terminal de a-Shell; un teclado físico resulta más cómodo en colecciones grandes.
