# Guía paso a paso para que Oye Claude siga funcionando (Linux)

Todo lo de esta guía se hace desde una terminal normal. Los comandos están pensados para fish o bash.

---

## 1. Uso diario

1. **No hay que arrancar nada.** El servicio `oye-claude` se inicia solo cuando entras en tu sesión gráfica.
2. Entra en la carpeta de tu proyecto y abre Claude **con `claude-voz`** (no con `claude`):
   ```bash
   cd ~/mi-proyecto
   claude-voz
   ```
3. Habla:
   - «Oye Claude, *orden*» todo seguido, **o**
   - «Oye Claude» → espera el pitido → di la orden (tienes 8 s).
4. Para dejar la ventana sin cerrar Claude: `Ctrl+b` y luego `d`. Para volver: `claude-voz`.
5. Para cambiar de proyecto, cierra Claude (`/exit` o `Ctrl+d`) y vuelve a abrir `claude-voz` en la otra carpeta. Solo hay **una** sesión de voz a la vez (la sesión tmux `claude`).

> Si hablas sin haber abierto `claude-voz`, el daemon abre Claude solo en tu carpeta personal (`~`).

---

## 2. Comprobar que todo está bien (30 segundos)

```bash
systemctl --user status oye-claude
```
Debe poner **`active (running)`**. Luego mira lo que oye en vivo:

```bash
journalctl --user -u oye-claude -f
```

Di «Oye Claude, hola». Debes ver `¡activado!` y `→ Claude: hola`. Sal con `Ctrl+c`.

---

## 3. Después de actualizar el sistema (`sudo pacman -Syu`)

| Si se actualizó… | Qué hacer |
|---|---|
| **python** (p. ej. 3.14 → 3.15) | El entorno virtual se rompe y el servicio no arranca. Ejecuta `~/oye-claude/linux/install.sh` (lo detecta y lo rehace solo). |
| **pipewire / portaudio** | Normalmente nada. Si no oye, `systemctl --user restart oye-claude`. |
| **tmux** | Nada. Si `claude-voz` da error, cierra las sesiones viejas con `tmux kill-server`. |
| **Claude Code** (se actualiza solo) | Nada: el enlace `~/.local/bin/claude` siempre apunta a la versión nueva. |

Truco: tras **cualquier** actualización grande, ejecutar el instalador de nuevo no hace daño y lo deja todo al día:

```bash
~/oye-claude/linux/install.sh
```

---

## 4. Actualizar Oye Claude desde GitHub

```bash
cd ~/oye-claude
git pull
./linux/install.sh
```

Tu configuración (`~/.config/oye-claude/config.toml`) **no se toca** al reinstalar.

---

## 5. Cambiar ajustes

1. Edita la configuración:
   ```bash
   nano ~/.config/oye-claude/config.toml
   ```
2. Reinicia el servicio para aplicarla:
   ```bash
   systemctl --user restart oye-claude
   ```

Cambios típicos:

| Quiero… | Cambia |
|---|---|
| Otro micrófono | `input_device = "nombre"` (nombres en `oye-claude --list-devices`) |
| Que no se active con ruido | sube `vad_margin_db` (15–18) o `min_speech_s` (0.5) |
| Que me detecte mejor si hablo bajo | baja `vad_margin_db` (8–10) |
| Más precisión en las órdenes | `command_model = "medium"` (más lento) |
| Que retome la última conversación | `claude_command = "/home/d4/.local/bin/claude --continue"` |
| Que Claude se abra en otra carpeta por defecto | `workdir = "~/proyectos"` |
| Silenciar pitidos / avisos | `beep = false` / `notify = false` |

---

## 6. Si deja de funcionar: diagnóstico en orden

Ve paso por paso y para en el primero que falle.

1. **¿Está corriendo el servicio?**
   ```bash
   systemctl --user status oye-claude
   ```
   Si pone `failed`, mira el error:
   ```bash
   journalctl --user -u oye-claude -n 30 --no-pager
   ```
   - `No module named …` o `python3.x: not found` → Python se actualizó: `~/oye-claude/linux/install.sh`
   - `PortAudio` / `Invalid input device` → paso 2.
   - Otra cosa → `systemctl --user restart oye-claude` y vuelve a mirar.

2. **¿Llega audio del micrófono?** Para el servicio (solo para probar) y mide:
   ```bash
   systemctl --user stop oye-claude
   oye-claude --test-mic
   ```
   Al hablar debe aparecer `VOZ`; en silencio, no. Si la barra no se mueve: revisa que el micro esté conectado y elegido en *Ajustes → Sonido → Entrada* de GNOME, o ponlo en `input_device`. Al terminar:
   ```bash
   systemctl --user start oye-claude
   ```

3. **¿Te oye pero no se activa?** En `journalctl --user -u oye-claude -f` verás `(ignorado) …` con lo que entendió. Si escribe «Claude» de una forma rara (p. ej. «Clow»), añádela en `WAKE_RE` dentro de `~/oye-claude/linux/oye_claude.py` y reinstala con `./linux/install.sh`.

4. **¿Se activa pero no escribe en Claude?**
   ```bash
   oye-claude --say "hola"
   ```
   - `Falta tmux` → `sudo pacman -S tmux`
   - No aparece en tu ventana → probablemente abriste Claude con `claude` y no con `claude-voz`. Ciérralo y usa `claude-voz`.
   - La primera orden se pierde al abrir Claude → sube `claude_startup_s` a 8.

5. **¿Se activa sola?** Sube `vad_margin_db` y `min_speech_s` (sección 5). Silencia los altavoces cerca del micro si ves vídeos con gente diciendo «Claude».

---

## 7. Consumo de recursos

- En silencio: ~1–2 % de un núcleo de CPU, ~700 MB de RAM (los dos modelos de Whisper cargados).
- Cada vez que alguien habla cerca del micro (tú, Discord, un vídeo) se transcriben unos segundos con Whisper `base`, lo que gasta CPU en ese momento. Es normal.
- Para pausarlo un rato (p. ej. en una llamada o jugando):
  ```bash
  systemctl --user stop oye-claude
  ```
  Y para reanudarlo:
  ```bash
  systemctl --user start oye-claude
  ```
- Para que no arranque al iniciar sesión:
  ```bash
  systemctl --user disable oye-claude
  ```

---

## 8. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Código fuente (repo git) | `~/oye-claude` |
| Programa instalado + entorno Python | `~/.local/share/oye-claude/` |
| Comandos `oye-claude` y `claude-voz` | `~/.local/bin/` |
| Configuración | `~/.config/oye-claude/config.toml` |
| Servicio | `~/.config/systemd/user/oye-claude.service` |
| Modelos de Whisper (~650 MB) | `~/.cache/huggingface/hub/` |

Si reinstalas el sistema, basta con clonar el repo y ejecutar `linux/install.sh` (y copiar tu `config.toml` si lo personalizaste).
