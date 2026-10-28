# Guía paso a paso para que Oye Claude siga funcionando (Linux)

Los comandos se escriben en una terminal normal y sirven para fish o bash.

---

## 1. Uso diario

1. Pulsa **Super + C**: se abre Oye Claude en el último proyecto que usaste.
2. Para hablar, pulsa **Super + Alt + C** (funciona con la app cerrada o abierta):
   1. suena un pitido y el cuadro de texto se marca en rojo con una barra de nivel;
   2. di lo que quieras y haz una pausa: se transcribe y se envía solo;
   3. si quieres cortar antes, pulsa el botón ⏹ del micrófono.
3. Cuando Claude pida permiso para editar o ejecutar algo, lee el diálogo y elige **Permitir**, **Permitir siempre** (solo en esta conversación) o **Denegar**.
4. Para cambiar de proyecto, usa el botón 📁 de arriba a la izquierda (la flechita muestra los recientes).
5. Para empezar de cero, usa el botón ＋ (**Ctrl + N**).

> Al cerrar la ventana no queda **nada** en segundo plano: ni micrófono ni procesos.

---

## 2. Comprobar que todo está bien (1 minuto)

1. Ábrela desde una terminal para ver los mensajes:
   ```bash
   oye-claude
   ```
2. Escribe «hola» y pulsa Intro: Claude debe responder.
3. Pulsa 🎙 y di «¿qué hora es?». En la terminal debe salir `cargando whisper small en cuda` (o `en cpu` si no hay GPU) y el texto debe aparecer en el chat.
4. Cierra la ventana.

---

## 3. Después de actualizar el sistema (`sudo pacman -Syu`)

| Si se actualizó… | Qué hacer |
|---|---|
| **python** (p. ej. 3.14 → 3.15) | La app deja de abrir. Ejecuta `~/oye-claude/linux/install.sh` (rehace el entorno solo). |
| **gtk4 / libadwaita / webkitgtk** | Normalmente nada. Si no abre, ejecuta el instalador. |
| **nvidia** (driver de la GPU) | **Reinicia el PC.** Hasta entonces la voz funciona en la CPU (más lenta). |
| **Claude Code** (se actualiza solo) | Nada. |

Truco: tras **cualquier** actualización grande, volver a ejecutar el instalador no hace daño y lo deja todo al día:

```bash
~/oye-claude/linux/install.sh
```

---

## 4. Actualizar Oye Claude desde GitHub

```bash
cd ~/oye-claude && git pull && ./linux/install.sh
```

Tu configuración (`~/.config/oye-claude/config.toml`) y tus atajos se mantienen.

---

## 5. Cambiar ajustes

1. Edita la configuración:
   ```bash
   nano ~/.config/oye-claude/config.toml
   ```
2. Cierra la app y vuelve a abrirla.

| Quiero… | Cambia |
|---|---|
| Otro micrófono | `input_device = "nombre"` (nombres: `oye-claude --list-mics`) |
| Revisar el texto dictado antes de enviarlo | `auto_send = false` |
| Más tiempo para pensar entre frases | `end_silence_ms = 2000` |
| Que entienda mejor lo que dicto | `model = "large-v3-turbo"` (con GPU va rápido; descarga 1,6 GB la primera vez) |
| Que corte bien con ruido / que me oiga hablando bajo | sube / baja `vad_margin_db` (15 / 8) |
| No usar la GPU (p. ej. al jugar) | `device = "cpu"` |
| Quitar el pitido | `beep = false` |

Para cambiar los **atajos de teclado**, ve a *Configuración → Teclado → Atajos de teclado → Ver y personalizar → Atajos personalizados*. Ahí están «Oye Claude» y «Oye Claude (voz)».

---

## 6. Si deja de funcionar: diagnóstico en orden

Para en el primer paso que falle.

1. **¿Abre la app?** Ejecuta `oye-claude` en una terminal.
   - `No module named …` o `python3.x: not found` → Python se actualizó: `~/oye-claude/linux/install.sh`.
   - `Namespace Adw/WebKit not available` → falta un paquete del sistema:
     ```bash
     sudo pacman -S --needed python-gobject gtk4 libadwaita webkitgtk-6.0
     ```
   - `command not found: oye-claude` → `~/.local/bin` no está en el PATH; ejecuta el instalador de nuevo.
2. **¿Abre pero Claude no responde / da error?**
   - Comprueba que `claude` funciona en la terminal y que tienes la sesión iniciada.
   - Si el error habla de autenticación o de `login`, ejecuta `claude` y sigue los pasos para iniciar sesión.
3. **¿Los atajos no hacen nada?**
   - Comprueba que existen:
     ```bash
     gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
     ```
   - Si no aparecen `oye-claude-voz` y el de Super+C, ejecuta el instalador de nuevo.
4. **¿El micrófono no capta nada?** (la barra de nivel no se mueve)
   - Comprueba el micro en *Configuración → Sonido → Entrada*.
   - O elige otro con `input_device` (sección 5).
5. **¿Capta, pero transcribe mal o «No he entendido nada»?**
   - Habla más cerca del micro.
   - Sube `end_silence_ms` si te corta a mitad de frase.
   - Prueba `model = "large-v3-turbo"`.
6. **¿Va lenta la voz?** Ejecuta `oye-claude` en la terminal. Si pone `no se pudo usar la GPU`, reinicia el PC (driver de NVIDIA actualizado) o comprueba que `nvidia-smi` funciona.

---

## 7. Consumo de recursos

- **Con la app cerrada:** nada.
- **Con la app abierta:** ~700 MB de RAM entre la app (~400 MB) y el motor web que dibuja el chat (~300 MB), más el proceso de `claude` desde el primer mensaje.
- **Tras usar la voz por primera vez:** el modelo de Whisper se queda cargado mientras la app esté abierta, para que las siguientes veces sea instantáneo:
  - con GPU: ~420 MB de memoria de vídeo;
  - sin GPU: ~500 MB de RAM.

---

## 8. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Código fuente (repo git) | `~/oye-claude` |
| App instalada + entorno Python | `~/.local/share/oye-claude/` |
| Comando `oye-claude` | `~/.local/bin/oye-claude` |
| Configuración | `~/.config/oye-claude/config.toml` |
| Último proyecto y recientes | `~/.local/state/oye-claude/state.json` |
| Entrada del menú e icono | `~/.local/share/applications/io.github.OyeClaude.desktop`, `~/.local/share/icons/hicolor/scalable/apps/` |
| Modelos de Whisper | `~/.cache/huggingface/hub/` |
| Conversaciones (las guarda Claude Code) | `~/.claude/projects/` |

## 9. Desinstalar

```bash
rm -rf ~/.local/share/oye-claude ~/.config/oye-claude ~/.local/state/oye-claude ~/.local/bin/oye-claude ~/.local/share/applications/io.github.OyeClaude.desktop ~/.local/share/icons/hicolor/scalable/apps/io.github.OyeClaude.svg
```

Luego borra los dos atajos en *Configuración → Teclado → Atajos personalizados*.
