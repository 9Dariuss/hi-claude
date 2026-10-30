# Guía paso a paso para que Hi Claude! siga funcionando (Windows)

Los comandos se escriben en **PowerShell** o en **Terminal** (clic derecho en el botón Inicio → Terminal).

---

## 1. Uso diario

1. Pulsa **Win + Alt + C**: se abre Hi Claude! en el último proyecto que usaste (o búscala en el menú Inicio).
2. Para hablar, pulsa **Win + Alt + V** (funciona con la app cerrada o abierta):
   1. suena un pitido y el cuadro de texto se marca en rojo con una barra de nivel;
   2. di lo que quieras y haz una pausa: se transcribe y se envía solo;
   3. si quieres cortar antes, pulsa el botón ⏹ del micrófono.
3. Cuando Claude pida permiso para editar o ejecutar algo, lee el diálogo y elige **Permitir**, **Permitir siempre** (solo en esta conversación) o **Denegar**.
4. Para cambiar de proyecto, pulsa el nombre del proyecto arriba a la izquierda: salen los recientes y «Elegir otra carpeta…» (**Ctrl + O**).
5. Para empezar de cero, usa el botón ＋ (**Ctrl + N**).
6. Para preguntar por algo que ves en pantalla (un error, un plano, una tabla…):
   1. pulsa **Win + Alt + X** (o el botón ✂): la pantalla se congela y se oscurece;
   2. arrastra con el ratón sobre la zona que te interesa y suelta (**Esc** o clic derecho cancela);
   3. en la ventanita, escribe o dicta la pregunta y pulsa Intro: la respuesta sale ahí mismo;
   4. si quieres seguir con más calma, pulsa el botón ⤢ de arriba a la izquierda para pasar la conversación a la ventana grande.
7. Para cambiar el **color principal** o el modo claro/oscuro: menú ⋮ → **Preferencias** (**Ctrl + ,**).
8. Cuando Claude termina y la ventana no está delante, su botón de la barra de tareas **parpadea**.

> Al cerrar la ventana no queda nada de la app funcionando: ni micrófono ni Claude. Solo sigue el proceso de los atajos (`pythonw.exe … --atajos`), que ocupa unos pocos MB y no usa CPU mientras no pulses un atajo.

---

## 2. Comprobar que todo está bien (1 minuto)

1. Abre una terminal **nueva** y ejecuta:
   ```powershell
   hi-claude
   ```
   Así se ven los mensajes en la terminal.
2. Escribe «hola» y pulsa Intro: Claude debe responder.
3. Pulsa 🎙 y di «¿qué hora es?». En la terminal debe salir `cargando whisper small en cuda` (o `en cpu` si no hay GPU NVIDIA) y el texto debe aparecer en el chat.
4. Cierra la ventana.

---

## 3. Después de actualizar Windows o Python

| Si se actualizó… | Qué hacer |
|---|---|
| **Python** (p. ej. 3.13 → 3.14) | Si la app no abre, vuelve a ejecutar `Instalar Hi Claude.cmd` (rehace el entorno solo). |
| **Windows** | Normalmente nada. |
| **Driver de NVIDIA** | **Reinicia el PC.** Hasta entonces la voz funciona en la CPU (más lenta). |
| **Claude Code** | Nada. |

Truco: volver a ejecutar el instalador nunca hace daño y lo deja todo al día.

---

## 4. Actualizar Hi Claude! desde GitHub

Con git:

```powershell
cd $HOME\hi-claude; git pull; .\windows\install.ps1
```

Sin git: descarga el ZIP de nuevo, descomprímelo encima y haz doble clic en `windows\Instalar Hi Claude.cmd`. Tu configuración se mantiene.

---

## 5. Cambiar ajustes

1. Menú ⋮ → **Preferencias** → **Abrir config.toml** (se abre en el Bloc de notas).
2. Cambia lo que quieras y guarda.
3. Cierra la app y vuelve a abrirla. Si cambiaste los **atajos**, ejecuta de nuevo el instalador (o cierra sesión en Windows y vuelve a entrar).

