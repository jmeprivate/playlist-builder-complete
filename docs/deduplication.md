# Deduplicación opcional por contenido

La deduplicación se activa con `--deduplicate` o con `deduplicate = true` en `config.ini`. La opción `--no-deduplicate` desactiva expresamente el valor configurado.

Se ejecuta después de aplicar las playlists de origen/exclusión y los filtros interactivos. Primero agrupa las candidatas por tamaño y solo calcula SHA-256, por bloques de 1 MiB, en grupos donde al menos dos archivos tienen el mismo tamaño. Por cada hash idéntico conserva de forma determinista la ruta relativa menor.

La aplicación no modifica, borra, enlaza ni renombra archivos originales. Si un archivo no puede leerse durante el hash, se registra el fallo y se mantiene como candidato porque no puede afirmarse que sea duplicado.

Los resultados se conservan en memoria durante la ejecución para no volver a leer los mismos archivos al mostrar de nuevo la preview o rehacer una selección con los mismos filtros. Los hashes no se guardan en la caché de metadatos ni se reutilizan entre ejecuciones.
