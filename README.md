# Rubencio bot 

[![](https://img.shields.io/badge/Rubencio-Telegram%20Bot-blue)]()

_Este proyecto es una modificación del bot de telegram [@puns2bot](https://telegram.me/puns2bot) que consiste en responder a los usuarios con rimas, frases, palabras y números según se configure en el chat._

#### Ejemplo (Español) 📋

-- He quedado con Carlos

-- ¿Que Carlos?

-- ¡¡El de los cojones largos!!

## Instalación 🔧

_Ir al [repo official](https://github.com/morenod/punsBot) para ver los [prerequisitos](https://github.com/morenod/punsBot#prerequisites) y los pasos de la [instalación](https://github.com/morenod/punsBot#installing) del bot._

## Uso 📖

- _Para iniciar el bot en un chat, agregue el contacto [@rubencio_bot](https://telegram.me/rubencio_bot) en él._

- _Para ver las combinaciones disponibles, ejecute **/list** o **/punslist**, se enumerarán las combinaciones predeterminadas, disponibles para todos los chats, y combinaciones específicas, agregados en su canal._

- _Para agregar una nueva combinacón, ejecute **/punadd** seguido de la palabra o número utilizado para ser detectado por el bot, un **"|"** char como separador y la combinación, por ejemplo:_

```
/punadd carlos|el de los cojones largos
```

- _Para agregar terminaciones de palabras, por ejemplo:_

```
/punadd ^.*ado$|el que tengo aquí colgado
```
_Este disparador detectará todas las palabras terminadas en ado, como Abogado, Certificado, etc._

- _Los juegos de palabras agregados se crean deshabilitados, deben ser validados por personas del chat. El karma mínimo requerido para habilitar una combinación de palabras se puede configurar con el parámetro **required_validations**._

- _Para agregar +1 al karma de un juego de palabras, ejecute:_ 
```
/punapprove palabra
```
- _Para agregar -1 al karma de un juego de palabras, ejecute:_ 
```
/punban palabra
```
- _Para eliminar un juego de palabras, ejecute:_
```
/pundel palabra.
```

## Licencia 📄

Este proyecto está bajo la Licencia (MIT License) - mira el archivo [LICENSE.md](LICENSE.md) para detalles.




---
Proyecto original **[punsbot](https://github.com/morenod/punsBot)** traducido y modificado por [![](https://img.shields.io/badge/cesar-estrada-brightgreen)](https://github.com/cesar-estrada)