| Quiero… | Cambia |
|---|---|
| Otro micrófono | `input_device = "nombre"` (nombres: `hi-claude --list-mics`) |
| Más tiempo para pensar entre frases | `end_silence_ms = 2000` |
| Que entienda mejor lo que dicto | `model = "large-v3-turbo"` (con GPU va rápido; descarga 1,6 GB la primera vez) |
| Que corte bien con ruido / que me oiga hablando bajo | sube / baja `vad_margin_db` (15 / 8) |
| No usar la GPU (p. ej. al jugar) | `device = "cpu"` |
| Otros atajos | `hotkey_open = "Win+Alt+C"` (también valen `Ctrl`, `Shift` y `F1`…`F12`) |

---

## 6. Si deja de funcionar: diagnóstico en orden

Para en el primer paso que falle.

1. **¿Abre la app?** Ejecuta `hi-claude` en una terminal nueva.
   - `"hi-claude" no se reconoce…` → el instalador no llegó a terminar, o la terminal es anterior a la instalación: abre otra o vuelve a instalar.
   - `No module named …` → vuelve a ejecutar el instalador.
   - Si la abriste desde el menú Inicio, los errores quedan en `%LOCALAPPDATA%\hi-claude\hi-claude.log`.
2. **¿Abre pero Claude no responde / dice «Not logged in»?**
   - Inicia sesión una vez: en una terminal, `& "$env:LOCALAPPDATA\hi-claude\venv\Lib\site-packages\claude_agent_sdk\_bundled\claude.exe" auth login` (o `claude auth login` si tienes Claude Code instalado aparte).
3. **¿Los atajos no hacen nada?**
   - Mira si el proceso de los atajos está en marcha: Administrador de tareas → Detalles → `pythonw.exe`. Si no, haz doble clic en el acceso «Hi Claude! (atajos)» de la carpeta Inicio (`Win + R` → `shell:startup`) o vuelve a instalar.
   - Si otro programa usa la misma combinación, el registro dirá `no se pudo registrar…`: cambia la combinación en `config.toml`.
4. **¿El recorte no hace nada?** Ejecuta `hi-claude --snip` en una terminal para ver el error.
5. **¿El micrófono no capta nada?** (la barra de nivel no se mueve)
   - *Configuración → Privacidad y seguridad → Micrófono*: activa «Permitir que las aplicaciones de escritorio accedan al micrófono».
   - Comprueba el micro en *Configuración → Sistema → Sonido → Entrada*, o elige otro con `input_device`.
6. **¿Capta, pero transcribe mal o «No he entendido nada»?** Habla más cerca del micro, sube `end_silence_ms` si te corta a mitad de frase, o prueba `model = "large-v3-turbo"`.
7. **¿Va lenta la voz?** Si la terminal pone `no se pudo usar la GPU`, reinicia el PC (driver de NVIDIA actualizado) o comprueba que `nvidia-smi` funciona. Sin GPU NVIDIA siempre va en CPU (~2 s por frase con `small`).

---

## 7. Consumo de recursos

- **Con la app cerrada:** solo el proceso de los atajos, dormido (unos MB de RAM, 0 % de CPU).
- **Con la app abierta:** la app (~150 MB) y el motor web Edge WebView2 (~200 MB), más el proceso de `claude` desde el primer mensaje.
- **Tras usar la voz por primera vez:** el modelo de Whisper se queda cargado mientras la app esté abierta (~420 MB de memoria de vídeo con GPU; ~500 MB de RAM sin ella).

---

## 8. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| App instalada + entorno Python | `%LOCALAPPDATA%\hi-claude\` |
| Comando `hi-claude` | `%LOCALAPPDATA%\hi-claude\bin\hi-claude.cmd` (en tu PATH) |
| Configuración | `%APPDATA%\hi-claude\config.toml` |
| Preferencias, último proyecto y recientes | `%LOCALAPPDATA%\hi-claude\state.json` |
| Registro de errores (al abrirla sin terminal) | `%LOCALAPPDATA%\hi-claude\hi-claude.log` |
| Últimos 20 recortes | `%LOCALAPPDATA%\hi-claude\cache\recortes\` |
| Accesos directos | menú Inicio (`Hi Claude!`, `Hi Claude! (recorte)`) y `shell:startup` (`Hi Claude! (atajos)`) |
| Modelos de Whisper | `%USERPROFILE%\.cache\huggingface\hub\` |
| Conversaciones (las guarda Claude Code) | `%USERPROFILE%\.claude\projects\` |

## 9. Desinstalar

```powershell
powershell -ExecutionPolicy Bypass -File windows\desinstalar.ps1
```

Añade `-Todo` para borrar también `config.toml`.
