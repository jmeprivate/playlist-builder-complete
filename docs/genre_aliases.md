# Alias y agrupaciones manuales de género

Los alias se declaran exclusivamente en `config.ini`, sin taxonomías automáticas ni servicios externos.
El bloque viene comentado en la configuración predeterminada para no cambiar el comportamiento de instalaciones nuevas.

```ini
[genre_aliases]
Jazz = jazz fusion; jazz/fusion; fusion
Electrónica = electronic; electronica; electrónica
```

La clave es el género canónico que aparece una sola vez en las opciones y cada valor separado por punto y coma es un alias adicional. La propia clave también coincide consigo misma.

Claves, alias y etiquetas se comparan ignorando mayúsculas, acentos, espacios repetidos y formas Unicode equivalentes, pero se conserva la escritura legible de la clave. Los géneros del catálogo que no estén cubiertos continúan mostrándose tal cual.

Una forma normalizada no puede pertenecer a dos canónicos y tampoco se admiten claves o alias vacíos. La aplicación detiene la ejecución con un error claro en vez de elegir una prioridad. Las exclusiones siguen prevaleciendo sobre las inclusiones al usar alias.

Esta configuración se carga en cada ejecución y solo interviene en la comparación y el filtro: no reescribe etiquetas, la caché ni los archivos musicales.
